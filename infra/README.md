# Infrastructure

Start the full app with `bash infra/scripts/setup.sh` from the project root.
See the [quick start](../README.md#quick-start) for requirements. All commands below
also run from the project root. Add `sudo` before `docker` if needed.

## Tested configuration

| Component | Tested version or hardware |
|---|---|
| OS | Ubuntu 22.04.5 LTS, kernel 5.15 |
| CPU / RAM | AMD EPYC, 32 vCPU / 94 GiB |
| GPU / driver | NVIDIA A100-PCIE-40GB / 580.178.04 |
| Docker / Compose | 28.5.0 / v2.40.0 |
| NVIDIA Container Toolkit | 1.17.8 |
| Python in app containers / uv | 3.12.16 / 0.12.21 |
| Ollama / Qdrant images | `ollama/ollama:0.40.14` / `qdrant/qdrant:v1.20.0` |
| Chat model | `qwen3:8b`, Q4_K_M, 5.2 GB download |
| Embedding model | `qwen3-embedding:0.6b`, 639 MB download, 1024 dimensions |

## Configuration

`setup.sh` copies `.env.example` to `.env` only if `.env` is missing. To change
settings before the first start, copy the file yourself and edit it:

```bash
cp -n .env.example .env
```

The default setup runs its own Ollama and Qdrant containers. An existing host
Ollama installation is not used, and its downloaded models are not shared.
If port 11434 is busy, set `OLLAMA_PORT=11435` in `.env`. Change `OLLAMA_URL`
to match for host-side tests; the app still uses the internal container port.
Other host ports are `QDRANT_HTTP_PORT`, `QDRANT_GRPC_PORT`, `BACKEND_PORT`
and `FRONTEND_PORT`. Keep `BIND_ADDRESS=127.0.0.1` for local access.

Defaults for the shared GPU:

| Setting | Default | Purpose |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | 1 | Limit concurrent model requests |
| `OLLAMA_MAX_LOADED_MODELS` | 2 | Keep chat and embedding models loaded |
| `OLLAMA_CONTEXT_LENGTH` | 8192 | Limit context size |
| `OLLAMA_KV_CACHE_TYPE` / `OLLAMA_FLASH_ATTENTION` | `q8_0` / `1` | Reduce memory use |
| `OLLAMA_KEEP_ALIVE` | `15m` | Unload idle models |
| `OLLAMA_GPU_OVERHEAD` | `1073741824` | Leave 1 GiB free when placing models |
| `OLLAMA_GPU_DEVICE` | `0` | Select the GPU |

### Use existing Ollama and Qdrant services

Skip `setup.sh` for this option. Copy `.env.example` to `.env` if needed, then set
`APP_OLLAMA_URL` and `APP_QDRANT_URL` to addresses reachable **from the backend
container**. `localhost` inside a container is not the host. Use Qdrant 1.20 or later
for native BM25, with both models from the table above available in Ollama.

```bash
docker compose --env-file .env -f infra/compose.yaml up -d --build --no-deps --wait backend frontend
```

This starts only the app services. Keep the existing services running yourself.

## Services and data

| Container | Default host address |
|---|---|
| `meddoc-frontend` | `127.0.0.1:8501` |
| `meddoc-backend` | `127.0.0.1:8080` |
| `meddoc-ollama` | `127.0.0.1:11434` |
| `meddoc-qdrant` | `127.0.0.1:6333` (HTTP), `127.0.0.1:6334` (gRPC) |

The backend mounts `data/` for original files and SQLite metadata, `logs/` for
JSONL logs, and `samples/` as read-only. Docker volumes store models
(`meddoc_ollama_models`), the CUDA cache (`meddoc_ollama_cuda_cache`) and the search
index (`meddoc_qdrant_storage`). All persist across container restarts.

```bash
docker compose --env-file .env -f infra/compose.yaml ps
docker compose --env-file .env -f infra/compose.yaml logs -f backend frontend
docker compose --env-file .env -f infra/compose.yaml stop
docker compose --env-file .env -f infra/compose.yaml start
```

Add `backend frontend` to `stop` or `start` to affect only the app. After code
changes, run `bash infra/scripts/setup.sh` again to rebuild. `down` removes the
containers but keeps data; `down -v` also deletes the model and index volumes.

## Remote access

Run this on your own computer, replacing `user@server` with your SSH address:

```bash
ssh -N -L 8501:127.0.0.1:8501 -L 8080:127.0.0.1:8080 user@server
```

Then open `http://localhost:8501`. Adjust ports if you changed them in `.env`.

## Development

Only development and infrastructure tests need uv on the host. Python 3.12 and
dependencies are selected by `pyproject.toml` and `uv.lock`.

```bash
uv sync --group frontend
uv run ruff check backend frontend scripts infra/scripts
uv run python infra/scripts/smoke_test.py
```

The infrastructure test checks generation, embeddings, dense/BM25 search and
SQLite, then removes its temporary test data. For local app development, stop
the app containers first, keep Ollama/Qdrant running, then use separate terminals:

```bash
SQLITE_DIR=data/dev/sqlite DOCUMENTS_DIR=data/dev/documents LOGS_DIR=data/dev/logs \
  uv run uvicorn backend.main:app --host 127.0.0.1 --port 8080
uv run --group frontend streamlit run frontend/app.py --server.address 127.0.0.1
```

Use [the sample guide](../samples/README.md) to generate sample PDFs.
