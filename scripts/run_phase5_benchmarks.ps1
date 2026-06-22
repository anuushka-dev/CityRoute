param(
    [ValidateSet("local", "docker", "both")]
    [string]$Mode = "local",

    [int[]]$Sizes = @(5, 10, 15),

    [string]$Phase5Algorithm = "bidirectional_astar",

    [switch]$SkipPhase5,

    [switch]$SkipPhase51
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Invoke-PythonBenchmark {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host ">>> python $ScriptPath $($Arguments -join ' ')" -ForegroundColor Cyan

    & python $ScriptPath @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: python $ScriptPath $($Arguments -join ' ')"
    }
}

function Test-CityRouteApi {
    param(
        [string]$BaseUrl,
        [string]$CurrentMode
    )

    Write-Host ""
    Write-Host "Checking $CurrentMode API at $BaseUrl ..." -ForegroundColor Yellow

    $health = Invoke-RestMethod "$BaseUrl/health"
    $stats = Invoke-RestMethod "$BaseUrl/graph/stats"

    if ($health.status -ne "ok") {
        throw "$CurrentMode health check failed."
    }

    if ($health.graph_loaded -ne $true) {
        throw "$CurrentMode graph_loaded is not True."
    }

    if ($stats.graph_loaded -ne $true) {
        throw "$CurrentMode graph stats graph_loaded is not True."
    }

    Write-Host "$CurrentMode API OK. graph_loaded=True" -ForegroundColor Green
}

function Save-CityRouteEvidence {
    param(
        [string]$BaseUrl,
        [string]$CurrentMode
    )

    $phase5Dir = "benchmarks\phase5\$($CurrentMode)_results"
    $phase51Dir = "benchmarks\phase5_1\$($CurrentMode)_results"

    New-Item -ItemType Directory $phase5Dir -Force | Out-Null
    New-Item -ItemType Directory $phase51Dir -Force | Out-Null

    Invoke-RestMethod "$BaseUrl/health" |
        ConvertTo-Json -Depth 10 |
        Out-File "$phase5Dir\phase5_$($CurrentMode)_health.json" -Encoding utf8

    Invoke-RestMethod "$BaseUrl/graph/stats" |
        ConvertTo-Json -Depth 10 |
        Out-File "$phase5Dir\phase5_$($CurrentMode)_graph_stats.json" -Encoding utf8

    Invoke-RestMethod "$BaseUrl/health" |
        ConvertTo-Json -Depth 10 |
        Out-File "$phase51Dir\phase5_1_$($CurrentMode)_health.json" -Encoding utf8

    Invoke-RestMethod "$BaseUrl/graph/stats" |
        ConvertTo-Json -Depth 10 |
        Out-File "$phase51Dir\phase5_1_$($CurrentMode)_graph_stats.json" -Encoding utf8

    Write-Host "Saved $CurrentMode health/stats evidence." -ForegroundColor Green
}

function Run-Phase5Benchmarks {
    param(
        [string]$CurrentMode
    )

    foreach ($n in $Sizes) {
        Invoke-PythonBenchmark "benchmarks\phase5_matrix_benchmark.py" @(
            "--mode", $CurrentMode,
            "--n", "$n",
            "--algorithm", $Phase5Algorithm
        )
    }

    foreach ($n in $Sizes) {
        Invoke-PythonBenchmark "benchmarks\phase5_cache_probe.py" @(
            "--mode", $CurrentMode,
            "--n", "$n",
            "--algorithm", $Phase5Algorithm
        )
    }

    foreach ($n in $Sizes) {
        Invoke-PythonBenchmark "benchmarks\phase5_parallel_vs_serial_probe.py" @(
            "--mode", $CurrentMode,
            "--n", "$n",
            "--algorithm", $Phase5Algorithm
        )
    }

    foreach ($n in $Sizes) {
        Invoke-PythonBenchmark "benchmarks\phase5_matrix_correctness_probe.py" @(
            "--mode", $CurrentMode,
            "--n", "$n",
            "--algorithm", $Phase5Algorithm
        )
    }
}

function Run-Phase51Benchmarks {
    param(
        [string]$CurrentMode
    )

    foreach ($n in $Sizes) {
        Invoke-PythonBenchmark "benchmarks\phase5_1_algorithm_comparison.py" @(
            "--mode", $CurrentMode,
            "--n", "$n",
            "--tolerance-m", "0.01"
        )
    }

    foreach ($n in $Sizes) {
        Invoke-PythonBenchmark "benchmarks\phase5_1_source_dijkstra_correctness.py" @(
            "--mode", $CurrentMode,
            "--n", "$n",
            "--tolerance-m", "0.01",
            "--compare-bidirectional"
        )
    }
}

function Run-Mode {
    param(
        [string]$CurrentMode
    )

    if ($CurrentMode -eq "local") {
        $baseUrl = "http://127.0.0.1:8000"
    }
    elseif ($CurrentMode -eq "docker") {
        $baseUrl = "http://127.0.0.1:8001"
    }
    else {
        throw "Unsupported mode: $CurrentMode"
    }

    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Magenta
    Write-Host "Running Phase 5 / 5.1 benchmarks for mode: $CurrentMode" -ForegroundColor Magenta
    Write-Host "Base URL: $baseUrl" -ForegroundColor Magenta
    Write-Host "Sizes: $($Sizes -join ', ')" -ForegroundColor Magenta
    Write-Host "==================================================" -ForegroundColor Magenta

    Test-CityRouteApi -BaseUrl $baseUrl -CurrentMode $CurrentMode

    if (-not $SkipPhase5) {
        Write-Host ""
        Write-Host "Running Phase 5 benchmarks..." -ForegroundColor Yellow
        Run-Phase5Benchmarks -CurrentMode $CurrentMode
    }
    else {
        Write-Host "Skipping Phase 5 benchmarks." -ForegroundColor Yellow
    }

    if (-not $SkipPhase51) {
        Write-Host ""
        Write-Host "Running Phase 5.1 benchmarks..." -ForegroundColor Yellow
        Run-Phase51Benchmarks -CurrentMode $CurrentMode
    }
    else {
        Write-Host "Skipping Phase 5.1 benchmarks." -ForegroundColor Yellow
    }

    Save-CityRouteEvidence -BaseUrl $baseUrl -CurrentMode $CurrentMode

    Write-Host ""
    Write-Host "$CurrentMode benchmark run complete." -ForegroundColor Green
}

if ($Mode -eq "both") {
    Run-Mode -CurrentMode "local"
    Run-Mode -CurrentMode "docker"
}
else {
    Run-Mode -CurrentMode $Mode
}

Write-Host ""
Write-Host "All requested Phase 5 / 5.1 benchmarks completed." -ForegroundColor Green