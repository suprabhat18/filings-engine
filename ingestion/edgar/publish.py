"""Publish saved filings: upload to Cloud Storage, record them in Firestore, and
import them into Vertex AI Search.

Usage (from the ingestion/ folder, after `python -m edgar.run`):
    python -m edgar.publish            # publish everything not yet published
    python -m edgar.publish --no-import   # upload only; import later

Only filings missing from the Firestore catalog are uploaded, so this is safe to
re-run and is the same code path the daily job uses.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from .documents import build_documents, filing_id, manifest_line

FILINGS_COLLECTION = "filings"
COMPANIES_COLLECTION = "companies"


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
        """Keep a log of daily runs (shows the pipeline really runs every day)."""
        run_id = summary["started_at"].replace(":", "").replace("-", "")
        self._db.collection("ingestion_runs").document(run_id).set(summary)

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
    manifest_uri: str | None = None
    new_filing_ids: list[str] = field(default_factory=list)


def catalog_entry(record: dict[str, Any], doc_ids: list[str]) -> dict[str, Any]:
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
        "doc_ids": doc_ids,
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def publish_records(
    records: Iterable[dict[str, Any]],
    store: BlobStore,
    catalog: Catalog,
    log: Callable[[str], None] = print,
    workers: int = 16,
) -> PublishResult:
    records = list(records)
    result = PublishResult()
    if not records:
        return result

    already = catalog.existing([filing_id(r) for r in records])
    todo = [r for r in records if filing_id(r) not in already]
    result.skipped = len(records) - len(todo)
    if not todo:
        log(f"Nothing new to publish ({result.skipped} filings already published).")
        return result

    log(f"Uploading {len(todo)} new filings ({result.skipped} already published)...")

    def upload_one(record: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        lines = []
        for doc in build_documents(record):
            uri = store.upload(f"docs/{doc.doc_id}.html", doc.html, "text/html; charset=utf-8")
            lines.append(manifest_line(doc, uri))
        return record, lines

    manifest: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (record, lines) in enumerate(pool.map(upload_one, todo), 1):
            manifest.extend(lines)
            entries.append(catalog_entry(record, [line["id"] for line in lines]))
            if n % 250 == 0 or n == len(todo):
                log(f"  uploaded {n}/{len(todo)}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result.manifest_uri = store.upload(
        f"manifests/{stamp}.jsonl",
        "\n".join(json.dumps(line, ensure_ascii=False) for line in manifest) + "\n",
        "application/x-ndjson",
    )

    companies = {
        r["ticker"]: {"ticker": r["ticker"], "name": r["company_name"], "cik": r["cik"]}
        for r in todo
    }
    # Catalog is written last: if anything above fails, the next run retries these filings.
    catalog.save(entries, list(companies.values()))

    result.filings = len(todo)
    result.documents = len(manifest)
    result.new_filing_ids = [e["filing_id"] for e in entries]
    return result


def load_saved_records(data_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(p.read_text())
        for p in sorted((data_dir / "filings").glob("*/*.json"))
    ]


def main(argv: list[str] | None = None) -> None:
    from .config import load_gcp_settings
    from .run import DEFAULT_OUT_DIR
    from .search_index import import_documents

    parser = argparse.ArgumentParser(description="Publish saved filings to GCP.")
    parser.add_argument("--data", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--no-import", action="store_true", help="upload only")
    args = parser.parse_args(argv)

    gcp = load_gcp_settings()
    records = load_saved_records(args.data)
    print(f"Found {len(records)} saved filings in {args.data}")

    result = publish_records(
        records,
        GcsStore(gcp.project_id, gcp.bucket),
        FirestoreCatalog(gcp.project_id),
    )
    if result.manifest_uri:
        print(f"Published {result.filings} filings as {result.documents} search documents.")
        print(f"Manifest: {result.manifest_uri}")
        if not args.no_import:
            import_documents(gcp, result.manifest_uri)


if __name__ == "__main__":
    main()
