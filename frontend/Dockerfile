FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group frontend
COPY frontend frontend
COPY scripts/ui_smoke.py scripts/ui_smoke.py
CMD ["uv", "run", "--no-sync", "streamlit", "run", "frontend/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.maxUploadSize=20", "--browser.gatherUsageStats=false"]
