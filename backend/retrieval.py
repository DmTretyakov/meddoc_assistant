from time import perf_counter
from uuid import UUID

import httpx

from backend import db
from backend.config import settings
from backend.llm import embed
from backend.logging import event


async def qdrant(method: str, path: str = "", body: dict | None = None):
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(
            method, f"{settings.qdrant_url}/collections/{settings.collection}{path}", json=body
        )
        response.raise_for_status()
    return response.json()["result"]


async def initialize() -> None:
    exists = await qdrant("GET", "/exists")
    if not exists["exists"]:
        await qdrant(
            "PUT",
            body={
                "vectors": {"dense": {"size": settings.embedding_dimension, "distance": "Cosine"}}
            },
        )
    await qdrant(
        "PUT",
        "/index?wait=true",
        {
            "field_name": "text",
            "field_schema": {
                "type": "text",
                "tokenizer": "word",
                "lowercase": True,
                "stemmer": {"type": "snowball", "language": "english"},
                "stopwords": "english",
                "scoring": True,
            },
        },
    )
    await qdrant(
        "PUT",
        "/index?wait=true",
        {
            "field_name": "document_id",
            "field_schema": "keyword",
        },
    )


async def search(query: str, hyde_text: str | None = None, top_k: int = 3) -> list[dict]:
    started = perf_counter()
    ready_ids = [doc["id"] for doc in db.list_documents("READY")]
    if not ready_ids:
        event(
            "retrieval",
            chunk_ids=[],
            query=query,
            hyde_used=bool(hyde_text),
            duration_ms=round((perf_counter() - started) * 1000),
        )
        return []
    ready_filter = {"must": [{"key": "document_id", "match": {"any": ready_ids}}]}
    vector = (await embed([hyde_text or query]))[0]
    result = await qdrant(
        "POST",
        "/points/query",
        {
            "prefetch": [
                {"query": vector, "using": "dense", "limit": 12, "filter": ready_filter},
                {"query": {"text": query}, "using": "text", "limit": 12, "filter": ready_filter},
            ],
            "query": {"fusion": "rrf"},
            "filter": ready_filter,
            "limit": top_k,
            "with_payload": True,
        },
    )
    sources = [point["payload"] for point in result["points"]]
    event(
        "retrieval",
        query=query,
        hyde_used=bool(hyde_text),
        duration_ms=round((perf_counter() - started) * 1000),
        chunk_ids=[source["chunk_id"] for source in sources],
    )
    return sources


async def get_chunk(chunk_id: str) -> dict | None:
    UUID(chunk_id)
    points = await qdrant(
        "POST",
        "/points",
        {
            "ids": [chunk_id],
            "with_payload": True,
            "with_vector": False,
        },
    )
    if points:
        source = points[0]["payload"]
        document = db.get(source["document_id"])
        if document and document["status"] == "READY":
            return source
    return None
