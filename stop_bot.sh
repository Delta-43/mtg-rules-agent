#!/usr/bin/env bash
set -euo pipefail

# Automatically switch to docker group if member but session does not have it
# active yet. `getent`/`sg` are Linux-specific and deliberately guarded behind
# `command -v` -- macOS (Docker Desktop) and other platforms without them
# simply skip this and rely on `docker info` having already succeeded above.
if ! docker info >/dev/null 2>&1; then
  if command -v getent >/dev/null 2>&1 && command -v sg >/dev/null 2>&1 \
      && getent group docker | grep -qw "${USER:-$(whoami)}"; then
    exec sg docker -c "$0 $*"
  fi
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker-compose)
else
  DOCKER_COMPOSE=()
fi

echo "=== Stopping MTG Judge Chatbot Stack ==="

# 1. Stop local uvicorn if running
if pgrep -f "uvicorn app_api.main:app" >/dev/null 2>&1; then
  echo "Stopping FastAPI / Uvicorn server..."
  pkill -f "uvicorn app_api.main:app" || true
fi

# 2. Stop Docker Compose containers
if [[ ${#DOCKER_COMPOSE[@]} -gt 0 ]]; then
  echo "Stopping Docker containers (rules-mcp, scryfall-mcp, searxng)..."
  "${DOCKER_COMPOSE[@]}" down
fi

# 3. Stop dedicated Ollama instance on port 11435
OLLAMA_PIDS=$(pgrep -f "0.0.0.0:11435" || true)
if [[ -n "${OLLAMA_PIDS}" ]]; then
  echo "Stopping dedicated Ollama instance on port 11435..."
  kill ${OLLAMA_PIDS} 2>/dev/null || true
fi

echo "=== All services stopped and GPU memory freed ==="
