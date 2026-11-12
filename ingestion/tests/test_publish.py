from __future__ import annotations

import json

from edgar.documents import (
    SCHEMA,
    build_documents,
    filing_id,
    manifest_line,
    split_parts,
    text_to_html,
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


def test_html_has_headings_and_escapes():
    page = text_to_html("Apple <10-K>", "Item 1A. Risk Factors\n\nA & B\nline two\n\nNet sales | 1 | 2")
    assert "<title>Apple &lt;10-K&gt;</title>" in page
    assert "<h2>Item 1A. Risk Factors</h2>" in page
    assert "<p>A &amp; B<br>line two</p>" in page
    assert "<p>Net sales | 1 | 2</p>" in page


def test_split_parts_respects_limit_and_keeps_all_text():
    paras = [("word " * 50).strip() for _ in range(100)]
    text = "\n\n".join(paras)
    parts = split_parts(text, max_bytes=2_000)
    assert len(parts) > 1
    assert all(len(p.encode()) <= 2_000 for p in parts)
    assert "\n\n".join(parts) == text


def test_split_parts_hard_splits_giant_paragraph():
    parts = split_parts("x" * 5_000, max_bytes=2_000)
    assert [len(p) for p in parts] == [2_000, 2_000, 1_000]


def test_build_documents_ids_and_metadata():
    (doc,) = build_documents(record())
    assert doc.doc_id == "320193-000032019326000010" == filing_id(record())
    assert doc.struct_data["filing_year"] == 2026
    assert doc.struct_data["ticker"] == "AAPL"
    assert set(doc.struct_data) <= set(SCHEMA["properties"])  # every field is in the schema

    line = manifest_line(doc, "gs://b/docs/x.html")
    assert line == {
        "id": doc.doc_id,
        "structData": doc.struct_data,
        "content": {"mimeType": "text/html", "uri": "gs://b/docs/x.html"},
    }


def test_build_documents_multi_part(monkeypatch):
    import edgar.documents as d
    monkeypatch.setattr(d, "MAX_PART_BYTES", 50)
    docs = d.build_documents(record(text="\n\n".join(["paragraph number %d here" % i for i in range(10)])))
    assert len(docs) > 1
    assert docs[0].doc_id.endswith("-p1") and docs[0].struct_data["total_parts"] == len(docs)
    assert all(len(doc.doc_id) <= 63 for doc in docs)  # Vertex AI Search ID limit
    assert "(part 1 of" in docs[0].title


def test_publish_uploads_new_only_and_writes_manifest():
    store, catalog = FakeStore(), FakeCatalog(existing=["320193-000032019326000009"])
    records = [
        record(),
        record(accession="000032019326000009"),  # already published
        record(accession="000178951926000001", cik=1789519, ticker="GOOG",
               company_name="Alphabet Inc."),
    ]
    logs = []
    result = publish_records(records, store, catalog, log=logs.append, workers=2)

    assert result.filings == 2 and result.skipped == 1 and result.documents == 2
    assert "docs/320193-000032019326000010.html" in store.files
    assert "docs/320193-000032019326000009.html" not in store.files

    manifest_path = result.manifest_uri.removeprefix("gs://b/")
    lines = [json.loads(l) for l in store.files[manifest_path].splitlines()]
    assert {l["id"] for l in lines} == {"320193-000032019326000010", "1789519-000178951926000001"}

    assert catalog.filings["320193-000032019326000010"]["doc_ids"] == ["320193-000032019326000010"]
    assert set(catalog.companies) == {"AAPL", "GOOG"}

    # Second run: nothing left to do, no new manifest.
    again = publish_records(records, store, catalog, log=logs.append)
    assert again.filings == 0 and again.manifest_uri is None


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
