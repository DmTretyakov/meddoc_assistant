"""Check that real chat execution is captured in the two JSONL logs."""

import json
import os
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
logs = Path(os.environ.get("LOGS_DIR", "logs"))
questions = json.loads((root / "samples/questions.json").read_text())["questions"]

for question, multipart in [
    (questions[0]["question"], False),
    (questions[0]["question"] + " Also, " + questions[1]["question"], True),
]:
    response = httpx.post("http://127.0.0.1:8080/chat", json={"question": question}, timeout=600)
    response.raise_for_status()
    result = response.json()
    requests = [json.loads(line) for line in (logs / "requests.jsonl").read_text().splitlines()]
    traces = [json.loads(line) for line in (logs / "agent_traces.jsonl").read_text().splitlines()]
    request = next(record for record in requests if record["trace_id"] == result["trace_id"])
    events = [record for record in traces if record["trace_id"] == result["trace_id"]]
    assert request["question"] == question and request["answer"] == result["answer"]
    assert request["status"] == "success" and request["duration_ms"] > 0
    assert all(event["timestamp"] for event in events)
    plan = next(event for event in events if event["event"] == "planner")
    assert plan["intent"] == result["plan"]["intent"]
    assert plan["subquestions"] == result["plan"]["subquestions"]
    assert plan["rewritten_query"] == result["plan"]["search_question"]
    assert len(plan["subquestions"]) >= (2 if multipart else 1)
    for index, branch in enumerate(result["branches"], start=1):
        branch_events = [event for event in events if event["branch_id"] == f"b{index}"]
        assert {"branch", "branch_answer", "mcp_tool", "retrieval", "critic"} <= {
            event["event"] for event in branch_events
        }
        retrievals = [event for event in branch_events if event["event"] == "retrieval"]
        assert all(event["chunk_ids"] and event["duration_ms"] >= 0 for event in retrievals)
        critics = [event for event in branch_events if event["event"] == "critic"]
        assert all("reason" in event and event["retry_count"] <= 1 for event in critics)
        assert critics[-1]["passed"] == branch["critic"]["passed"]
        assert critics[-1]["retry_count"] == branch["retries"]
    synthesis = next(
        event for event in events if event["event"] == "synthesis" and event["phase"] == "end"
    )
    assert synthesis["generated"] == result["synthesized"]
    assert not any({"evidence", "text", "prompt", "reasoning"} & event.keys() for event in events)
    print(
        f"PASS  {'Multi-part' if multipart else 'Simple'} chat linked to real execution: {result['trace_id']}"
    )

response = httpx.post("http://127.0.0.1:8080/chat", json={"question": ""})
assert response.status_code == 422
records = [json.loads(line) for line in (logs / "requests.jsonl").read_text().splitlines()]
request = next(
    record for record in records if record["trace_id"] == response.headers["X-Request-ID"]
)
assert request["status"] == "error" and request["answer"] is None and request["question"] == ""
print("PASS  Rejected chat request is logged with its trace ID and error status")
