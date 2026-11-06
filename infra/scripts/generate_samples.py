"""Generate fictional sample PDFs from samples/documents.json; keep existing files by default."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reportlab import rl_config

rl_config.invariant = 1  # fixed timestamps/IDs -> byte-identical output

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"

DISCLAIMER = (
    "SYNTHETIC DEMONSTRATION DATA. This document is fictional and was generated "
    "for testing a document retrieval system. It contains no real patient "
    "information and does not report genuine research findings. Do not use it "
    "for clinical decisions."
)
SPONSOR = "Northbridge Clinical Research Unit (fictional)"

DOCUMENTS = json.loads((SAMPLES / "documents.json").read_text())


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=15, leading=19, spaceAfter=4),
        "banner": ParagraphStyle(
            "b",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#8a1c1c"),
            backColor=colors.HexColor("#fdecec"),
            borderPadding=4,
            spaceAfter=8,
        ),
        "h": ParagraphStyle(
            "h", parent=base["Heading3"], fontSize=11, leading=14, spaceBefore=6, spaceAfter=2
        ),
        "body": ParagraphStyle("p", parent=base["BodyText"], fontSize=9.5, leading=12.5),
        "small": ParagraphStyle(
            "s", parent=base["Normal"], fontSize=7.5, leading=9.5, textColor=colors.grey
        ),
    }


def render(doc: dict, styles: dict[str, ParagraphStyle]) -> Path:
    out = SAMPLES / doc["folder"] / doc["file"]
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{doc['id']}: {doc['title']}",
        author=SPONSOR,
        subject="Synthetic demonstration data",
        creator="generate_samples.py",
    )
    story = [
        Paragraph(doc["title"], styles["title"]),
        Paragraph(f"<b>{DISCLAIMER}</b>", styles["banner"]),
    ]
    meta = [["Document ID", doc["id"]], ["Sponsor", SPONSOR]] + [list(r) for r in doc["meta"]]
    meta_tbl = Table(meta, colWidths=[42 * mm, 130 * mm])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [meta_tbl, Spacer(1, 4)]
    for heading, text in doc["sections"]:
        story += [Paragraph(heading, styles["h"]), Paragraph(text, styles["body"])]
    if doc.get("table"):
        story += [Spacer(1, 6), Paragraph("Summary table", styles["h"])]
        tbl = Table(doc["table"], hAlign="LEFT")
        tbl.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ]
            )
        )
        story.append(tbl)
    story += [
        Spacer(1, 10),
        Paragraph(
            f"{doc['id']} - Fictional document generated for the Medical Document Assistant demo. "
            "All names, products, studies and results are invented.",
            styles["small"],
        ),
    ]
    pdf.build(story)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--overwrite", action="store_true", help="Regenerate existing PDFs explicitly"
    )
    args = parser.parse_args()
    styles = build_styles()
    for doc in DOCUMENTS:
        path = SAMPLES / doc["folder"] / doc["file"]
        if path.exists() and not args.overwrite:
            print(f"Kept {path.relative_to(ROOT)}")
            continue
        render(doc, styles)
        print(f"Created {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
