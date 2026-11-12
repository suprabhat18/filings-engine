"""Bring the search index up to date with new SEC filings, whenever you choose.

    python -m edgar.update                         # filings from the last 14 days
    python -m edgar.update --days 45               # look further back
    python -m edgar.update --since 2026-10-01      # from a given date
    python -m edgar.update --tickers AAPL,MSFT     # only some companies

1. Ask EDGAR for each company's filings in the window.
2. Skip any filing already in the Firestore catalog (so overlapping windows are free).
3. Download and clean the new ones, save them under data/ (so a future rebuild
   includes them), split them into passages, and import them into Vertex AI Search.
4. Record a summary of the run in Firestore (ingestion_runs); the app shows the
   latest one as "Index last updated".
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from .companies import Company, fetch_companies, load_tickers
from .config import GcpSettings, Settings, load_gcp_settings, load_settings
from .documents import filing_id
from .filings import list_filings
from .publish import BlobStore, Catalog, publish_records
from .run import (
    DEFAULT_OUT_DIR,
    DEFAULT_TICKERS_FILE,
    Client,
    _write_atomic,
    fetch_filing_text,
    filing_record,
    output_path,
)

Importer = Callable[[list[str]], None]


def run_update(
    client: Client,
    companies: list[Company],
    settings: Settings,
    store: BlobStore,
    catalog: Catalog,
    importer: Importer,
    log: Callable[[str], None] = print,
    save_dir: Path | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "since": settings.cutoff.isoformat(),
        "companies": len(companies),
        "seen": 0,
        "new": 0,
        "passages": 0,
        "errors": 0,
        "new_by_form": {},
        "manifest_uris": [],
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
            record = filing_record(filing, text)
            if save_dir is not None:
                _write_atomic(output_path(save_dir, filing), record)
            records.append(record)
            log(f"+ {company.ticker} {filing.form} filed {filing.filing_date}")

    if records:
        result = publish_records(records, store, catalog, log=log)
        summary["new"] = result.filings
        summary["passages"] = result.documents
        summary["manifest_uris"] = result.manifest_uris
        published = set(result.new_filing_ids)
        for r in records:
            if filing_id(r) in published:
                summary["new_by_form"][r["form_type"]] = summary["new_by_form"].get(r["form_type"], 0) + 1
        if result.manifest_uris:
            importer(result.manifest_uris)
    else:
        log("No new filings in this window.")

    summary["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return summary


def main(argv: list[str] | None = None) -> None:
    from .client import SecClient
    from .publish import FirestoreCatalog, GcsStore
    from .search_index import import_documents

    parser = argparse.ArgumentParser(description="Import new SEC filings into the search index.")
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--days", type=int, default=14, help="look back this many days (default 14)")
    window.add_argument("--since", type=date.fromisoformat, help="look back to this date (YYYY-MM-DD)")
    parser.add_argument("--tickers", help="comma-separated tickers; default: all in sp100.txt")
    parser.add_argument("--data", type=Path, default=DEFAULT_OUT_DIR,
                        help="where to save downloaded filings (default: ingestion/data)")
    args = parser.parse_args(argv)

    settings = load_settings()
    days = (date.today() - args.since).days if args.since else args.days
    settings = replace(settings, lookback_days=max(days, 0))
    gcp: GcpSettings = load_gcp_settings()
    catalog = FirestoreCatalog(gcp.project_id)
    tickers = args.tickers.split(",") if args.tickers else load_tickers(DEFAULT_TICKERS_FILE)
    print(f"Checking {len(tickers)} tickers for filings since {settings.cutoff.isoformat()}...")

    start = time.monotonic()
    with SecClient(settings.user_agent, settings.requests_per_second) as client:
        companies, missing = fetch_companies(client, tickers)
        if missing:
            print(f"Tickers not found at the SEC: {', '.join(missing)}")
        summary = run_update(
            client,
            companies,
            settings,
            GcsStore(gcp.project_id, gcp.bucket),
            catalog,
            importer=lambda uris: import_documents(gcp, uris, wait=True),
            save_dir=args.data,
        )
        summary["sec_requests"] = client.request_count

    summary["minutes"] = round((time.monotonic() - start) / 60, 1)
    catalog.record_run(summary)
    print(f"Done: {summary['new']} new filings {summary['new_by_form']} as "
          f"{summary['passages']:,} passages, {summary['errors']} errors, {summary['minutes']} min.")
    if summary["errors"] and summary["new"] == 0 and summary["seen"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
