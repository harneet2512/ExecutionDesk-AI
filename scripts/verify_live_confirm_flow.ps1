# Verify end-to-end LIVE confirmation flow
# This script starts the backend if needed, runs the verification test,
# and exits with non-zero if any step fails.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

Set-Location $ProjectDir

Write-Host "=== LIVE Confirmation Flow Verification ===" -ForegroundColor Cyan
Write-Host ""

function Test-Backend {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8004/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

$StartedBackend = $false
$BackendProcess = $null

# Check if backend is running
if (-not (Test-Backend)) {
    Write-Host "Backend not running. Starting..."
    
    # Activate venv if exists
    if (Test-Path ".venv\Scripts\Activate.ps1") {
        . .\.venv\Scripts\Activate.ps1
    }
    
    # Start backend in background
    $BackendProcess = Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8004" -PassThru -NoNewWindow
    
    # Wait for backend to be ready (max 30 seconds)
    Write-Host "Waiting for backend to start..."
    $attempts = 0
    while ($attempts -lt 30) {
        if (Test-Backend) {
            Write-Host "Backend started (PID: $($BackendProcess.Id))"
            break
        }
        Start-Sleep -Seconds 1
        $attempts++
    }
    
    if (-not (Test-Backend)) {
        Write-Host "ERROR: Backend failed to start" -ForegroundColor Red
        if ($BackendProcess) { Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue }
        exit 1
    }
    
    $StartedBackend = $true
} else {
    Write-Host "Backend already running"
}

Write-Host ""
Write-Host "Running verification script..."
Write-Host ""

# Run the Python verification script
try {
    python scripts\verify_live_confirm.py
    $Result = $LASTEXITCODE
} catch {
    $Result = 1
}

# Cleanup if we started the backend
if ($StartedBackend -and $BackendProcess) {
    Write-Host ""
    Write-Host "Stopping backend..."
    Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
}

# Exit with the verification script's result
if ($Result -eq 0) {
    Write-Host ""
    Write-Host "=== VERIFICATION PASSED ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host ""
    Write-Host "=== VERIFICATION FAILED ===" -ForegroundColor Red
    exit 1
}
