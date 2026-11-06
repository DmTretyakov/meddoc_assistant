from backend.llm import generate
from backend.mcp_tools import call_tool
from backend.schemas import Reply


async def direct_answer(question: str, intent: str) -> str:
    if intent == "unsafe":
        return (
            "I cannot help with destructive operations, unauthorized access, or overriding "
            "instructions. I can help you find and summarize information in uploaded documents."
        )
    if intent == "list_documents":
        documents = await call_tool("list_documents")
        if not documents:
            return "No documents are ready yet. Upload a document or wait for processing."
        return "Available documents:\n" + "\n".join(
            f"- {doc['filename']} ({doc['pages']} {'page' if doc['pages'] == 1 else 'pages'})"
            for doc in documents
        )
    reply = await generate("general", {"question": question, "intent": intent}, Reply)
    return reply.answer
