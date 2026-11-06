"""Check Ollama, embeddings, Qdrant hybrid search and SQLite; clean up temporary test data."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path) -> None:
    """Minimal .env loader; existing environment variables take precedence."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env(ROOT / ".env")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
LLM_MODEL = os.environ.get("OLLAMA_LLM_MODEL", "qwen3:8b")
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b")
SQLITE_DIR = ROOT / os.environ.get("SQLITE_DIR", "data/sqlite")
EXPECTED_EMBED_DIM = 1024
TEST_PREFIX = "smoke_test_"

# (document id, section heading used as the excerpt start) from samples/seed/
EXCERPTS = [
    ("MDA-CT-001", "Results"),
    ("MDA-DS-002", "Key findings"),
    ("MDA-AE-005", "Most common adverse events"),
    ("MDA-CT-008", "Results"),
    ("MDA-AE-009", "Liver enzyme findings"),
]


def http(method: str, url: str, body: dict | None = None, timeout: float = 300) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {exc.read().decode()[:500]}") from exc


def embed(texts: list[str]) -> list[list[float]]:
    return http("POST", f"{OLLAMA_URL}/api/embed", {"model": EMBED_MODEL, "input": texts})["embeddings"]


def load_excerpts() -> list[dict]:
    """Extract one short section per PDF."""
    passages = []
    for doc_id, heading in EXCERPTS:
        pdf = next((ROOT / "samples" / "seed").glob(f"{doc_id}_*.pdf"))
        with pymupdf.open(pdf) as doc:
            text = " ".join(page.get_text() for page in doc)
        text = " ".join(text.split())
        start = text.index(heading + " ") + len(heading) + 1
        passages.append({"doc_id": doc_id, "file": pdf.name, "text": text[start:start + 600]})
    return passages


def test_llm() -> str:
    t0 = time.time()
    resp = http("POST", f"{OLLAMA_URL}/api/chat", {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "In one short sentence, what does an ACE inhibitor treat?"}],
        "think": False,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 64},
    })
    answer = resp["message"]["content"].strip()
    assert answer, "empty LLM response"
    return f"{LLM_MODEL} answered in {time.time() - t0:.1f}s: {answer[:100]!r}"


def test_embeddings() -> str:
    vectors = embed(["Hyperkalemia is an elevated serum potassium level.", "Median progression-free survival."])
    assert len(vectors) == 2, "expected 2 embeddings"
    for vec in vectors:
        assert len(vec) == EXPECTED_EMBED_DIM, f"dim {len(vec)} != {EXPECTED_EMBED_DIM}"
        assert all(math.isfinite(x) for x in vec), "non-finite values"
        norm = math.sqrt(sum(x * x for x in vec))
        assert norm > 0.1, "near-zero vector"
    cos = sum(a * b for a, b in zip(*vectors)) / (
        math.sqrt(sum(a * a for a in vectors[0])) * math.sqrt(sum(b * b for b in vectors[1])))
    return f"{EMBED_MODEL}: dim={len(vectors[0])}, norm={norm:.3f}, cos(two texts)={cos:.3f}"


def test_qdrant() -> str:
    passages = load_excerpts()
    vectors = embed([p["text"] for p in passages])
    collection = f"{TEST_PREFIX}{uuid.uuid4().hex[:8]}"
    base = f"{QDRANT_URL}/collections/{collection}"
    try:
        http("PUT", base, {"vectors": {"dense": {"size": len(vectors[0]), "distance": "Cosine"}}})
        http("PUT", f"{base}/index?wait=true", {
            "field_name": "text",
            "field_schema": {
                "type": "text", "tokenizer": "word", "lowercase": True,
                "stemmer": {"type": "snowball", "language": "english"},
                "stopwords": "english", "scoring": True,
            },
        })
        http("PUT", f"{base}/points?wait=true", {"points": [
            {"id": i, "vector": {"dense": vec}, "payload": p}
            for i, (p, vec) in enumerate(zip(passages, vectors))
        ]})

        query = "Which drug caused grade 3 ALT elevation and liver injury?"
        qvec = embed([query])[0]
        dense = http("POST", f"{base}/points/query",
                     {"query": qvec, "using": "dense", "limit": 3, "with_payload": True})["result"]["points"]
        bm25 = http("POST", f"{base}/points/query",
                    {"query": {"text": query}, "using": "text", "limit": 3, "with_payload": True})["result"]["points"]
        hybrid = http("POST", f"{base}/points/query", {
            "prefetch": [
                {"query": qvec, "using": "dense", "limit": 5},
                {"query": {"text": query}, "using": "text", "limit": 5},
            ],
            "query": {"fusion": "rrf"},
            "limit": 3,
            "with_payload": True,
        })["result"]["points"]

        for name, res in (("dense", dense), ("bm25", bm25), ("hybrid", hybrid)):
            assert res, f"{name} search returned no results"
        top = lambda res: f"{res[0]['payload']['doc_id']}({res[0]['score']:.3f})"  # noqa: E731
        assert hybrid[0]["payload"]["doc_id"] in {"MDA-AE-009", "MDA-CT-008", "MDA-AE-005"}, "unexpected hybrid top hit"
        return (f"{len(passages)} PDF excerpts indexed; top hits: dense={top(dense)}, "
                f"bm25={top(bm25)}, rrf={top(hybrid)}")
    finally:
        try:
            http("DELETE", base)
        except Exception as exc:  # noqa: BLE001
            print(f"  WARNING: could not delete collection {collection}: {exc}")


def test_sqlite() -> str:
    SQLITE_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=TEST_PREFIX, suffix=".db", dir=SQLITE_DIR)
    os.close(fd)
    path = Path(name)
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            conn.execute("INSERT INTO documents VALUES (?, ?)", ("MDA-CT-001", "processed"))
            row = conn.execute("SELECT status FROM documents WHERE id = ?", ("MDA-CT-001",)).fetchone()
        conn.close()
        assert row == ("processed",), f"unexpected row {row}"
        return f"SQLite {sqlite3.sqlite_version}: write/read OK in {SQLITE_DIR.relative_to(ROOT)}/"
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)


def check_cleanup() -> str:
    leftovers = [c["name"] for c in http("GET", f"{QDRANT_URL}/collections")["result"]["collections"]
                 if c["name"].startswith(TEST_PREFIX)]
    leftovers += [p.name for p in SQLITE_DIR.glob(f"{TEST_PREFIX}*")]
    assert not leftovers, f"leftover test data: {leftovers}"
    return "no temporary Qdrant collections or SQLite files left"


def main() -> int:
    tests = [("Ollama LLM", test_llm), ("Ollama embeddings", test_embeddings),
             ("Qdrant dense+BM25+RRF", test_qdrant), ("SQLite", test_sqlite), ("Cleanup", check_cleanup)]
    failed = 0
    for name, fn in tests:
        try:
            print(f"PASS  {name}: {fn()}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
