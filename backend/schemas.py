from typing import Literal

from pydantic import BaseModel, Field


class Document(BaseModel):
    id: str
    content_hash: str
    filename: str
    status: Literal["PENDING", "READY", "FAILED"]
    pages: int
    chunks: int
    error: str | None
    created_at: str
    updated_at: str


class UploadResponse(Document):
    already_exists: bool


class Plan(BaseModel):
    intent: Literal["assistant", "general", "documents", "list_documents", "unsafe"]
    search_question: str
    hyde_text: str | None = None
    subquestions: list[str] = Field(default_factory=list, max_length=3)


class Reply(BaseModel):
    answer: str = Field(min_length=1)


class Answer(BaseModel):
    answer: str = Field(min_length=1)
    sufficient: bool


class Critique(BaseModel):
    passed: bool
    reason: str
    retry_needed: bool


class Source(BaseModel):
    source_id: str
    chunk_id: str
    document_id: str
    filename: str
    page: int
    text: str


class BranchResult(BaseModel):
    question: str
    answer: str
    sources: list[Source]
    sufficient: bool
    critic: Critique
    retries: int


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000, pattern=r"\S")


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    trace_id: str
    plan: Plan
    branches: list[BranchResult] = Field(default_factory=list)
    synthesized: bool = False
