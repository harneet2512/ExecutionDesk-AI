# Run tests (backend + frontend)

# Activate venv if it exists
if (Test-Path ".venv") {
    & .\.venv\Scripts\Activate.ps1
}

# Set test database
$env:TEST_DATABASE_URL = "sqlite:///./test_enterprise.db"
$env:DATABASE_URL = $env:TEST_DATABASE_URL

# Remove test DB if exists
if (Test-Path "test_enterprise.db") {
    Remove-Item test_enterprise.db
}

Write-Host "Running backend tests..." -ForegroundColor Cyan
python -m pytest tests/ -v --tb=short

# Frontend smoke test
if (Test-Path "frontend") {
    Write-Host "Running frontend smoke test..." -ForegroundColor Cyan
    Push-Location frontend
    if (Test-Path "tests/smoke.spec.ts") {
        npx playwright test tests/smoke.spec.ts
    } else {
        Write-Host "Frontend smoke test not found, skipping..." -ForegroundColor Yellow
    }
    Pop-Location
}

Write-Host "Tests complete!" -ForegroundColor Green
