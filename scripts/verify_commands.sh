#!/bin/bash
# verify_commands.sh - Wrapper for end-to-end verification
#
# Usage:
#   ./scripts/verify_commands.sh
#   BACKEND_URL=http://localhost:9000 ./scripts/verify_commands.sh
#
# Runs Command A (Analyze portfolio) and Command B (Buy most profitable) through
# the trading platform and verifies the response.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Check if backend is running
echo "=== Checking backend health ==="
if ! curl -s http://localhost:8000/api/v1/ops/health > /dev/null 2>&1; then
    echo "ERROR: Backend not running on localhost:8000"
    echo "Start it with: uvicorn backend.api.main:app --port 8000"
    exit 1
fi

# Run verification
echo "=== Running verification script ==="
python scripts/verify_commands.py "$@"

# Check exit code
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "=== VERIFICATION PASSED ==="
else
    echo ""
    echo "=== VERIFICATION FAILED ==="
fi

exit $EXIT_CODE
