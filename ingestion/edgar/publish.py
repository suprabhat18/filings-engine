"""Publish saved filings: split them into passages, upload the import files to Cloud
Storage, record the filings in Firestore, and import the passages into Vertex AI Search.

Usage (from the ingestion/ folder):
    python -m edgar.publish                       # publish saved filings not yet published
    python -m edgar.publish --rebuild             # (re)publish every saved filing
    python -m edgar.publish --tickers AAPL,MSFT   # only these companies
    python -m edgar.publish --no-import           # upload only; import later

Filings already in the Firestore catalog are skipped unless --rebuild is given, so
this is safe to re-run. `python -m edgar.update` uses the same code for new filings.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Protocol

from .documents import build_documents, filing_id, manifest_line

FILINGS_COLLECTION = "filings"
COMPANIES_COLLECTION = "companies"
RUNS_COLLECTION = "ingestion_runs"

# Each import file holds up to this many passages (about 30 MB). Vertex AI Search
# accepts up to 100 files per import, so one import covers ~500,000 passages.
LINES_PER_MANIFEST = 5_000
BATCH = 100  # filings read and checked against the catalog at a time


class BlobStore(Protocol):
    bucket_name: str

    def upload(self, path: str, data: str, content_type: str) -> str: ...


class Catalog(Protocol):
    def existing(self, filing_ids: list[str]) -> set[str]: ...
    def save(self, filings: list[dict[str, Any]], companies: list[dict[str, Any]]) -> None: ...


# ---------- Google Cloud implementations ----------

class GcsStore:
    def __init__(self, project: str, bucket: str) -> None:
        from google.cloud import storage

        self.bucket_name = bucket
        self._bucket = storage.Client(project=project).bucket(bucket)

    def upload(self, path: str, data: str, content_type: str) -> str:
        self._bucket.blob(path).upload_from_string(data, content_type=content_type)
        return f"gs://{self.bucket_name}/{path}"


class FirestoreCatalog:
    def __init__(self, project: str, database: str = "(default)") -> None:
        from google.cloud import firestore

        self._db = firestore.Client(project=project, database=database)

    def existing(self, filing_ids: list[str]) -> set[str]:
        found: set[str] = set()
        col = self._db.collection(FILINGS_COLLECTION)
        for i in range(0, len(filing_ids), 300):
            refs = [col.document(fid) for fid in filing_ids[i : i + 300]]
            found.update(snap.id for snap in self._db.get_all(refs) if snap.exists)
        return found

    def record_run(self, summary: dict[str, Any]) -> None:
        """Keep a log of update runs; the app shows the latest as 'last updated'."""
        run_id = summary["started_at"].replace(":", "").replace("-", "")
        self._db.collection(RUNS_COLLECTION).document(run_id).set(summary)

    def save(self, filings: list[dict[str, Any]], companies: list[dict[str, Any]]) -> None:
        items = [(FILINGS_COLLECTION, f["filing_id"], f) for f in filings]
        items += [(COMPANIES_COLLECTION, c["ticker"], c) for c in companies]
        for i in range(0, len(items), 400):  # Firestore batches hold up to 500 writes
            batch = self._db.batch()
            for collection, doc_id, data in items[i : i + 400]:
                batch.set(self._db.collection(collection).document(doc_id), data, merge=True)
            batch.commit()


# ---------- publishing ----------

@dataclass
class PublishResult:
    filings: int = 0
    documents: int = 0
    skipped: int = 0
    manifest_uris: list[str] = field(default_factory=list)
    new_filing_ids: list[str] = field(default_factory=list)


def catalog_entry(record: dict[str, Any], passages: int) -> dict[str, Any]:
    return {
        "filing_id": filing_id(record),
        "ticker": record["ticker"],
        "company_name": record["company_name"],
        "cik": record["cik"],
        "form_type": record["form_type"],
        "filing_date": record["filing_date"],
        "filing_year": int(record["filing_date"][:4]),
        "report_date": record.get("report_date"),
        "accession_number": record["accession_number"],
        "source_url": record["source_url"],
        "index_url": record["index_url"],
        "char_count": record["char_count"],
        "passages": passages,
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _batches(items: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def publish_records(
    records: Iterable[dict[str, Any]],
    store: BlobStore,
    catalog: Catalog,
    log: Callable[[str], None] = print,
    rebuild: bool = False,
    lines_per_manifest: int = LINES_PER_MANIFEST,
) -> PublishResult:
    """Split filings into passages and upload them as JSONL import files.

    `records` may be a lazy iterator: filings are processed in small batches and each
    import file is uploaded as soon as it is full, so memory use stays low even for
    a full rebuild. Returns the uploaded file URIs; the caller runs the import.
    """
    result = PublishResult()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines: list[str] = []
    entries: list[dict[str, Any]] = []
    companies: dict[str, dict[str, Any]] = {}

    def upload_manifest() -> None:
        nonlocal lines
        if not lines:
            return
        n = len(result.manifest_uris) + 1
        uri = store.upload(f"manifests/{stamp}-{n:03d}.jsonl", "\n".join(lines) + "\n",
                           "application/x-ndjson")
        result.manifest_uris.append(uri)
        lines = []

    for batch in _batches(records, BATCH):
        ids = [filing_id(r) for r in batch]
        already = set() if rebuild else catalog.existing(ids)
        for record in batch:
            if filing_id(record) in already:
                result.skipped += 1
                continue
            docs = build_documents(record)
            for doc in docs:
                lines.append(json.dumps(manifest_line(doc), ensure_ascii=False))
                if len(lines) >= lines_per_manifest:
                    upload_manifest()
            entries.append(catalog_entry(record, len(docs)))
            companies[record["ticker"]] = {
                "ticker": record["ticker"], "name": record["company_name"], "cik": record["cik"],
            }
            result.filings += 1
            result.documents += len(docs)
            if result.filings % 250 == 0:
                log(f"  prepared {result.filings} filings ({result.documents:,} passages)")
    upload_manifest()

    if not result.filings:
        log(f"Nothing new to publish ({result.skipped} filings already published).")
        return result

    # Catalog is written last: if anything above fails, the next run retries these filings.
    catalog.save(entries, list(companies.values()))
    result.new_filing_ids = [e["filing_id"] for e in entries]
    return result


def iter_saved_records(data_dir: Path, tickers: set[str] | None = None) -> Iterator[dict[str, Any]]:
    """Saved filings, read one at a time (data/filings/<TICKER>/<accession>.json)."""
    for path in sorted((data_dir / "filings").glob("*/*.json")):
        if tickers and path.parent.name.upper() not in tickers:
            continue
        yield json.loads(path.read_text())


def main(argv: list[str] | None = None) -> None:
    from .config import load_gcp_settings
    from .run import DEFAULT_OUT_DIR
    from .search_index import import_documents

    parser = argparse.ArgumentParser(description="Publish saved filings to GCP.")
    parser.add_argument("--data", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--tickers", help="comma-separated tickers, e.g. AAPL,MSFT")
    parser.add_argument("--rebuild", action="store_true",
                        help="publish every saved filing, even ones already in the catalog")
    parser.add_argument("--no-import", action="store_true", help="upload only")
    args = parser.parse_args(argv)

    gcp = load_gcp_settings()
    tickers = {t.strip().upper() for t in args.tickers.split(",")} if args.tickers else None
    print(f"Reading saved filings from {args.data}"
          + (f" for {', '.join(sorted(tickers))}" if tickers else ""))

    catalog = FirestoreCatalog(gcp.project_id)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = publish_records(
        iter_saved_records(args.data, tickers),
        GcsStore(gcp.project_id, gcp.bucket),
        catalog,
        rebuild=args.rebuild,
    )
    if result.manifest_uris:
        print(f"Published {result.filings} filings as {result.documents:,} passages "
              f"in {len(result.manifest_uris)} import file(s).")
        if args.no_import:
            print("Import later with: python -m edgar.search_index import " + " ".join(result.manifest_uris))
            return
        import_documents(gcp, result.manifest_uris)
        catalog.record_run({
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": "rebuild" if args.rebuild else "publish",
            "new": result.filings,
            "passages": result.documents,
            "manifest_uris": result.manifest_uris,
        })


if __name__ == "__main__":
    main()
