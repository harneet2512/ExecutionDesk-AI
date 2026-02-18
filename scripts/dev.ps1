# Dev script for Windows (PowerShell)

# Activate venv if it exists
if (Test-Path ".venv") {
    & ".venv\Scripts\Activate.ps1"
}

Write-Host "Starting backend and frontend..." -ForegroundColor Green

# Clean stale .next build artifacts (prevents ChunkLoadError from OneDrive sync)
if (Test-Path "frontend\.next") {
    Write-Host "Cleaning stale .next build cache..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "frontend\.next" -ErrorAction SilentlyContinue
}

# Kill existing processes on ports 8000 and 3000
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

# Start backend
$backendJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    Set-Location backend
    uvicorn api.main:app --reload --port 8000
}

# Start frontend if package.json exists
if (Test-Path "frontend\package.json") {
    $frontendJob = Start-Job -ScriptBlock {
        Set-Location $using:PWD
        Set-Location frontend
        npm run dev
    }
}

Write-Host "Backend: http://localhost:8000" -ForegroundColor Cyan
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow

# Wait for Ctrl+C
try {
    Wait-Job $backendJob, $frontendJob
} finally {
    Stop-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
}
