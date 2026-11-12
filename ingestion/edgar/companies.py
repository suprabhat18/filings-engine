"""Turn stock tickers into SEC company IDs (CIKs)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


class JsonClient(Protocol):
    def get_json(self, url: str) -> Any: ...


@dataclass(frozen=True)
class Company:
    ticker: str
    cik: int
    name: str

    @property
    def cik10(self) -> str:
        """CIK zero-padded to 10 digits, as the submissions API expects."""
        return f"{self.cik:010d}"


def normalize_ticker(ticker: str) -> str:
    """The SEC writes class shares with a dash: BRK.B -> BRK-B."""
    return ticker.strip().upper().replace(".", "-")


def load_tickers(path: Path) -> list[str]:
    """Read one ticker per line; blank lines and # comments are ignored."""
    tickers = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            tickers.append(line)
    return tickers


def resolve_companies(
    tickers: list[str], ticker_map: dict[str, dict[str, Any]]
) -> tuple[list[Company], list[str]]:
    """Match tickers against the SEC ticker file.

    Returns (companies, missing_tickers). Share classes of the same company
    (GOOG / GOOGL) share a CIK, so each company appears once.
    """
    by_ticker = {normalize_ticker(e["ticker"]): e for e in ticker_map.values()}
    companies: list[Company] = []
    missing: list[str] = []
    seen_ciks: set[int] = set()
    for ticker in tickers:
        entry = by_ticker.get(normalize_ticker(ticker))
        if entry is None:
            missing.append(ticker)
            continue
        cik = int(entry["cik_str"])
        if cik in seen_ciks:
            continue
        seen_ciks.add(cik)
        companies.append(
            Company(ticker=normalize_ticker(ticker), cik=cik, name=entry["title"])
        )
    return companies, missing


def fetch_companies(
    client: JsonClient, tickers: list[str]
) -> tuple[list[Company], list[str]]:
    return resolve_companies(tickers, client.get_json(TICKERS_URL))
