from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_url: str = "http://127.0.0.1:11434"
    qdrant_url: str = "http://127.0.0.1:6333"
    ollama_llm_model: str = "qwen3:8b"
    ollama_embed_model: str = "qwen3-embedding:0.6b"
    collection: str = "medical_documents"
    embedding_dimension: int = 1024
    sqlite_dir: Path = Path("data/sqlite")
    documents_dir: Path = Path("data/documents")
    logs_dir: Path = Path("logs")
    seed_dir: Path = Path("samples/seed")
    mcp_url: str = "http://127.0.0.1:8080/mcp/"
    max_upload_mb: int = 20


settings = Settings()
