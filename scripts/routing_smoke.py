"""Check the direct-answer/document boundary against the running application."""

import httpx

cases = [
    ("What is Helvetica?", "general", ("font", "typeface")),
    ("What is Helvetica and what are you doing?", "general", ("font", "typeface")),
    ("How do I upload a PDF and check whether it is ready?", "assistant", ("upload",)),
    ("What do my uploaded PDFs say about Helvetica?", "documents", ()),
]
with httpx.Client(base_url="http://127.0.0.1:8080", timeout=600) as client:
    for question, intent, keywords in cases:
        response = client.post("/chat", json={"question": question})
        response.raise_for_status()
        result = response.json()
        assert result["plan"]["intent"] == intent, result
        answer = result["answer"].lower()
        assert not keywords or any(word in answer for word in keywords), result
        if "what are you doing" in question:
            assert "document" in answer, result
        if intent != "documents":
            assert not result["sources"] and not result["branches"], result
            assert result["plan"]["subquestions"] == [], result
        else:
            assert result["branches"], result
            assert all(not branch["sufficient"] for branch in result["branches"]), result
        print(f"PASS  {intent}: {question}\n{result['answer']}\n", flush=True)
