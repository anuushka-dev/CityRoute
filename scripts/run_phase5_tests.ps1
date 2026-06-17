$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Invoke-Step {
    param(
        [string]$Title,
        [string[]]$CommandParts
    )

    Write-Host ""
    Write-Host ">>> $Title" -ForegroundColor Cyan
    Write-Host "$($CommandParts -join ' ')" -ForegroundColor DarkGray

    $command = $CommandParts[0]
    $arguments = $CommandParts[1..($CommandParts.Length - 1)]

    & $command @arguments

    if ($LASTEXITCODE -ne 0) {
        throw "Failed: $Title"
    }
}

$CompileFiles = @(
    "app\core\graph_adjacency.py",
    "app\core\multi_target_dijkstra.py",
    "app\core\distance_matrix.py",
    "app\models\matrix_model.py",
    "app\services\matrix_service.py",
    "benchmarks\phase5_matrix_benchmark.py",
    "benchmarks\phase5_cache_probe.py",
    "benchmarks\phase5_parallel_vs_serial_probe.py",
    "benchmarks\phase5_matrix_correctness_probe.py",
    "benchmarks\phase5_1_algorithm_comparison.py",
    "benchmarks\phase5_1_source_dijkstra_correctness.py"
)

foreach ($file in $CompileFiles) {
    Invoke-Step "Compile $file" @("python", "-m", "py_compile", $file)
}

$TargetedTests = @(
    "tests\test_matrix_endpoint.py",
    "tests\test_matrix_service.py",
    "tests\test_matrix_cache_key.py",
    "tests\test_redis_cache.py",
    "tests\test_graph_adjacency.py",
    "tests\test_multi_target_dijkstra.py",
    "tests\test_distance_matrix_source_dijkstra.py"
)

foreach ($testFile in $TargetedTests) {
    Invoke-Step "Run $testFile" @("python", "-m", "pytest", $testFile, "-v")
}

Invoke-Step "Run full pytest suite" @("python", "-m", "pytest", "-v")

Write-Host ""
Write-Host "All Phase 5 / 5.1 tests completed successfully." -ForegroundColor Green