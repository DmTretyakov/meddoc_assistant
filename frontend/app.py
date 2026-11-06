import os

import httpx
import streamlit as st

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8080").rstrip("/")

st.set_page_config(page_title="Medical Document Assistant", page_icon="📄", layout="wide")
st.title("Medical Document Assistant")
st.caption(
    "Ask questions about your documents. Bundled medical examples are synthetic, not medical advice."
)


def api(method: str, path: str, **kwargs):
    try:
        response = httpx.request(method, f"{BACKEND}{path}", timeout=600, **kwargs)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        detail = (
            "Could not complete the answer. Please try again."
            if path == "/chat"
            else exc.response.json().get("detail", "The request failed.")
        )
        st.error(str(detail))
    except httpx.RequestError:
        st.error("The backend is unavailable or the request timed out. Please try again.")
    return None


def show_answer(message: dict):
    if message.get("general_knowledge"):
        st.caption("General knowledge; not based on uploaded documents.")
    st.markdown(message["answer"])
    if message.get("sources"):
        with st.expander("Sources"):
            for source in message["sources"]:
                st.text(f"[{source['source_id']}] {source['filename']} · page {source['page']}")
                st.text(source["text"])


def show_status(document: dict):
    label = {"PENDING": "Processing", "READY": "Ready", "FAILED": "Failed"}[document["status"]]
    message = f"{document['filename']}: {label}"
    if document.get("already_exists"):
        message = f"Already Exists — {message}"
    if document["status"] == "FAILED":
        st.error(f"{message}. {document['error'] or 'Please upload again.'}")
    elif document["status"] == "READY":
        st.success(message)
    else:
        st.info(message)


with st.sidebar:
    st.header("Documents")
    with st.form("upload", clear_on_submit=True):
        file = st.file_uploader("Choose a PDF or text file", type=["pdf", "txt"])
        submitted = st.form_submit_button("Upload", use_container_width=True)
    if submitted:
        st.session_state.pop("upload_result", None)
        if file is None:
            st.warning("Choose a file first.")
        else:
            with st.spinner("Processing upload…"):
                result = api(
                    "POST", "/documents", files={"file": (file.name, file.getvalue(), file.type)}
                )
            if result:
                st.session_state.upload_result = result
            else:
                st.error("Failed to upload the document.")

    @st.fragment(run_every="3s")
    def upload_status():
        document = st.session_state.get("upload_result")
        if document:
            if document["status"] == "PENDING":
                latest = api("GET", f"/documents/{document['id']}")
                if latest:
                    document.update(latest)
            show_status(document)

    upload_status()

    with st.form("document_lookup"):
        filename = st.text_input("Filename", placeholder="example.pdf")
        check = st.form_submit_button("Check", use_container_width=True)
    if check:
        if not filename.strip():
            st.warning("Enter a filename.")
        else:
            documents = api("GET", "/documents", params={"filename": filename.strip()})
            if documents is not None:
                if documents:
                    st.caption(
                        "Document exists."
                        if len(documents) == 1
                        else f"{len(documents)} documents have this filename."
                    )
                    for document in documents:
                        show_status(document)
                else:
                    st.info("Document not found.")

st.session_state.setdefault("messages", [])
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            show_answer(message)
        else:
            st.markdown(message["content"])

if question := st.chat_input("Ask a question about the documents"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Preparing an answer…"):
            result = api("POST", "/chat", json={"question": question})
        if result:
            result["general_knowledge"] = result["plan"]["intent"] == "general"
            show_answer(result)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "answer": result["answer"],
                    "sources": result["sources"],
                    "general_knowledge": result["general_knowledge"],
                }
            )
