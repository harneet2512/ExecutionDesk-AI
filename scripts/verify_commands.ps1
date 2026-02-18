# verify_commands.ps1 - Wrapper for end-to-end verification
#
# Usage:
#   .\scripts\verify_commands.ps1
#   $env:BACKEND_URL = "http://localhost:9000"; .\scripts\verify_commands.ps1
#
# Runs Command A (Analyze portfolio) and Command B (Buy most profitable) through
# the trading platform and verifies the response.

param(
    [string]$BackendUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Push-Location $ProjectRoot

try {
    # Check if backend is running
    Write-Host "=== Checking backend health ===" -ForegroundColor Cyan
    try {
        $response = Invoke-WebRequest -Uri "$BackendUrl/api/v1/ops/health" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -ne 200) {
            throw "Backend returned non-200 status"
        }
    }
    catch {
        Write-Host "ERROR: Backend not running on $BackendUrl" -ForegroundColor Red
        Write-Host "Start it with: uvicorn backend.api.main:app --port 8000"
        exit 1
    }

    # Run verification
    Write-Host "=== Running verification script ===" -ForegroundColor Cyan
    $env:BACKEND_URL = $BackendUrl
    python scripts/verify_commands.py

    $ExitCode = $LASTEXITCODE
    if ($ExitCode -eq 0) {
        Write-Host ""
        Write-Host "=== VERIFICATION PASSED ===" -ForegroundColor Green
    }
    else {
        Write-Host ""
        Write-Host "=== VERIFICATION FAILED ===" -ForegroundColor Red
    }

    exit $ExitCode
}
finally {
    Pop-Location
}
