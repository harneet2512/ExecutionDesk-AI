#!/bin/bash
set -e

# Activate venv if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Start backend and frontend concurrently
echo "Starting backend and frontend..."

# Kill existing processes on ports 8000 and 3000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:3000 | xargs kill -9 2>/dev/null || true

# Start backend
cd backend
uvicorn api.main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# Start frontend if package.json exists
if [ -f "frontend/package.json" ]; then
    cd frontend
    npm run dev &
    FRONTEND_PID=$!
    cd ..
fi

# Wait for both processes
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
