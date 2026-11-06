# Sample PDFs

All products, participants and study results are fictional test data.

| Folder | Files | How to use |
|---|---:|---|
| `seed/` | 16 PDFs | Loaded automatically at backend startup |
| `manual_upload/` | 8 PDFs | Select a file in Streamlit and click **Upload** |

[questions.json](questions.json) has example questions and expected facts.
[documents.json](documents.json) defines the PDF contents and destination folders.
The PDFs are already included; you do not need to generate them to run the app.

To generate missing PDFs from the project root (requires uv):

```bash
uv run --no-project --python 3.12 --with reportlab==5.1.0 python infra/scripts/generate_samples.py
```

Existing PDFs are kept unless you add `--overwrite`. A changed file gets a new
content hash and is treated as a new document.

Uploading keeps the sample file and stores a copy in `data/documents/`. Removing
a sample does not remove it from the index.
