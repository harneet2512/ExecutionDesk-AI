#!/usr/bin/env bash
set -euo pipefail

echo "=== ExecutionDesk-AI: Docker Quick Start ==="

command -v docker >/dev/null 2>&1 || { echo "Docker not found. Install: https://docs.docker.com/get-docker/"; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "Docker Compose not found."; exit 1; }

if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env 2>/dev/null || echo "No .env.example found. Create .env with your API keys."
fi

echo "Building containers..."
docker compose build

echo "Starting services..."
docker compose up -d

echo ""
echo "Waiting for backend health..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/health | grep -q '"ok"'; then
        echo "Backend is healthy!"
        break
    fi
    sleep 1
done

echo ""
echo "=== Ready ==="
echo "Frontend:  http://localhost:3000"
echo "Backend:   http://localhost:8000"
echo "API Docs:  http://localhost:8000/docs"
echo "Database:  postgresql://edai:edai@localhost:5432/executiondesk"
echo ""
echo "Logs: docker compose logs -f"
echo "Stop: docker compose down"
