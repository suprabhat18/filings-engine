"""Daily incremental ingestion (runs as a Cloud Run Job, triggered by Cloud Scheduler).

1. Ask EDGAR for each company's filings from the last DAILY_LOOKBACK_DAYS days
   (default 14, so a missed day or two is caught up automatically).
2. Skip any filing already in the Firestore catalog.
3. Download and clean the new ones, upload them, import them into Vertex AI Search.
4. Record a summary of the run in Firestore (ingestion_runs collection).

Run by hand:  python -m edgar.daily
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from .companies import Company, fetch_companies, load_tickers
from .config import GcpSettings, Settings, load_gcp_settings, load_settings
from .documents import filing_id
from .filings import list_filings
from .publish import Catalog, BlobStore, publish_records
from .run import DEFAULT_TICKERS_FILE, Client, fetch_filing_text, filing_record

Importer = Callable[[str], None]


def run_daily(
    client: Client,
    companies: list[Company],
    settings: Settings,
    store: BlobStore,
    catalog: Catalog,
    importer: Importer,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "since": settings.cutoff.isoformat(),
        "companies": len(companies),
        "seen": 0,
        "new": 0,
        "errors": 0,
        "new_by_form": {},
        "manifest_uri": None,
    }

    records: list[dict[str, Any]] = []
    for company in companies:
        try:
            filings = list_filings(client, company, settings.form_types, settings.cutoff)
        except httpx.HTTPError as exc:
            log(f"! {company.ticker}: could not list filings ({exc})")
            summary["errors"] += 1
            continue
        summary["seen"] += len(filings)
        if not filings:
            continue

        ids = {f: f"{company.cik}-{f.accession_nodash}" for f in filings}
        known = catalog.existing(list(ids.values()))
        for filing in filings:
            if ids[filing] in known:
                continue
            try:
                text = fetch_filing_text(client, filing, log)
            except httpx.HTTPError as exc:
                log(f"! {company.ticker} {filing.form} {filing.accession}: {exc}")
                summary["errors"] += 1
                continue
            records.append(filing_record(filing, text))
            log(f"+ {company.ticker} {filing.form} filed {filing.filing_date}")

    if records:
        result = publish_records(records, store, catalog, log=log)
        summary["new"] = result.filings
        summary["manifest_uri"] = result.manifest_uri
        for r in records:
            if filing_id(r) in set(result.new_filing_ids):
                summary["new_by_form"][r["form_type"]] = summary["new_by_form"].get(r["form_type"], 0) + 1
        if result.manifest_uri:
            importer(result.manifest_uri)
    else:
        log("No new filings today.")

    summary["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return summary


def main() -> None:
    from .client import SecClient
    from .publish import FirestoreCatalog, GcsStore
    from .search_index import import_documents

    settings = load_settings()
    settings = replace(settings, lookback_days=int(os.getenv("DAILY_LOOKBACK_DAYS", "14")))
    gcp: GcpSettings = load_gcp_settings()
    catalog = FirestoreCatalog(gcp.project_id)

    start = time.monotonic()
    with SecClient(settings.user_agent, settings.requests_per_second) as client:
        companies, missing = fetch_companies(client, load_tickers(DEFAULT_TICKERS_FILE))
        if missing:
            print(f"Tickers not found at the SEC: {', '.join(missing)}")
        summary = run_daily(
            client,
            companies,
            settings,
            GcsStore(gcp.project_id, gcp.bucket),
            catalog,
            importer=lambda uri: import_documents(gcp, uri, wait=True),
        )
        summary["sec_requests"] = client.request_count

    summary["minutes"] = round((time.monotonic() - start) / 60, 1)
    catalog.record_run(summary)
    print(f"Done: {summary['new']} new filings {summary['new_by_form']}, "
          f"{summary['errors']} errors, {summary['minutes']} min.")
    # A failing exit code makes Cloud Run mark the execution failed (and retry it).
    if summary["errors"] and summary["new"] == 0 and summary["seen"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
