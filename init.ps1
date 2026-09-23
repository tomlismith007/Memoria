#!/usr/bin/env pwsh
# Standard startup and verification path (Windows / pwsh)
# Mirrors init.sh for environments without bash.
$ErrorActionPreference = "Stop"

Write-Host "=== Harness Initialization ==="

Write-Host "=== python -m pytest -q ==="
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (Test-Path "frontend/node_modules") {
    Write-Host "=== npm run build (frontend) ==="
    Push-Location frontend
    npm run build
    $feCode = $LASTEXITCODE
    Pop-Location
    if ($feCode -ne 0) { exit $feCode }
}

Write-Host "=== Verification Complete ==="
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Read feature_list.json to see current feature state"
Write-Host "2. Pick ONE unfinished feature to work on"
Write-Host "3. Implement only that feature"
Write-Host "4. Re-run verification before claiming done"