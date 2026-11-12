"""Retrieve relevant filing chunks from Vertex AI Search."""

from __future__ import annotations

import re
from typing import Protocol

from .models import AppliedFilters, Passage

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class Retriever(Protocol):
    def retrieve(self, query: str, filters: AppliedFilters, k: int) -> list[Passage]: ...


_HEADING = re.compile(r"^\s*#{1,6}\s+(.*?)\s*$")


def split_chunk(content: str) -> tuple[str, str]:
    """Separate the headings Vertex AI Search puts at the top of each chunk.

    With `include_ancestor_headings`, a chunk starts with markdown-style lines such as
    "# Apple Inc. (AAPL) · 10-K · filed 2026-11-03" and "## Item 1A. Risk Factors".
    The first is the document title (already shown separately); the rest name the
    section. Returns (section, body).
    """
    lines = content.splitlines()
    headings: list[str] = []
    i = 0
    while i < len(lines):
        m = _HEADING.match(lines[i])
        if m:
            headings.append(m.group(1))
        elif lines[i].strip():
            break
        i += 1
    section_parts = [" ".join(h.replace("|", " ").split()) for h in headings[1:]]
    section = " · ".join(part for part in section_parts if part)
    body = "\n".join(lines[i:]).strip()
    return section, body or content.strip()


def build_filter(filters: AppliedFilters) -> str:
    """Vertex AI Search filter expression, e.g.
    ticker: ANY("AAPL","MSFT") AND form_type: ANY("10-K") AND filing_year >= 2025
    Values are validated before they get here, so they can be quoted directly.
    """
    parts = []
    if filters.tickers:
        parts.append("ticker: ANY(" + ",".join(f'"{t}"' for t in filters.tickers) + ")")
    if filters.form_types:
        parts.append("form_type: ANY(" + ",".join(f'"{f}"' for f in filters.form_types) + ")")
    if filters.from_year:
        parts.append(f"filing_year >= {int(filters.from_year)}")
    return " AND ".join(parts)


def valid_ticker(ticker: str) -> bool:
    return bool(_TICKER.match(ticker))


def _doc_id_from_chunk_name(name: str) -> str:
    # projects/.../documents/{doc_id}/chunks/{chunk_id}
    parts = name.split("/")
    return parts[parts.index("documents") + 1] if "documents" in parts else ""


class VertexRetriever:
    def __init__(self, serving_config: str, location: str = "global") -> None:
        from google.api_core.client_options import ClientOptions
        from google.cloud import discoveryengine_v1 as de

        self._de = de
        opts = None if location == "global" else ClientOptions(
            api_endpoint=f"{location}-discoveryengine.googleapis.com"
        )
        self._client = de.SearchServiceClient(client_options=opts)
        self._serving_config = serving_config

    def retrieve(self, query: str, filters: AppliedFilters, k: int) -> list[Passage]:
        de = self._de
        spec = de.SearchRequest.ContentSearchSpec
        request = de.SearchRequest(
            serving_config=self._serving_config,
            query=query,
            page_size=k,
            filter=build_filter(filters),
            content_search_spec=spec(search_result_mode=spec.SearchResultMode.CHUNKS),
        )
        response = self._client.search(request=request)
        passages = []
        for result in response.results:
            chunk = de.Chunk.to_dict(result.chunk)
            meta = chunk.get("document_metadata") or {}
            data = meta.get("struct_data") or {}
            section, body = split_chunk(chunk.get("content", ""))
            passages.append(
                Passage(
                    doc_id=_doc_id_from_chunk_name(chunk.get("name", "")),
                    content=body,
                    section=section,
                    title=meta.get("title") or data.get("title", ""),
                    filing_id=str(data.get("filing_id", "")),
                    ticker=str(data.get("ticker", "")),
                    company_name=str(data.get("company_name", "")),
                    form_type=str(data.get("form_type", "")),
                    filing_date=str(data.get("filing_date", "")),
                    source_url=str(data.get("source_url", "")),
                )
            )
            if len(passages) >= k:
                break
        return passages
