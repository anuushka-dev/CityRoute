# CityRoute Phase 12 - Historical Evidence Collector
#
# Purpose:
#   Read-only inventory of project evidence.
#
# This script:
#   - DOES collect metadata
#   - DOES collect Git state
#   - DOES inventory benchmarks
#   - DOES inventory tests
#   - DOES identify evidence candidates
#
# This script does NOT:
#   - modify project files
#   - delete files
#   - rename files
#   - hash files
#   - classify evidence
#   - decide whether evidence is valid

$ErrorActionPreference = "Stop"

$repoRoot = (Get-Location).Path
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$evidenceRoot = Join-Path $repoRoot ".phase12_evidence"
$runRoot = Join-Path $evidenceRoot "collection_$timestamp"
$manifestRoot = Join-Path $runRoot "manifests"

New-Item -ItemType Directory -Force -Path $manifestRoot | Out-Null

Write-Host ""
Write-Host "==============================================="
Write-Host " CityRoute Phase 12 Evidence Collector"
Write-Host "==============================================="
Write-Host ""

Write-Host "Repository:"
Write-Host "  $repoRoot"

Write-Host ""
Write-Host "Collection:"
Write-Host "  $runRoot"

function Get-RelativePath {
    param(
        [string]$BasePath,
        [string]$FullPath
    )

    $base = [System.IO.Path]::GetFullPath($BasePath)
    $full = [System.IO.Path]::GetFullPath($FullPath)

    if (-not $base.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $base += [System.IO.Path]::DirectorySeparatorChar
    }

    $baseUri = [System.Uri]$base
    $fullUri = [System.Uri]$full

    return [System.Uri]::UnescapeDataString(
        $baseUri.MakeRelativeUri($fullUri).ToString()
    ).Replace("/", "\")
}

# ------------------------------------------------------------
# 1. Git state
# ------------------------------------------------------------

Write-Host "[1/8] Collecting Git state..."

$gitManifest = [ordered]@{
    collected_at = (Get-Date).ToString("o")
    repository_root = $repoRoot
    branch = $null
    commit = $null
    short_commit = $null
    status = @()
    remotes = @()
}

try {
    $gitManifest.branch = (git branch --show-current 2>$null).Trim()
}
catch {
    $gitManifest.branch = $null
}

try {
    $gitManifest.commit = (git rev-parse HEAD 2>$null).Trim()
}
catch {
    $gitManifest.commit = $null
}

try {
    $gitManifest.short_commit = (git rev-parse --short HEAD 2>$null).Trim()
}
catch {
    $gitManifest.short_commit = $null
}

try {
    $gitManifest.status = @(git status --short 2>$null)
}
catch {
    $gitManifest.status = @()
}

try {
    $gitManifest.remotes = @(git remote -v 2>$null)
}
catch {
    $gitManifest.remotes = @()
}

$gitManifest |
    ConvertTo-Json -Depth 10 |
    Set-Content -Path "$manifestRoot\git_state.json" -Encoding UTF8

# ------------------------------------------------------------
# 2. Environment
# ------------------------------------------------------------

Write-Host "[2/8] Collecting environment metadata..."

$environment = [ordered]@{
    collected_at = (Get-Date).ToString("o")
    repository_root = $repoRoot
    current_directory = (Get-Location).Path
    powershell_version = $PSVersionTable.PSVersion.ToString()
    os_version = [System.Environment]::OSVersion.VersionString
    machine = $env:COMPUTERNAME
    username = $env:USERNAME
}

$environment |
    ConvertTo-Json -Depth 10 |
    Set-Content -Path "$manifestRoot\environment.json" -Encoding UTF8

# ------------------------------------------------------------
# 3. Benchmark inventory
# ------------------------------------------------------------

Write-Host "[3/8] Inventorying benchmarks..."

$benchmarkRoot = Join-Path $repoRoot "benchmarks"
$benchmarkFiles = @()

if (Test-Path $benchmarkRoot) {

    $benchmarkFiles = @(
        Get-ChildItem `
            -Path $benchmarkRoot `
            -Recurse `
            -File `
            -Force `
            -ErrorAction SilentlyContinue |
        ForEach-Object {

            [PSCustomObject]@{
                relative_path = Get-RelativePath $repoRoot $_.FullName
                full_path = $_.FullName
                name = $_.Name
                extension = $_.Extension
                directory = Get-RelativePath $repoRoot $_.DirectoryName
                length_bytes = $_.Length
                created_utc = $_.CreationTimeUtc.ToString("o")
                modified_utc = $_.LastWriteTimeUtc.ToString("o")
            }
        }
    )
}

$benchmarkFiles |
    Export-Csv `
        -Path "$manifestRoot\benchmark_inventory.csv" `
        -NoTypeInformation `
        -Encoding UTF8

# ------------------------------------------------------------
# 4. Phase 1-11 inventory
# ------------------------------------------------------------

Write-Host "[4/8] Inventorying Phase 1-11 directories..."

$phaseInventory = @()

for ($phase = 1; $phase -le 11; $phase++) {

    $phaseName = "phase_$phase"
    $phasePath = Join-Path $benchmarkRoot $phaseName

    if (Test-Path $phasePath) {

        $files = @(
            Get-ChildItem `
                -Path $phasePath `
                -Recurse `
                -File `
                -Force `
                -ErrorAction SilentlyContinue
        )

        $directories = @(
            Get-ChildItem `
                -Path $phasePath `
                -Recurse `
                -Directory `
                -Force `
                -ErrorAction SilentlyContinue
        )

        $phaseInventory += [PSCustomObject]@{
            phase = $phase
            directory = Get-RelativePath $repoRoot $phasePath
            exists = $true
            file_count = $files.Count
            directory_count = $directories.Count
        }
    }
    else {

        $phaseInventory += [PSCustomObject]@{
            phase = $phase
            directory = "benchmarks\$phaseName"
            exists = $false
            file_count = 0
            directory_count = 0
        }
    }
}

$phaseInventory |
    Export-Csv `
        -Path "$manifestRoot\phase_inventory.csv" `
        -NoTypeInformation `
        -Encoding UTF8

# ------------------------------------------------------------
# 5. Evidence candidates
# ------------------------------------------------------------

Write-Host "[5/8] Identifying evidence candidates..."

$evidencePattern = '(?i)(audit|evidence|benchmark|probe|summary|report|result|metrics|performance|load|stress|concurrency|reliability|phase)'

$evidenceCandidates = @()

if ($benchmarkFiles.Count -gt 0) {

    $evidenceCandidates = @(
        $benchmarkFiles |
        Where-Object {
            $_.name -match $evidencePattern -or
            $_.relative_path -match $evidencePattern
        }
    )
}

$evidenceCandidates |
    Export-Csv `
        -Path "$manifestRoot\evidence_candidates.csv" `
        -NoTypeInformation `
        -Encoding UTF8

# ------------------------------------------------------------
# 6. Important project files
# ------------------------------------------------------------

Write-Host "[6/8] Inventorying important project files..."

$importantNames = @(
    "README.md",
    "Makefile",
    "pyproject.toml",
    "requirements.txt",
    "requirements-prod.txt",
    "Dockerfile",
    "docker-compose.yml",
    "pytest.ini",
    ".gitignore",
    ".dockerignore"
)

$importantFiles = @()

foreach ($name in $importantNames) {

    $path = Join-Path $repoRoot $name

    if (Test-Path $path) {

        $item = Get-Item $path

        $importantFiles += [PSCustomObject]@{
            relative_path = Get-RelativePath $repoRoot $item.FullName
            full_path = $item.FullName
            name = $item.Name
            extension = $item.Extension
            length_bytes = $item.Length
            modified_utc = $item.LastWriteTimeUtc.ToString("o")
        }
    }
}

$importantFiles |
    Export-Csv `
        -Path "$manifestRoot\project_files.csv" `
        -NoTypeInformation `
        -Encoding UTF8

# ------------------------------------------------------------
# 7. Test inventory
# ------------------------------------------------------------

Write-Host "[7/8] Inventorying tests..."

$testsRoot = Join-Path $repoRoot "tests"
$testFiles = @()

if (Test-Path $testsRoot) {

    $testFiles = @(
        Get-ChildItem `
            -Path $testsRoot `
            -Recurse `
            -File `
            -Force `
            -ErrorAction SilentlyContinue |
        ForEach-Object {

            [PSCustomObject]@{
                relative_path = Get-RelativePath $repoRoot $_.FullName
                full_path = $_.FullName
                name = $_.Name
                extension = $_.Extension
                length_bytes = $_.Length
                modified_utc = $_.LastWriteTimeUtc.ToString("o")
            }
        }
    )
}

$testFiles |
    Export-Csv `
        -Path "$manifestRoot\test_inventory.csv" `
        -NoTypeInformation `
        -Encoding UTF8

# ------------------------------------------------------------
# 8. Summary
# ------------------------------------------------------------

Write-Host "[8/8] Writing collection summary..."

$phasesFound = @(
    $phaseInventory |
    Where-Object { $_.exists -eq $true } |
    Select-Object -ExpandProperty phase
)

$summary = [ordered]@{
    collected_at = (Get-Date).ToString("o")
    repository = $repoRoot
    collection_directory = $runRoot
    benchmark_file_count = $benchmarkFiles.Count
    evidence_candidate_count = $evidenceCandidates.Count
    test_file_count = $testFiles.Count
    phases_found = $phasesFound
}

$summary |
    ConvertTo-Json -Depth 10 |
    Set-Content -Path "$manifestRoot\collection_summary.json" -Encoding UTF8

Write-Host ""
Write-Host "==============================================="
Write-Host " Collection complete"
Write-Host "==============================================="
Write-Host ""

Write-Host "Collection directory:"
Write-Host "  $runRoot"

Write-Host ""
Write-Host "Benchmark files:"
Write-Host "  $($benchmarkFiles.Count)"

Write-Host "Evidence candidates:"
Write-Host "  $($evidenceCandidates.Count)"

Write-Host "Test files:"
Write-Host "  $($testFiles.Count)"

Write-Host ""
Write-Host "Manifest files:"

Get-ChildItem -Path $manifestRoot -File |
    Select-Object -ExpandProperty Name |
    ForEach-Object {
        Write-Host "  $_"
    }

Write-Host ""
Write-Host "NO SOURCE FILES WERE MODIFIED."
Write-Host "NO FILES WERE HASHED."
Write-Host "NO FILES WERE DELETED."
Write-Host ""