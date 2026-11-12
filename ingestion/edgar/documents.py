"""Turn a saved filing record into Vertex AI Search documents, one per passage.

Each filing is split here, in our own code, into passages of roughly 350 words that
never cross a section boundary ("Item 1A. Risk Factors", "Exhibit 99.1", ...). Each
passage is imported as its own plain-text document, carrying its section and text as
metadata. That lets Vertex AI Search use its free default (digital) parser instead
of the layout parser, which is billed per page, while still giving the app
passage-level citations labelled with their section.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

TARGET_WORDS = 350  # close a passage once it reaches this many words...
MAX_WORDS = 500     # ...and never let one grow past this

# A line that starts a new section: "Item 1A. Risk Factors", "ITEM 7.", "PART II",
# "Item 2.02 Results of Operations..." (8-K), "Exhibit 99.1".
_HEADING = re.compile(
    r"^(part\s+[ivx]+\b|item\s+\d{1,2}(?:\.\d{1,2})?[a-z]?\b|exhibit\s+\d{1,3}(?:\.\d{1,2})?\b)",
    re.IGNORECASE,
)
# A heading on its own with the title on the next line: "Item 1A." / "Risk Factors".
_BARE_HEADING = re.compile(
    r"^(part\s+[ivx]+|item\s+\d{1,2}(?:\.\d{1,2})?[a-z]?|exhibit\s+\d{1,3}(?:\.\d{1,2})?)\.?$",
    re.IGNORECASE,
)
# Page numbers, separators and similar noise lines.
_NOISE = re.compile(r"^[\d\s|.\-–—•]*$")


@dataclass(frozen=True)
class SearchDocument:
    doc_id: str
    title: str
    content: str  # what Vertex AI Search indexes (header line + passage text)
    struct_data: dict[str, Any]


def filing_id(record: dict[str, Any]) -> str:
    """Stable ID for a filing: '<cik>-<accession without dashes>'."""
    return f"{record['cik']}-{record['id']}"


def filing_title(record: dict[str, Any]) -> str:
    return (
        f"{record['company_name']} ({record['ticker']}) · {record['form_type']} · "
        f"filed {record['filing_date']}"
    )


def _heading(line: str) -> str | None:
    """The section name if this line is a section heading, else None."""
    if len(line) > 100 or "|" in line or not _HEADING.match(line):
        return None
    if _BARE_HEADING.match(line):
        return line
    # "Item 5 is not applicable." is a sentence, not a heading.
    if line.endswith(".") or len(line.split()) > 15:
        return None
    return line


def _is_title_line(line: str) -> bool:
    return (
        0 < len(line) <= 80 and "|" not in line and not line.endswith(".")
        and _heading(line) is None and not _NOISE.match(line)
    )


def split_passages(text: str) -> list[tuple[str, str]]:
    """Split filing text into (section, passage) pairs.

    Lines are paragraphs or table rows (see clean.py). Passages close at about
    TARGET_WORDS, never exceed MAX_WORDS, and start fresh at every section heading.
    """
    lines = [line.strip() for line in text.splitlines()]
    passages: list[tuple[str, str]] = []
    section = ""
    buf: list[str] = []
    words = 0

    def flush() -> None:
        nonlocal buf, words
        body = "\n".join(buf).strip()
        if len(body.split()) >= 8:  # drop fragments such as a lone page header
            passages.append((section, body))
        buf, words = [], 0

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line or _NOISE.match(line):
            continue
        heading = _heading(line)
        if heading:
            if _BARE_HEADING.match(heading) and i < len(lines) and _is_title_line(lines[i]):
                heading = f"{heading.rstrip('.')}. {lines[i]}"
                i += 1
            flush()
            section = " ".join(heading.split())
            continue
        n = len(line.split())
        if n > MAX_WORDS:  # one enormous paragraph: cut it into windows
            flush()
            tokens = line.split()
            for start in range(0, len(tokens), TARGET_WORDS):
                buf, words = [" ".join(tokens[start:start + TARGET_WORDS])], 0
                flush()
            continue
        if buf and words + n > MAX_WORDS:
            flush()
        buf.append(line)
        words += n
        if words >= TARGET_WORDS:
            flush()
    flush()
    return passages


def build_documents(record: dict[str, Any]) -> list[SearchDocument]:
    base_id = filing_id(record)
    title = filing_title(record)
    passages = split_passages(record["text"])
    docs = []
    for n, (section, text) in enumerate(passages, 1):
        header = title + (f" · {section}" if section else "")
        docs.append(
            SearchDocument(
                doc_id=f"{base_id}-{n:04d}",
                title=title,
                content=f"{header}\n\n{text}",
                struct_data={
                    "title": title,
                    "filing_id": base_id,
                    "ticker": record["ticker"],
                    "company_name": record["company_name"],
                    "cik": record["cik"],
                    "form_type": record["form_type"],
                    "filing_date": record["filing_date"],
                    "filing_year": int(record["filing_date"][:4]),
                    "report_date": record.get("report_date") or "",
                    "accession_number": record["accession_number"],
                    "source_url": record["source_url"],
                    "index_url": record["index_url"],
                    "section": section,
                    "passage": n,
                    "total_passages": len(passages),
                    "text": text,
                },
            )
        )
    return docs


def manifest_line(doc: SearchDocument) -> dict[str, Any]:
    """One line of the JSONL file Vertex AI Search imports (data_schema='document').

    The passage is embedded in the line itself, so no per-passage files are needed.
    """
    return {
        "id": doc.doc_id,
        "structData": doc.struct_data,
        "content": {
            "mimeType": "text/plain",
            "rawBytes": base64.b64encode(doc.content.encode("utf-8")).decode("ascii"),
        },
    }


# Field settings for the data store schema. "indexable" fields can be used in
# search filters (e.g. only AAPL 10-Ks from 2026); "retrievable" fields come back
# with each result so the app can show the passage and cite it. Set before the
# first import, so Vertex AI Search never has to guess field types.
SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "title": {"type": "string", "retrievable": True, "keyPropertyMapping": "title"},
        "filing_id": {"type": "string", "retrievable": True, "indexable": True},
        "ticker": {"type": "string", "retrievable": True, "indexable": True,
                   "searchable": True, "dynamicFacetable": True},
        "company_name": {"type": "string", "retrievable": True, "searchable": True},
        "cik": {"type": "integer", "retrievable": True},
        "form_type": {"type": "string", "retrievable": True, "indexable": True,
                      "dynamicFacetable": True},
        "filing_date": {"type": "string", "retrievable": True},
        "filing_year": {"type": "integer", "retrievable": True, "indexable": True},
        "report_date": {"type": "string", "retrievable": True},
        "accession_number": {"type": "string", "retrievable": True},
        "source_url": {"type": "string", "retrievable": True},
        "index_url": {"type": "string", "retrievable": True},
        "section": {"type": "string", "retrievable": True},
        "passage": {"type": "integer", "retrievable": True},
        "total_passages": {"type": "integer", "retrievable": True},
        "text": {"type": "string", "retrievable": True},
    },
}
