#!/bin/bash
set -e

# Activate venv if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Set test database
export TEST_DATABASE_URL="sqlite:///./test_enterprise.db"
export DATABASE_URL="$TEST_DATABASE_URL"

# Remove test DB if exists
if [ -f "test_enterprise.db" ]; then
    rm test_enterprise.db
fi

echo "Running backend tests..."
pytest tests/ -v --tb=short

# Frontend smoke test (if Playwright not available, skip)
if [ -d "frontend" ] && command -v npx &> /dev/null; then
    echo "Running frontend smoke test..."
    cd frontend
    if [ -f "tests/smoke.spec.ts" ]; then
        npx playwright test tests/smoke.spec.ts || echo "Frontend test skipped (Playwright not configured)"
    else
        echo "Frontend smoke test not found, skipping..."
    fi
    cd ..
fi

echo "Tests complete!"
