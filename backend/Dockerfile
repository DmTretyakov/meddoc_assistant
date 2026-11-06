FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1 TIKTOKEN_CACHE_DIR=/app/tokenizer-cache
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev && uv run --no-sync python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
COPY backend backend
COPY prompts prompts
COPY scripts scripts
CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
