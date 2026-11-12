from __future__ import annotations

import json

import base64

from edgar.documents import (
    MAX_WORDS,
    SCHEMA,
    build_documents,
    filing_id,
    manifest_line,
    split_passages,
)
from edgar.publish import publish_records


def record(accession="000032019326000010", text="Item 1A. Risk Factors\n\nSupply chain risk.", **kw):
    base = {
        "id": accession,
        "accession_number": "0000320193-26-000010",
        "cik": 320193,
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "form_type": "10-K",
        "filing_date": "2026-10-30",
        "report_date": "2026-09-27",
        "source_url": "https://www.sec.gov/Archives/edgar/data/320193/x/k.htm",
        "index_url": "https://www.sec.gov/Archives/edgar/data/320193/x/i.htm",
        "text": text,
        "char_count": len(text),
    }
    base.update(kw)
    return base


class FakeStore:
    bucket_name = "b"

    def __init__(self):
        self.files: dict[str, str] = {}

    def upload(self, path, data, content_type):
        self.files[path] = data
        return f"gs://b/{path}"


class FakeCatalog:
    def __init__(self, existing=()):
        self.filings = {fid: {} for fid in existing}
        self.companies = {}

    def existing(self, ids):
        return {i for i in ids if i in self.filings}

    def save(self, filings, companies):
        self.filings.update({f["filing_id"]: f for f in filings})
        self.companies.update({c["ticker"]: c for c in companies})


FILING_TEXT = """Apple Inc.
FORM 10-K
Item 1A. | Risk Factors | 5
Item 7. | Management's Discussion and Analysis | 20
PART I
Item 1.
Business
The Company designs, manufactures and markets smartphones, personal computers, tablets and wearables worldwide.
12
Item 1A.
Risk Factors
The Company depends on component and product manufacturing provided by outsourcing partners, many located outside the U.S.
Supply chain disruptions could materially affect results. Item 5 of this report describes more.
Item 5 is not applicable.
PART II
Item 7. Management's Discussion and Analysis of Financial Condition
Net sales increased due to higher iPhone sales across all geographic segments this fiscal year.
Net sales | 391,035 | 383,285
"""


def test_split_passages_tracks_sections():
    passages = split_passages(FILING_TEXT)
    sections = [s for s, _ in passages]
    assert sections == [
        "",  # cover page and table of contents (lines with "|" are never headings)
        "Item 1. Business",
        "Item 1A. Risk Factors",
        "Item 7. Management's Discussion and Analysis of Financial Condition",
    ]
    text = dict(passages)
    assert "outsourcing partners" in text["Item 1A. Risk Factors"]
    assert "Item 5 is not applicable." in text["Item 1A. Risk Factors"]  # a sentence, not a heading
    assert "12" not in text["Item 1. Business"].split()                  # page number dropped
    assert "Net sales | 391,035" in text[sections[-1]]                    # table rows kept


def test_split_passages_8k_items_and_exhibits():
    text = ("Item 2.02 Results of Operations and Financial Condition\n"
            "On October 30, 2026 the Company issued a press release announcing quarterly results.\n\n"
            "Exhibit 99.1\nApple reports fourth quarter results with record revenue in services and growth.")
    assert [s for s, _ in split_passages(text)] == [
        "Item 2.02 Results of Operations and Financial Condition", "Exhibit 99.1",
    ]


def test_split_passages_sizes_and_keeps_all_words():
    lines = [("word " * 60).strip() for _ in range(40)] + [("long " * 1200).strip()]
    passages = split_passages("Item 7. MD&A\n" + "\n".join(lines))
    assert len(passages) > 5
    assert all(len(p.split()) <= MAX_WORDS for _, p in passages)
    assert sum(len(p.split()) for _, p in passages) == 60 * 40 + 1200


def test_build_documents_ids_and_metadata():
    docs = build_documents(record(text=FILING_TEXT))
    assert len(docs) == 4
    doc = docs[2]
    assert doc.doc_id == f"{filing_id(record())}-0003"
    assert all(len(d.doc_id) <= 63 for d in docs)  # Vertex AI Search ID limit
    data = doc.struct_data
    assert data["section"] == "Item 1A. Risk Factors" and data["passage"] == 3
    assert data["total_passages"] == 4 and data["filing_year"] == 2026 and data["ticker"] == "AAPL"
    assert "outsourcing partners" in data["text"]
    assert doc.content.startswith("Apple Inc. (AAPL) · 10-K · filed 2026-10-30 · Item 1A. Risk Factors\n\n")
    assert set(data) <= set(SCHEMA["properties"])  # every field is in the schema

    line = manifest_line(doc)
    assert line["id"] == doc.doc_id and line["structData"] == data
    assert line["content"]["mimeType"] == "text/plain"
    assert base64.b64decode(line["content"]["rawBytes"]).decode() == doc.content


def test_manifest_line_parses_as_a_vertex_document():
    from google.cloud import discoveryengine_v1 as de

    doc = build_documents(record(text=FILING_TEXT))[2]
    parsed = de.Document.from_json(json.dumps(manifest_line(doc)))
    assert parsed.id == doc.doc_id
    assert parsed.content.raw_bytes.decode() == doc.content
    assert parsed.struct_data["section"] == "Item 1A. Risk Factors"


def test_publish_new_only_in_sharded_manifests():
    store, catalog = FakeStore(), FakeCatalog(existing=["320193-000032019326000009"])
    records = [
        record(text=FILING_TEXT),
        record(accession="000032019326000009", text=FILING_TEXT),  # already published
        record(accession="000178951926000001", cik=1789519, ticker="GOOG",
               company_name="Alphabet Inc.", text=FILING_TEXT),
    ]
    result = publish_records(iter(records), store, catalog, log=lambda _: None, lines_per_manifest=3)

    assert result.filings == 2 and result.skipped == 1 and result.documents == 8
    assert len(result.manifest_uris) == 3  # 8 passages, at most 3 per file
    ids = [json.loads(l)["id"] for uri in result.manifest_uris
           for l in store.files[uri.removeprefix("gs://b/")].splitlines()]
    assert len(ids) == 8 and not any("000032019326000009" in i for i in ids)

    assert catalog.filings["320193-000032019326000010"]["passages"] == 4
    assert set(catalog.companies) == {"AAPL", "GOOG"}

    # Second run: nothing left to do, no new files. --rebuild republishes everything.
    again = publish_records(records, store, catalog, log=lambda _: None)
    assert again.filings == 0 and again.manifest_uris == []
    rebuilt = publish_records(records, store, catalog, log=lambda _: None, rebuild=True)
    assert rebuilt.filings == 3 and rebuilt.skipped == 0


def test_iter_saved_records_filters_by_ticker(tmp_path):
    from edgar.publish import iter_saved_records

    for ticker, acc in [("AAPL", "1"), ("AAPL", "2"), ("MSFT", "3")]:
        path = tmp_path / "filings" / ticker / f"{acc}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": acc, "ticker": ticker}))
    assert [r["id"] for r in iter_saved_records(tmp_path)] == ["1", "2", "3"]
    assert [r["id"] for r in iter_saved_records(tmp_path, {"MSFT"})] == ["3"]


def test_schema_key_title_is_not_searchable_or_indexable():
    # Vertex AI Search rejects a keyPropertyMapping field marked searchable/indexable.
    for name, prop in SCHEMA["properties"].items():
        if "keyPropertyMapping" in prop:
            assert not prop.get("searchable") and not prop.get("indexable"), name


def test_merge_schema_keeps_detected_types_and_adds_annotations():
    from edgar.search_index import merge_schema

    detected = {"type": "object", "properties": {
        "filing_date": {"type": "string", "format": "date", "retrievable": True},
        "filing_year": {"type": "number"},
        "title": {"type": "string", "searchable": True},
    }}
    merged = merge_schema(detected, SCHEMA)
    p = merged["properties"]
    assert p["filing_date"]["format"] == "date"            # detected type kept
    assert p["filing_year"]["type"] == "number" and p["filing_year"]["indexable"]
    assert p["title"]["keyPropertyMapping"] == "title" and "searchable" not in p["title"]
    assert p["ticker"] == SCHEMA["properties"]["ticker"]   # missing field added as-is
    assert merge_schema({}, SCHEMA)["properties"]["form_type"]["indexable"]
