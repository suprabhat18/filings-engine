"""Unit tests for filter building, citation parsing and Vertex AI response parsing."""

from __future__ import annotations

from google.cloud import discoveryengine_v1 as de

from app.llm import format_passages
from app.models import AppliedFilters, Passage
from app.rag import cited_numbers
from app.retrieval import VertexRetriever, build_filter


def test_build_filter():
    assert build_filter(AppliedFilters()) == ""
    assert build_filter(AppliedFilters(tickers=["AAPL", "BRK-B"], form_types=["10-K"], from_year=2025)) == (
        'ticker: ANY("AAPL","BRK-B") AND form_type: ANY("10-K") AND filing_year >= 2025'
    )


def test_cited_numbers():
    assert cited_numbers("A [1]. B [2][4]. C [3, 5]. Year [2026 is not one") == {1, 2, 3, 4, 5}
    assert cited_numbers("no citations") == set()


def test_format_passages_numbers_and_truncates():
    text = format_passages([Passage(doc_id="a", content="x" * 5000, title="Apple 10-K")], max_chars=10)
    assert text == "[1] Apple 10-K\n" + "x" * 10


def test_vertex_retriever_parses_chunk_results():
    chunk = de.Chunk(
        name="projects/p/locations/global/collections/default_collection/dataStores/ds"
             "/branches/0/documents/320193-000032019326000010/chunks/c7",
        content="Item 1A. Risk Factors: supply chain concentration...",
        document_metadata=de.Chunk.DocumentMetadata(
            title="Apple Inc. (AAPL) · 10-K · filed 2026-10-30",
            struct_data={
                "filing_id": "320193-000032019326000010", "ticker": "AAPL",
                "company_name": "Apple Inc.", "form_type": "10-K", "filing_date": "2026-10-30",
                "source_url": "https://www.sec.gov/x", "cik": 320193,
            },
        ),
    )

    class FakeSearchClient:
        def __init__(self):
            self.request = None

        def search(self, request):
            self.request = request
            return de.SearchResponse(results=[de.SearchResponse.SearchResult(chunk=chunk)])

    retriever = VertexRetriever.__new__(VertexRetriever)
    retriever._de = de
    retriever._client = FakeSearchClient()
    retriever._serving_config = "projects/p/.../servingConfigs/default_search"

    (p,) = retriever.retrieve("supply chain", AppliedFilters(tickers=["AAPL"]), 5)
    assert p.doc_id == "320193-000032019326000010"
    assert p.ticker == "AAPL" and p.form_type == "10-K" and p.filing_date == "2026-10-30"
    assert p.title.startswith("Apple Inc.") and p.source_url == "https://www.sec.gov/x"
    assert "supply chain" in p.content

    req = retriever._client.request
    assert req.filter == 'ticker: ANY("AAPL")' and req.page_size == 5
    assert req.content_search_spec.search_result_mode == de.SearchRequest.ContentSearchSpec.SearchResultMode.CHUNKS


def test_firestore_store_imports():
    # FirestoreStore relies on these names existing in the installed library.
    from google.cloud import firestore
    assert hasattr(firestore, "FieldFilter") and hasattr(firestore, "transactional")
