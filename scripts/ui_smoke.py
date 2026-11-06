"""Exercise the Streamlit UI against the real backend; optionally upload an existing PDF."""

import argparse
import os
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

parser = argparse.ArgumentParser()
parser.add_argument(
    "--pdf", type=Path, help="An already indexed PDF to verify duplicate upload feedback"
)
args = parser.parse_args()
backend = os.environ.get("BACKEND_URL", "http://127.0.0.1:8080")
documents = httpx.get(f"{backend}/documents").json()
filename = documents[0]["filename"]
app = AppTest.from_file(
    str(Path(__file__).resolve().parents[1] / "frontend/app.py"), default_timeout=600
).run()
assert not app.exception, app.exception
assert not app.dataframe and not app.text

app.text_input[0].set_value(filename)
next(button for button in app.button if button.label == "Check").click().run()
assert any("Ready" in item.value and filename in item.value for item in app.success)
app.text_input[0].set_value("missing-ui-check-document.pdf")
next(button for button in app.button if button.label == "Check").click().run()
assert any("Document not found" in item.value for item in app.info)
print("PASS  Filename lookup finds an existing document and reports a missing filename")

if args.pdf:
    app.file_uploader[0].set_value((args.pdf.name, args.pdf.read_bytes(), "application/pdf"))
    next(button for button in app.button if button.label == "Upload").click().run()
    assert not app.exception, app.exception
    assert any("Already Exists" in item.value and "Ready" in item.value for item in app.success)
    app.file_uploader[0].set_value(("invalid.pdf", b"not a PDF", "application/pdf"))
    next(button for button in app.button if button.label == "Upload").click().run()
    assert any("Failed" in item.value for item in app.error)
    print("PASS  Real UI upload reports Already Exists / Ready and rejects an invalid PDF")

app.chat_input[0].set_value("What can this assistant do?").run()
assert not app.exception, app.exception
assert len(app.chat_message) == 2
assert any("document" in item.value.lower() for item in app.markdown)
print("PASS  Streamlit chat completes through the real backend")
