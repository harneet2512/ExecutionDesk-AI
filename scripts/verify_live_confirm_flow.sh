#!/bin/bash
# Verify end-to-end LIVE confirmation flow
# This script starts the backend if needed, runs the verification test,
# and exits with non-zero if any step fails.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== LIVE Confirmation Flow Verification ==="
echo ""

# Check if backend is running
check_backend() {
    curl -s http://localhost:8004/health > /dev/null 2>&1
    return $?
}

# Start backend if not running
if ! check_backend; then
    echo "Backend not running. Starting..."
    
    # Activate venv if exists
    if [ -d ".venv" ]; then
        source .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate 2>/dev/null || true
    fi
    
    # Start backend in background
    uvicorn backend.api.main:app --host 0.0.0.0 --port 8004 &
    BACKEND_PID=$!
    
    # Wait for backend to be ready (max 30 seconds)
    echo "Waiting for backend to start..."
    for i in {1..30}; do
        if check_backend; then
            echo "Backend started (PID: $BACKEND_PID)"
            break
        fi
        sleep 1
    done
    
    if ! check_backend; then
        echo "ERROR: Backend failed to start"
        kill $BACKEND_PID 2>/dev/null || true
        exit 1
    fi
    
    STARTED_BACKEND=true
else
    echo "Backend already running"
    STARTED_BACKEND=false
fi

echo ""
echo "Running verification script..."
echo ""

# Run the Python verification script
python scripts/verify_live_confirm.py
RESULT=$?

# Cleanup if we started the backend
if [ "$STARTED_BACKEND" = true ]; then
    echo ""
    echo "Stopping backend..."
    kill $BACKEND_PID 2>/dev/null || true
fi

# Exit with the verification script's result
if [ $RESULT -eq 0 ]; then
    echo ""
    echo "=== VERIFICATION PASSED ==="
    exit 0
else
    echo ""
    echo "=== VERIFICATION FAILED ==="
    exit 1
fi
