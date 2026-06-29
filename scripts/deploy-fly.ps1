$ErrorActionPreference = "Stop"
$flyctl = "$env:USERPROFILE\.fly\bin\flyctl.exe"

Write-Host "=== ExecutionDesk AI - Fly.io Deploy ===" -ForegroundColor Cyan

# Check auth
& $flyctl auth whoami
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in. Run: $flyctl auth login" -ForegroundColor Red
    exit 1
}

# Deploy backend
Write-Host "`n--- Deploying Backend ---" -ForegroundColor Yellow
& $flyctl deploy --config fly.backend.toml --remote-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "Backend deploy failed" -ForegroundColor Red
    exit 1
}

# Create volume if needed (first deploy only)
& $flyctl volumes list --config fly.backend.toml 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating data volume..." -ForegroundColor Yellow
    & $flyctl volumes create edai_data --config fly.backend.toml --region iad --size 1
}

Write-Host "Backend deployed: https://executiondesk-api.fly.dev" -ForegroundColor Green

# Deploy frontend
Write-Host "`n--- Deploying Frontend ---" -ForegroundColor Yellow
& $flyctl deploy --config fly.frontend.toml --remote-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "Frontend deploy failed" -ForegroundColor Red
    exit 1
}

Write-Host "Frontend deployed: https://executiondesk-ui.fly.dev" -ForegroundColor Green
Write-Host "`n=== Deploy Complete ===" -ForegroundColor Cyan
Write-Host "API:  https://executiondesk-api.fly.dev/health"
Write-Host "App:  https://executiondesk-ui.fly.dev"
