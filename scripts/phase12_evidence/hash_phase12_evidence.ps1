# CityRoute Phase 12 - Evidence Hashing
#
# Purpose:
#   SHA-256 fingerprint the exact files discovered by the
#   Phase 12 evidence collector.
#
# This script:
#   - reads the existing benchmark inventory
#   - calculates SHA-256
#   - records file metadata
#   - writes a hash manifest
#
# This script does NOT:
#   - modify evidence files
#   - rename evidence
#   - delete evidence
#   - classify evidence
#   - alter benchmark results

$ErrorActionPreference = "Stop"

$repoRoot = (Get-Location).Path

$evidenceRoot = Join-Path $repoRoot ".phase12_evidence"

if (-not (Test-Path $evidenceRoot)) {
    throw "Phase 12 evidence directory does not exist."
}

$collections = @(
    Get-ChildItem `
        -Path $evidenceRoot `
        -Directory `
        -Filter "collection_*" |
    Sort-Object Name -Descending
)

if ($collections.Count -eq 0) {
    throw "No evidence collection found."
}

$collection = $collections[0]
$collectionRoot = $collection.FullName
$manifestRoot = Join-Path $collectionRoot "manifests"

$inventoryPath = Join-Path $manifestRoot "benchmark_inventory.csv"

if (-not (Test-Path $inventoryPath)) {
    throw "benchmark_inventory.csv not found."
}

$hashOutput = Join-Path $manifestRoot "sha256_manifest.csv"

Write-Host ""
Write-Host "==============================================="
Write-Host " CityRoute Phase 12 Evidence Hashing"
Write-Host "==============================================="
Write-Host ""

Write-Host "Collection:"
Write-Host "  $collectionRoot"

Write-Host ""

$files = @(Import-Csv $inventoryPath)

Write-Host "Files to hash:"
Write-Host "  $($files.Count)"

Write-Host ""

$results = New-Object System.Collections.Generic.List[object]

$counter = 0

foreach ($entry in $files) {

    $counter++

    $path = $entry.full_path

    Write-Progress `
        -Activity "Hashing evidence" `
        -Status "$counter / $($files.Count): $($entry.name)" `
        -PercentComplete (($counter / $files.Count) * 100)

    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {

        $results.Add(
            [PSCustomObject]@{
                relative_path = $entry.relative_path
                full_path = $path
                extension = $entry.extension
                length_bytes = $entry.length_bytes
                created_utc = $entry.created_utc
                modified_utc = $entry.modified_utc
                sha256 = $null
                hash_status = "MISSING"
            }
        )

        continue
    }

    try {

        $hash = Get-FileHash `
            -LiteralPath $path `
            -Algorithm SHA256

        $results.Add(
            [PSCustomObject]@{
                relative_path = $entry.relative_path
                full_path = $path
                extension = $entry.extension
                length_bytes = $entry.length_bytes
                created_utc = $entry.created_utc
                modified_utc = $entry.modified_utc
                sha256 = $hash.Hash
                hash_status = "OK"
            }
        )
    }
    catch {

        $results.Add(
            [PSCustomObject]@{
                relative_path = $entry.relative_path
                full_path = $path
                extension = $entry.extension
                length_bytes = $entry.length_bytes
                created_utc = $entry.created_utc
                modified_utc = $entry.modified_utc
                sha256 = $null
                hash_status = "ERROR"
            }
        )
    }
}

Write-Progress `
    -Activity "Hashing evidence" `
    -Completed

$results |
    Export-Csv `
        -Path $hashOutput `
        -NoTypeInformation `
        -Encoding UTF8

$okCount = @(
    $results |
    Where-Object { $_.hash_status -eq "OK" }
).Count

$missingCount = @(
    $results |
    Where-Object { $_.hash_status -eq "MISSING" }
).Count

$errorCount = @(
    $results |
    Where-Object { $_.hash_status -eq "ERROR" }
).Count

Write-Host ""
Write-Host "==============================================="
Write-Host " Hashing complete"
Write-Host "==============================================="
Write-Host ""

Write-Host "Total:"
Write-Host "  $($results.Count)"

Write-Host "Successfully hashed:"
Write-Host "  $okCount"

Write-Host "Missing:"
Write-Host "  $missingCount"

Write-Host "Errors:"
Write-Host "  $errorCount"

Write-Host ""
Write-Host "SHA-256 manifest:"
Write-Host "  $hashOutput"

Write-Host ""
Write-Host "Evidence files were not modified."
Write-Host ""