# Medical Document Assistant

A local assistant for questions about medical PDFs and text files. Answers include
document names, pages and source excerpts. Models and document contents stay on
your host. The sample documents are fictional test data, not medical advice.

## Quick start

You need Linux, Docker Engine with Compose v2 (`docker compose`), an NVIDIA GPU,
its driver and NVIDIA Container Toolkit. The first run needs internet access to
download images, Python packages and models. Ollama and Qdrant run in Docker;
you do not need to install Python, uv or Ollama on the host.

**Tested on Ubuntu 22.04 with an NVIDIA A100 40 GB.** See the
[tested configuration and GPU settings](infra/README.md#tested-configuration).
This is the tested setup, not a minimum hardware requirement.

From the project folder:

```bash
bash infra/scripts/setup.sh
```

The script creates `.env` if missing, starts Ollama and Qdrant, downloads missing
models, then builds and starts the app. It uses `sudo` for Docker if needed.
You can run it again after code changes; it keeps your settings, models and data.

Open [Streamlit](http://localhost:8501). The 16 starter PDFs are indexed in the
background; wait for **Ready** before asking about them. The first run can take
several minutes. [API docs](http://localhost:8080/docs) and
[health status](http://localhost:8080/health) are also available.

To change ports or use existing Ollama/Qdrant services, see
[configuration](infra/README.md#configuration). For a remote server, use the
[SSH access command](infra/README.md#remote-access). Ports stay on localhost.

## Use the app

- **Upload:** select a PDF or UTF-8 text file and click **Upload**. Feedback shows
  **Processing**, **Ready**, **Already Exists** or **Failed**.
- **Check:** enter the full filename and click **Check** to see whether it exists
  and its status. Matching ignores letter case. This does not upload a file.
- **Chat:** ask a question, then open **Sources** to read the cited excerpts.
  Each question is independent; include the drug or trial name in follow-ups.

Try: "What was the change in systolic blood pressure with Cardivex compared with
placebo in the CARDIO-ALPHA trial?"

`samples/seed/` contains 16 PDFs loaded at startup. `samples/manual_upload/`
contains 8 PDFs to upload yourself. See the [sample guide](samples/README.md) and
[example questions](samples/questions.json).

Files are identified by their contents, so uploading the same file twice does
not add a copy. Interrupted jobs resume after restart. Upload a failed file again
to retry it. Files and metadata are stored in `data/`; the search index is stored
in a Docker volume. See [storage and service commands](infra/README.md#services-and-data).

## How the agent works

```text
Streamlit → FastAPI → Planner
                       ├─ assistant / general → direct answer
                       ├─ list documents → MCP
                       ├─ unsafe → refusal
                       └─ document question → 1–3 branches → synthesis
                                               └─ MCP search → answer → critic
```

The five files in `prompts/` give the same `qwen3:8b` model different jobs:

| Prompt | Job |
|---|---|
| `planner.md` | Choose a route, rewrite the search question and split it if needed |
| `general.md` | Answer general knowledge and assistant-help questions without document search |
| `answer.md` | Answer one subquestion using retrieved evidence and citations |
| `critic.md` | Check the answer against the evidence and request a retry if needed |
| `synthesis.md` | Combine answers to multiple subquestions into one final answer |

Medical and document questions use search. Each LangGraph branch retrieves up to
three chunks, answers, then runs the critic. A branch can retry once. The
`operator.add` reducer collects branch results. Synthesis combines them; a single
branch skips this extra model call. Invalid citations or incomplete branches
trigger a fallback to the checked branch answers.

`backend/ingestion.py` extracts text with PyMuPDF and splits it into 400-token
chunks with 50-token overlap. `tiktoken` counts tokens locally; its tokenizer is
an approximation for Qwen. It does not call an OpenAI API.

`backend/retrieval.py` combines embedding search with Qdrant BM25 keyword search
using RRF ranking. Only Ready documents are searched. The planner may produce
`hyde_text`, an optional search hint used for the first embedding search of a
single branch. `null` means no hint was generated. It is never used as evidence.

MCP exposes three read-only tools: `search_documents`, `get_chunk` and
`list_documents`. The workflow accesses MCP over HTTP. The MCP server runs inside
FastAPI at `/mcp/`. See `backend/graph.py` for the workflow and `frontend/app.py`
for the UI.

## Request and agent logs

- `logs/requests.jsonl`: question, final answer, timestamp, total latency and status.
- `logs/agent_traces.jsonl`: actual planner decisions, branches, search queries,
  HyDE usage, chunk IDs, MCP calls, critic results, retries, synthesis and durations.

Both files use `trace_id` to link records. They survive container restarts and are
excluded from Git. Traces do not store passages, full prompts or model reasoning.
Requests rejected before planning have no agent trace.
To view the last completed request and its full trace as formatted JSON (requires `jq`):

```bash
TRACE_ID=$(tail -n 1 logs/requests.jsonl | jq -r '.trace_id')
jq --arg id "$TRACE_ID" 'select(.trace_id == $id)' logs/requests.jsonl
jq --arg id "$TRACE_ID" 'select(.trace_id == $id)' logs/agent_traces.jsonl
```

## Checks

Run these after the starter documents are Ready. Add `sudo` before `docker` if needed.

```bash
docker exec meddoc-backend uv run --no-sync python scripts/smoke_test.py
docker exec meddoc-frontend uv run --no-sync python scripts/ui_smoke.py
```

These check uploads, duplicate handling, MCP search, simple and multi-part answers,
citations, filename lookup and chat. The app test uploads one manual sample.
For trace checks, run `scripts/trace_smoke.py` in the backend the same way;
`scripts/routing_smoke.py` checks general versus document questions.
See [development and infrastructure checks](infra/README.md#development).

## Limits

Uploads are limited to 20 MB. Scanned PDFs need OCR, which is not included.
Password-protected PDFs, table layout recovery, document deletion, authentication
and conversation memory are not supported. Run one backend process.
Search and model answers can be wrong; citation checks validate IDs, not every
claim. This is a local demo, not a clinical or public service.
