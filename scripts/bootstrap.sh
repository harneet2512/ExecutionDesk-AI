#!/bin/bash
set -e

echo "=== Bootstrapping Agentic Trading Platform ==="

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install backend deps
echo "Installing backend dependencies..."
pip install -r requirements.txt

# Initialize DB
echo "Initializing database..."
python -c "from backend.db.connect import init_db; init_db(); print('Database initialized')"

# Install frontend deps if package.json exists
if [ -f "frontend/package.json" ]; then
    echo "Installing frontend dependencies..."
    cd frontend
    if [ -f "package-lock.json" ]; then
        npm ci
    else
        npm install
    fi
    cd ..
fi

# Run tests
echo "Running tests..."
pytest tests/ -v --tb=short

echo "=== Bootstrap complete ==="
echo "Next steps:"
echo "  - Run dev: ./scripts/dev.sh"
echo "  - Run tests: pytest tests/ -v"
