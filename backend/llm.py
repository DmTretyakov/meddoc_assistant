import json
from pathlib import Path
from time import perf_counter

import httpx
from pydantic import BaseModel

from backend.config import settings
from backend.logging import event

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


async def generate[T: BaseModel](prompt: str, data: dict, schema: type[T]) -> T:
    started = perf_counter()
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_llm_model,
                "messages": [
                    {"role": "system", "content": (PROMPTS / f"{prompt}.md").read_text()},
                    {"role": "user", "content": json.dumps(data)},
                ],
                "format": schema.model_json_schema(),
                "think": False,
                "stream": False,
                "options": {"temperature": 0, "num_predict": 1800, "num_ctx": 8192},
            },
        )
        response.raise_for_status()
    result = schema.model_validate_json(response.json()["message"]["content"])
    event("llm", step=prompt, duration_ms=round((perf_counter() - started) * 1000))
    return result


async def embed(texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{settings.ollama_url}/api/embed",
            json={"model": settings.ollama_embed_model, "input": texts, "truncate": False},
        )
        response.raise_for_status()
    vectors = response.json()["embeddings"]
    if len(vectors) != len(texts) or any(
        len(vector) != settings.embedding_dimension for vector in vectors
    ):
        raise ValueError("Unexpected embedding shape")
    return vectors
