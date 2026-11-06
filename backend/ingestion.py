import asyncio
import hashlib
import threading
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pymupdf
import tiktoken

from backend import db
from backend.config import settings
from backend.llm import embed
from backend.logging import event
from backend.retrieval import qdrant

registration_lock = threading.Lock()
processing_lock = asyncio.Lock()
CHUNK_TOKENS = 400
OVERLAP_TOKENS = 50


def register(content: bytes, filename: str) -> tuple[dict, bool]:
    filename = Path(filename.replace("\\", "/")).name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".txt"}:
        raise ValueError("Only PDF and UTF-8 text files are supported.")
    if not content or len(content) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError(f"Upload a non-empty file up to {settings.max_upload_mb} MB.")
    if suffix == ".pdf" and b"%PDF-" not in content[:1024]:
        raise ValueError("This file does not have a PDF header.")
    document_id = hashlib.sha256(content).hexdigest()
    with registration_lock:
        existing = db.get(document_id)
        if existing:
            retry = existing["status"] == "FAILED"
            if retry:
                db.set_status(document_id, "PENDING")
            return db.get(document_id), retry
        path = settings.documents_dir / f"{document_id}{suffix}"
        path.write_bytes(content)
        with db.connect() as connection:
            connection.execute(
                """INSERT INTO documents (id, content_hash, filename, path, status)
                   VALUES (?, ?, ?, ?, 'PENDING')""",
                (document_id, document_id, filename, str(path)),
            )
    event("ingestion", document_id=document_id, status="PENDING")
    return db.get(document_id), True


def extract_chunks(document: dict) -> tuple[int, list[dict]]:
    path = Path(document["path"])
    if path.suffix == ".pdf":
        with pymupdf.open(path) as pdf:
            if pdf.needs_pass:
                raise ValueError("Password-protected PDFs are not supported.")
            pages = [page.get_text(sort=True) for page in pdf]
    else:
        pages = [path.read_text(encoding="utf-8")]
    tokenizer = tiktoken.get_encoding("cl100k_base")
    chunks = []
    for page, text in enumerate(pages, start=1):
        tokens = tokenizer.encode(text, disallowed_special=())
        for index, start in enumerate(
            range(0, len(tokens), CHUNK_TOKENS - OVERLAP_TOKENS), start=1
        ):
            chunk_text = tokenizer.decode(tokens[start : start + CHUNK_TOKENS]).strip()
            if not chunk_text:
                continue
            source_id = f"S{document['id'][:12]}P{page}C{index}"
            chunks.append(
                {
                    "source_id": source_id,
                    "chunk_id": str(uuid5(NAMESPACE_URL, f"{document['id']}:{page}:{index}")),
                    "document_id": document["id"],
                    "filename": document["filename"],
                    "page": page,
                    "text": chunk_text,
                }
            )
            if start + CHUNK_TOKENS >= len(tokens):
                break
    if not chunks:
        raise ValueError(
            "No extractable text found. Scanned PDFs require OCR, which is not included."
        )
    return len(pages), chunks


async def process(document_id: str) -> None:
    async with processing_lock:
        document = db.get(document_id)
        if document["status"] != "PENDING":
            return
        try:
            pages, chunks = await asyncio.to_thread(extract_chunks, document)
            await qdrant(
                "POST",
                "/points/delete?wait=true",
                {"filter": {"must": [{"key": "document_id", "match": {"value": document_id}}]}},
            )
            for offset in range(0, len(chunks), 16):
                batch = chunks[offset : offset + 16]
                vectors = await embed([chunk["text"] for chunk in batch])
                await qdrant(
                    "PUT",
                    "/points?wait=true",
                    {
                        "points": [
                            {"id": chunk["chunk_id"], "vector": {"dense": vector}, "payload": chunk}
                            for chunk, vector in zip(batch, vectors, strict=True)
                        ]
                    },
                )
            db.set_status(document_id, "READY", pages=pages, chunks=len(chunks))
            event("ingestion", document_id=document_id, status="READY", chunks=len(chunks))
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, ValueError)
                else (
                    f"Processing failed ({type(exc).__name__}). Check service health and upload again."
                )
            )
            db.set_status(document_id, "FAILED", error=message)
            event("ingestion", document_id=document_id, status="FAILED", error=type(exc).__name__)


async def seed_and_recover() -> None:
    for path in sorted(settings.seed_dir.glob("*.pdf")):
        await asyncio.to_thread(register, path.read_bytes(), path.name)
    for document in db.list_documents("PENDING"):
        await process(document["id"])
