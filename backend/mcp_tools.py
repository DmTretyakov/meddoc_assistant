import json
from time import perf_counter
from typing import Annotated

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from backend import db, retrieval
from backend.config import settings
from backend.logging import branch_id, event, trace_id
from backend.schemas import Document

mcp = FastMCP(
    "Medical documents", stateless_http=True, json_response=True, streamable_http_path="/"
)


@mcp.tool()
async def search_documents(
    query: Annotated[str, Field(min_length=1, max_length=4000)],
    hyde_text: str | None = None,
    top_k: Annotated[int, Field(ge=1, le=3)] = 3,
) -> list[dict]:
    """Search READY documents using dense embeddings, native BM25 and RRF fusion."""
    return await retrieval.search(query, hyde_text, top_k)


@mcp.tool()
async def get_chunk(chunk_id: str) -> dict | None:
    """Return a chunk and its original source metadata, only if its document is READY."""
    return await retrieval.get_chunk(chunk_id)


@mcp.tool()
async def list_documents() -> list[dict]:
    """List documents that have finished processing and are available for questions."""
    return [Document.model_validate(doc).model_dump() for doc in db.list_documents("READY")]


async def call_tool(name: str, arguments: dict | None = None):
    started = perf_counter()
    status = "error"
    headers = {"X-Request-ID": trace_id.get(), "X-Branch-ID": branch_id.get() or ""}
    event("mcp_tool", tool=name, phase="start")
    try:
        async with httpx.AsyncClient(timeout=300, headers=headers) as client:
            async with streamable_http_client(settings.mcp_url, http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments or {})
        if result.isError:
            raise RuntimeError(f"MCP tool {name} failed")
        if result.structuredContent is not None:
            data = result.structuredContent
            data = data.get("result", data)
        else:
            data = json.loads(
                "".join(block.text for block in result.content if block.type == "text")
            )
        status = "success"
        return data
    finally:
        event(
            "mcp_tool",
            tool=name,
            phase="end",
            status=status,
            duration_ms=round((perf_counter() - started) * 1000),
        )
