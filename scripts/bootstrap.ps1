# Bootstrap script for Windows (PowerShell)

Write-Host "=== Bootstrapping Agentic Trading Platform ===" -ForegroundColor Green

# Create venv if it doesn't exist
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

# Activate venv
& ".venv\Scripts\Activate.ps1"

# Upgrade pip
python -m pip install --upgrade pip

# Install backend deps
Write-Host "Installing backend dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt

# Initialize DB
Write-Host "Initializing database..." -ForegroundColor Yellow
python -c "from backend.db.connect import init_db; init_db(); print('Database initialized')"

# Install frontend deps if package.json exists
if (Test-Path "frontend\package.json") {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
    Set-Location frontend
    if (Test-Path "package-lock.json") {
        npm ci
    } else {
        npm install
    }
    Set-Location ..
}

# Run tests
Write-Host "Running tests..." -ForegroundColor Yellow
python -m pytest tests/ -v --tb=short

Write-Host "=== Bootstrap complete ===" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  - Run dev: .\scripts\dev.ps1"
Write-Host "  - Run tests: pytest tests/ -v"
