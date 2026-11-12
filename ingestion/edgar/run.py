"""Pull S&P 100 filings from SEC EDGAR and save them as JSON files.

Usage (from the ingestion/ folder):
    python -m edgar.run                    # all companies in sp100.txt
    python -m edgar.run --limit 3          # quick test: first 3 companies
    python -m edgar.run --tickers AAPL,MSFT

Re-running is safe: filings already saved are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

import httpx

from .clean import html_to_text
from .companies import Company, fetch_companies, load_tickers
from .config import Settings, load_settings
from .filings import Filing, exhibit_urls, list_filings

INGESTION_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TICKERS_FILE = INGESTION_DIR / "sp100.txt"
DEFAULT_OUT_DIR = INGESTION_DIR / "data"


class Client(Protocol):
    request_count: int

    def get_json(self, url: str): ...
    def get_text(self, url: str) -> str: ...


def output_path(out_dir: Path, filing: Filing) -> Path:
    return out_dir / "filings" / filing.company.ticker / f"{filing.accession_nodash}.json"


def filing_record(filing: Filing, text: str) -> dict:
    """The JSON saved per filing. These fields become search filters and citations."""
    return {
        "id": filing.accession_nodash,
        "accession_number": filing.accession,
        "cik": filing.company.cik,
        "ticker": filing.company.ticker,
        "company_name": filing.company.name,
        "form_type": filing.form,
        "filing_date": filing.filing_date.isoformat(),
        "report_date": filing.report_date,
        "source_url": filing.primary_url,
        "index_url": filing.index_url,
        "char_count": len(text),
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "text": text,
    }


def fetch_filing_text(client: Client, filing: Filing, log: Callable[[str], None]) -> str:
    text = html_to_text(client.get_text(filing.primary_url))
    if filing.form == "8-K":
        try:
            urls = exhibit_urls(client.get_text(filing.index_url), filing.folder_url)
        except httpx.HTTPError as exc:
            log(f"    ! {filing.accession}: could not read exhibit list ({exc})")
            urls = []
        for url in urls:
            try:
                text += "\n\n" + html_to_text(client.get_text(url))
            except httpx.HTTPError as exc:
                log(f"    ! {filing.accession}: skipped exhibit {url} ({exc})")
    return text


def _write_atomic(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".json.{os.getpid()}.tmp")  # unique per process
    tmp.write_text(json.dumps(record, ensure_ascii=False))
    os.replace(tmp, path)


def ingest(
    client: Client,
    companies: list[Company],
    settings: Settings,
    out_dir: Path,
    log: Callable[[str], None] = print,
) -> Counter:
    stats: Counter = Counter()
    for i, company in enumerate(companies, 1):
        try:
            filings = list_filings(client, company, settings.form_types, settings.cutoff)
        except httpx.HTTPError as exc:
            log(f"[{i}/{len(companies)}] {company.ticker}: could not list filings ({exc})")
            stats["company_errors"] += 1
            continue

        new = 0
        for filing in filings:
            path = output_path(out_dir, filing)
            if path.exists():
                stats["skipped_existing"] += 1
                stats[f"form:{filing.form}"] += 1
                continue
            try:
                text = fetch_filing_text(client, filing, log)
            except httpx.HTTPError as exc:
                log(f"    ! {company.ticker} {filing.form} {filing.accession}: {exc}")
                stats["filing_errors"] += 1
                continue
            _write_atomic(path, filing_record(filing, text))
            stats[f"form:{filing.form}"] += 1
            stats["downloaded"] += 1
            new += 1

        stats["companies"] += 1
        log(f"[{i}/{len(companies)}] {company.ticker}: {len(filings)} filings ({new} new)")
    return stats


def print_summary(stats: Counter, missing: list[str], elapsed: float, requests: int) -> None:
    forms = sorted((k.split(":", 1)[1], v) for k, v in stats.items() if k.startswith("form:"))
    total = sum(v for _, v in forms)
    print("\n" + "=" * 44)
    print(f"Companies processed : {stats['companies']}")
    for form, count in forms:
        print(f"  {form:<6}            : {count:,}")
    print(f"Total filings saved : {total:,}")
    print(f"  new this run      : {stats['downloaded']:,}")
    print(f"  already had       : {stats['skipped_existing']:,}")
    if stats["filing_errors"] or stats["company_errors"]:
        print(f"Errors              : {stats['filing_errors']} filings, "
              f"{stats['company_errors']} companies (re-run to retry)")
    if missing:
        print(f"Tickers not found   : {', '.join(missing)}")
    print(f"SEC requests        : {requests:,} in {elapsed / 60:.1f} min")
    print("=" * 44)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tickers-file", type=Path, default=DEFAULT_TICKERS_FILE)
    parser.add_argument("--tickers", help="comma-separated tickers; overrides --tickers-file")
    parser.add_argument("--limit", type=int, help="only the first N companies (for testing)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    settings = load_settings()
    tickers = args.tickers.split(",") if args.tickers else load_tickers(args.tickers_file)

    from .client import SecClient

    start = time.monotonic()
    with SecClient(settings.user_agent, settings.requests_per_second) as client:
        companies, missing = fetch_companies(client, tickers)
        if args.limit:
            companies = companies[: args.limit]
        print(
            f"{len(companies)} companies · forms {', '.join(settings.form_types)} · "
            f"filed since {settings.cutoff.isoformat()}"
        )
        stats = ingest(client, companies, settings, args.out)
        print_summary(stats, missing, time.monotonic() - start, client.request_count)


if __name__ == "__main__":
    main()
