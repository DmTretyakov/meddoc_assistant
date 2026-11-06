#!/usr/bin/env bash
# Start the full app; keep existing settings, models and data.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example"; }
set -a; . ./.env; set +a
mkdir -p "${SQLITE_DIR:-data/sqlite}" data/documents logs

# Use plain docker if the user can reach the daemon, otherwise sudo.
if docker info >/dev/null 2>&1; then DOCKER=(docker); else DOCKER=(sudo docker); fi
COMPOSE=("${DOCKER[@]}" compose --env-file .env -f infra/compose.yaml)

"${COMPOSE[@]}" up -d --wait --wait-timeout 180 ollama qdrant

for model in "${OLLAMA_LLM_MODEL:-qwen3:8b}" "${OLLAMA_EMBED_MODEL:-qwen3-embedding:0.6b}"; do
  if "${DOCKER[@]}" exec meddoc-ollama ollama show "$model" >/dev/null 2>&1; then
    echo "Model ready: $model"
  else
    echo "Downloading $model ..."
    "${DOCKER[@]}" exec meddoc-ollama ollama pull "$model"
  fi
done

"${COMPOSE[@]}" up -d --build --no-deps --wait --wait-timeout 180 backend frontend
echo "App ready: http://localhost:${FRONTEND_PORT:-8501}"
echo "Health: http://localhost:${BACKEND_PORT:-8080}/health"
echo "Starter PDFs are indexed in the background. Use Filename and Check to see their status."
