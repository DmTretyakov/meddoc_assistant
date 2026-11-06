import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

from backend.config import settings

trace_id: ContextVar[str] = ContextVar("trace_id", default="startup")
branch_id: ContextVar[str | None] = ContextVar("branch_id", default=None)
logger = logging.getLogger("meddoc")
TRACE_EVENTS = {
    "planner",
    "branch",
    "branch_answer",
    "mcp_tool",
    "retrieval",
    "llm",
    "critic",
    "synthesis",
    "direct",
    "chat_error",
}


def configure_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s", force=True)
    logger.setLevel(logging.INFO)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    for name in ("requests", "agent_traces"):
        file_logger = logging.getLogger(f"meddoc.{name}")
        for handler in file_logger.handlers[:]:
            handler.close()
            file_logger.removeHandler(handler)
        handler = logging.FileHandler(settings.logs_dir / f"{name}.jsonl", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        file_logger.addHandler(handler)
        file_logger.setLevel(logging.INFO)
        file_logger.propagate = False


def record(**fields) -> str:
    return json.dumps(
        {
            "trace_id": trace_id.get(),
            "timestamp": datetime.now(UTC).isoformat(),
            **fields,
        },
        ensure_ascii=False,
    )


def event(event_name: str, **fields) -> None:
    message = record(event=event_name, branch_id=branch_id.get(), **fields)
    logger.info(message)
    if event_name in TRACE_EVENTS:
        logging.getLogger("meddoc.agent_traces").info(message)


def chat_request(question: str | None, answer: str | None, duration_ms: int, status: str) -> None:
    logging.getLogger("meddoc.requests").info(
        record(
            question=question,
            answer=answer,
            duration_ms=duration_ms,
            status=status,
        )
    )
