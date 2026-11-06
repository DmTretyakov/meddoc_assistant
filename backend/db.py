import sqlite3
from contextlib import contextmanager

from backend.config import settings


@contextmanager
def connect():
    connection = sqlite3.connect(settings.sqlite_dir / "documents.db", timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize() -> None:
    settings.sqlite_dir.mkdir(parents=True, exist_ok=True)
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    with connect() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, content_hash TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL, path TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('PENDING', 'READY', 'FAILED')),
                pages INTEGER NOT NULL DEFAULT 0, chunks INTEGER NOT NULL DEFAULT 0,
                error TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)


def get(document_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return dict(row) if row else None


def list_documents(status: str | None = None) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM documents WHERE (? IS NULL OR status = ?) ORDER BY created_at, id",
            (status, status),
        ).fetchall()
    return [dict(row) for row in rows]


def set_status(document_id: str, status: str, *, pages=0, chunks=0, error=None) -> None:
    with connect() as connection:
        connection.execute(
            """UPDATE documents SET status=?, pages=?, chunks=?, error=?,
               updated_at=datetime('now') WHERE id=?""",
            (status, pages, chunks, error, document_id),
        )
