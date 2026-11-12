"""Find a company's filings in EDGAR and locate their documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator, Protocol

from bs4 import BeautifulSoup

from .companies import Company

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}"

_COLUMNS = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
_TEXT_EXTENSIONS = (".htm", ".html", ".txt")


class JsonClient(Protocol):
    def get_json(self, url: str) -> Any: ...


@dataclass(frozen=True)
class Filing:
    company: Company
    accession: str  # e.g. 0000320193-25-000079
    form: str
    filing_date: date
    report_date: str | None
    primary_document: str

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def folder_url(self) -> str:
        return ARCHIVE_URL.format(
            cik=self.company.cik, accession_nodash=self.accession_nodash
        )

    @property
    def primary_url(self) -> str:
        return f"{self.folder_url}/{self.primary_document}"

    @property
    def index_url(self) -> str:
        return f"{self.folder_url}/{self.accession}-index.htm"


def _rows(columns: dict[str, list[Any]]) -> Iterator[dict[str, Any]]:
    """EDGAR returns filings column-wise; yield them one row at a time."""
    n = len(columns.get("accessionNumber", []))
    for i in range(n):
        yield {k: (columns.get(k) or [None] * n)[i] for k in _COLUMNS}


def list_filings(
    client: JsonClient,
    company: Company,
    forms: tuple[str, ...],
    cutoff: date,
) -> list[Filing]:
    """All filings of the given form types filed on or after `cutoff`, newest first.

    The main submissions file only holds the most recent ~1,000 filings. Banks
    such as JPM file far more than that, so older pages are fetched too when
    they overlap the date window.
    """
    submissions = client.get_json(SUBMISSIONS_URL.format(cik10=company.cik10))
    pages = [submissions["filings"]["recent"]]
    for page in submissions["filings"].get("files", []):
        if date.fromisoformat(page["filingTo"]) >= cutoff:
            pages.append(client.get_json(SUBMISSIONS_PAGE_URL.format(name=page["name"])))

    filings: list[Filing] = []
    seen: set[str] = set()
    for page in pages:
        for row in _rows(page):
            if row["form"] not in forms or not row["primaryDocument"]:
                continue
            filed = date.fromisoformat(row["filingDate"])
            if filed < cutoff or row["accessionNumber"] in seen:
                continue
            seen.add(row["accessionNumber"])
            filings.append(
                Filing(
                    company=company,
                    accession=row["accessionNumber"],
                    form=row["form"],
                    filing_date=filed,
                    report_date=row["reportDate"] or None,
                    primary_document=row["primaryDocument"],
                )
            )
    filings.sort(key=lambda f: f.filing_date, reverse=True)
    return filings


def exhibit_urls(
    index_html: str, folder_url: str, prefixes: tuple[str, ...] = ("EX-99",)
) -> list[str]:
    """URLs of exhibits (by default EX-99.x) listed on a filing's index page.

    An 8-K's main document is often just a cover page; the substance, such as
    an earnings press release, is in exhibit 99.1.
    """
    soup = BeautifulSoup(index_html, "lxml")
    table = soup.find("table", class_="tableFile")
    if table is None:
        return []
    urls = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        doc_type = cells[3].get_text(strip=True).upper()
        link = cells[2].find("a")
        if link is None or not doc_type.startswith(prefixes):
            continue
        name = link["href"].rsplit("/", 1)[-1]
        if name.lower().endswith(_TEXT_EXTENSIONS):
            urls.append(f"{folder_url}/{name}")
    return urls
