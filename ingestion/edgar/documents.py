"""Turn a saved filing record into Vertex AI Search documents.

Each filing becomes one or more HTML documents. HTML (rather than plain text) lets
Vertex AI's layout parser recognise headings such as "Item 1A. Risk Factors", so
search chunks carry the section they came from. Very long filings are split into
parts to stay under the per-document size limit.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

# Vertex AI Search accepts larger HTML files, but staying well under the limit
# leaves room for markup and avoids import failures on the biggest bank filings.
MAX_PART_BYTES = 1_500_000

_HEADING = re.compile(r"^(item\s+\d{1,2}[a-z]?\.?|part\s+[ivx]+\b)", re.IGNORECASE)


@dataclass(frozen=True)
class SearchDocument:
    doc_id: str
    title: str
    html: str
    struct_data: dict[str, Any]


def filing_id(record: dict[str, Any]) -> str:
    """Stable ID for a filing: '<cik>-<accession without dashes>'."""
    return f"{record['cik']}-{record['id']}"


def filing_title(record: dict[str, Any]) -> str:
    return (
        f"{record['company_name']} ({record['ticker']}) · {record['form_type']} · "
        f"filed {record['filing_date']}"
    )


def split_parts(text: str, max_bytes: int | None = None) -> list[str]:
    """Split on paragraph boundaries so each part is at most `max_bytes` (UTF-8)."""
    max_bytes = max_bytes or MAX_PART_BYTES
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for para in text.split("\n\n"):
        para_bytes = len(para.encode("utf-8")) + 2
        if para_bytes > max_bytes:  # a single enormous paragraph: hard-split it
            if current:
                parts.append("\n\n".join(current))
                current, size = [], 0
            encoded = para.encode("utf-8")
            for i in range(0, len(encoded), max_bytes):
                parts.append(encoded[i : i + max_bytes].decode("utf-8", errors="ignore"))
            continue
        if size + para_bytes > max_bytes and current:
            parts.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += para_bytes
    if current:
        parts.append("\n\n".join(current))
    return parts


def text_to_html(title: str, text: str) -> str:
    body: list[str] = [f"<h1>{html.escape(title)}</h1>"]
    for para in text.split("\n\n"):
        lines = [line for line in para.split("\n") if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and len(lines[0]) < 120 and _HEADING.match(lines[0]):
            body.append(f"<h2>{html.escape(lines[0])}</h2>")
        else:
            body.append("<p>" + "<br>".join(html.escape(line) for line in lines) + "</p>")
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>"
    )


def build_documents(record: dict[str, Any]) -> list[SearchDocument]:
    base_id = filing_id(record)
    base_title = filing_title(record)
    parts = split_parts(record["text"])
    docs = []
    for n, part in enumerate(parts, 1):
        suffix = f"-p{n}" if len(parts) > 1 else ""
        title = base_title + (f" (part {n} of {len(parts)})" if len(parts) > 1 else "")
        docs.append(
            SearchDocument(
                doc_id=base_id + suffix,
                title=title,
                html=text_to_html(title, part),
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
                    "part": n,
                    "total_parts": len(parts),
                },
            )
        )
    return docs


def manifest_line(doc: SearchDocument, gcs_uri: str) -> dict[str, Any]:
    """One line of the JSONL file Vertex AI Search imports (data_schema='document')."""
    return {
        "id": doc.doc_id,
        "structData": doc.struct_data,
        "content": {"mimeType": "text/html", "uri": gcs_uri},
    }


# Field settings for the data store schema. "indexable" fields can be used in
# search filters (e.g. only AAPL 10-Ks from 2026); "retrievable" fields come back
# with each result so the app can show citations.
SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "title": {"type": "string", "retrievable": True,
                  "keyPropertyMapping": "title"},
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
        "part": {"type": "integer", "retrievable": True},
        "total_parts": {"type": "integer", "retrievable": True},
    },
}
