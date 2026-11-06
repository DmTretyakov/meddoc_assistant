import asyncio
import re
from contextlib import asynccontextmanager, suppress
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError

from backend import db, ingestion, retrieval
from backend.config import settings
from backend.graph import graph
from backend.logging import branch_id, chat_request, configure_logging, event, trace_id
from backend.mcp_tools import mcp
from backend.schemas import ChatRequest, ChatResponse, Document, UploadResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    db.initialize()
    await retrieval.initialize()
    async with mcp.session_manager.run():
        seed_task = asyncio.create_task(ingestion.seed_and_recover())
        app.state.seed_task = seed_task
        yield
        seed_task.cancel()
        with suppress(asyncio.CancelledError):
            await seed_task


app = FastAPI(title="Medical Document Assistant", lifespan=lifespan)
app.mount("/mcp", mcp.streamable_http_app())


@app.middleware("http")
async def request_trace(request: Request, call_next):
    supplied = request.headers.get("X-Request-ID", "")
    token = trace_id.set(
        supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied) else uuid4().hex
    )
    supplied_branch = request.headers.get("X-Branch-ID", "")
    branch_token = branch_id.set(
        supplied_branch if re.fullmatch(r"b[1-3]", supplied_branch) else None
    )
    started = perf_counter()
    request.state.started = started
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = trace_id.get()
        if request.url.path != "/health":
            event(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((perf_counter() - started) * 1000),
            )
        return response
    finally:
        branch_id.reset(branch_token)
        trace_id.reset(token)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path == "/chat":
        question = exc.body.get("question") if isinstance(exc.body, dict) else None
        chat_request(
            question if isinstance(question, str) else None,
            None,
            round((perf_counter() - request.state.started) * 1000),
            "error",
        )
    return await request_validation_exception_handler(request, exc)


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            ollama, qdrant = await asyncio.gather(
                client.get(f"{settings.ollama_url}/api/tags"),
                client.get(f"{settings.qdrant_url}/healthz"),
            )
            ollama.raise_for_status()
            qdrant.raise_for_status()
        available = {model["name"] for model in ollama.json()["models"]}
        if not {settings.ollama_llm_model, settings.ollama_embed_model} <= available:
            raise RuntimeError("Required models are not available")
        documents = db.list_documents()
        task = app.state.seed_task
        if task.done() and not task.cancelled() and task.exception():
            raise RuntimeError("Seed initialization failed")
    except Exception as exc:
        event("health_error", error=type(exc).__name__)
        raise HTTPException(503, "A dependency or seed initialization is unavailable.") from exc
    return {
        "status": "ok",
        "ollama": "ok",
        "qdrant": "ok",
        "sqlite": "ok",
        "documents": {
            status: sum(doc["status"] == status for doc in documents)
            for status in ("PENDING", "READY", "FAILED")
        },
    }


@app.post("/documents", response_model=UploadResponse, status_code=202)
async def upload_document(file: UploadFile, background_tasks: BackgroundTasks):
    content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    await file.close()
    try:
        document, should_process = await asyncio.to_thread(
            ingestion.register, content, file.filename or "upload.pdf"
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if should_process:
        background_tasks.add_task(ingestion.process, document["id"])
    return {**document, "already_exists": not should_process}


@app.get("/documents", response_model=list[Document])
def documents(filename: str | None = None):
    documents = db.list_documents()
    if filename is not None:
        documents = [
            doc for doc in documents if doc["filename"].casefold() == filename.strip().casefold()
        ]
    return documents


@app.get("/documents/{document_id}", response_model=Document)
def document_details(document_id: str):
    document = db.get(document_id)
    if not document:
        raise HTTPException(404, "Document not found.")
    return document


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    started = perf_counter()
    answer = None
    status = "error"
    try:
        result = await graph.ainvoke({"question": body.question.strip(), "branch_results": []})
        response = ChatResponse(
            answer=result["final_answer"],
            sources=result.get("sources", []),
            trace_id=trace_id.get(),
            plan=result["plan"],
            branches=result.get("branch_results", []),
            synthesized=result.get("synthesized", False),
        )
        answer = response.answer
        status = "success"
        return response
    except Exception as exc:
        event("chat_error", error=type(exc).__name__)
        raise HTTPException(
            502,
            f"Could not complete the answer. Retry or check the service logs. Trace: {trace_id.get()}",
        ) from exc
    finally:
        chat_request(body.question, answer, round((perf_counter() - started) * 1000), status)
