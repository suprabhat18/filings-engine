"""Offline tests: a fake client serves saved-style EDGAR responses."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from edgar.clean import html_to_text
from edgar.companies import TICKERS_URL, Company, resolve_companies
from edgar.config import Settings
from edgar.filings import exhibit_urls, list_filings
from edgar.run import ingest, output_path

APPLE = Company(ticker="AAPL", cik=320193, name="Apple Inc.")


class FakeClient:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []
        self.request_count = 0

    def _get(self, url: str):
        self.calls.append(url)
        self.request_count += 1
        if url not in self.responses:
            raise httpx.HTTPStatusError(
                "404", request=httpx.Request("GET", url), response=httpx.Response(404)
            )
        return self.responses[url]

    def get_json(self, url):
        return self._get(url)

    def get_text(self, url):
        return self._get(url)


# ---------- companies ----------

TICKER_FILE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
    "2": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
    "3": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
}


def test_resolve_handles_class_shares_and_missing():
    companies, missing = resolve_companies(["AAPL", "GOOG", "GOOGL", "BRK.B", "ZZZZ"], TICKER_FILE)
    assert [c.ticker for c in companies] == ["AAPL", "GOOG", "BRK-B"]
    assert missing == ["ZZZZ"]
    assert companies[0].cik10 == "0000320193"


# ---------- listing filings ----------

def _cols(rows):
    keys = ["accessionNumber", "filingDate", "reportDate", "form", "primaryDocument"]
    return {k: [r[i] for r in rows] for i, k in enumerate(keys)}


SUBMISSIONS = {
    "filings": {
        "recent": _cols([
            ("0000320193-26-000010", "2026-10-30", "2026-09-27", "10-K", "aapl-20260927.htm"),
            ("0000320193-26-000009", "2026-10-30", "", "8-K", "aapl-8k.htm"),
            ("0000320193-26-000008", "2026-08-01", "2026-06-28", "10-Q", "aapl-20260628.htm"),
            ("0000320193-26-000007", "2026-07-15", "", "4", "form4.xml"),       # wrong form
            ("0000320193-26-000006", "2026-07-01", "", "10-K/A", "amend.htm"),  # amendment
        ]),
        "files": [
            {"name": "CIK0000320193-submissions-001.json", "filingFrom": "2024-06-01", "filingTo": "2025-12-31"},
            {"name": "CIK0000320193-submissions-002.json", "filingFrom": "2010-01-01", "filingTo": "2015-12-31"},
        ],
    }
}
OLDER_PAGE = _cols([
    ("0000320193-25-000050", "2025-11-01", "2025-09-27", "10-K", "aapl-20250927.htm"),
    ("0000320193-24-000001", "2024-06-02", "2024-03-30", "10-Q", "too-old.htm"),  # before cutoff
])
BASE = "https://data.sec.gov/submissions/"
CUTOFF = date(2024, 11, 6)


def test_list_filings_filters_and_pages():
    client = FakeClient({
        BASE + "CIK0000320193.json": SUBMISSIONS,
        BASE + "CIK0000320193-submissions-001.json": OLDER_PAGE,
    })
    filings = list_filings(client, APPLE, ("10-K", "10-Q", "8-K"), CUTOFF)

    assert [f.accession for f in filings] == [
        "0000320193-26-000010",
        "0000320193-26-000009",
        "0000320193-26-000008",
        "0000320193-25-000050",
    ]
    # The 2010-2015 page is outside the window and must not be fetched.
    assert not any("002.json" in c for c in client.calls)
    assert filings[0].primary_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/aapl-20260927.htm"
    )
    assert filings[1].report_date is None


# ---------- 8-K exhibits ----------

INDEX_HTML = """
<table class="tableFile" summary="Document Format Files">
 <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
 <tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/320193/x/aapl-8k.htm">aapl-8k.htm</a></td><td>8-K</td><td>30000</td></tr>
 <tr><td>2</td><td>Press release</td><td><a href="/Archives/edgar/data/320193/x/ex991.htm">ex991.htm</a></td><td>EX-99.1</td><td>9000</td></tr>
 <tr><td>3</td><td>Logo</td><td><a href="/Archives/edgar/data/320193/x/logo.jpg">logo.jpg</a></td><td>EX-99.2</td><td>500</td></tr>
 <tr><td>4</td><td>Schema</td><td><a href="/Archives/edgar/data/320193/x/aapl.xsd">aapl.xsd</a></td><td>EX-101.SCH</td><td>500</td></tr>
</table>
"""


def test_exhibit_urls_picks_text_ex99_only():
    assert exhibit_urls(INDEX_HTML, "https://f") == ["https://f/ex991.htm"]


def test_exhibit_urls_without_table():
    assert exhibit_urls("<html>nothing</html>", "https://f") == []


# ---------- cleaning ----------

FILING_HTML = """
<html><head><title>10-K</title><style>.x{color:red}</style></head>
<body>
<div style="display:none"><ix:header><ix:hidden>dei:EntityCentralIndexKey 0000320193</ix:hidden></ix:header></div>
<p><span>Apple&#160;Inc.</span><span> designs smartphones.</span></p>
<div>Item 1A. <b>Risk Factors</b></div>
<table>
 <tr><td>Net sales</td><td>$</td><td><ix:nonFraction>391,035</ix:nonFraction></td></tr>
 <tr><td></td><td></td></tr>
</table>
<script>alert(1)</script>
</body></html>
"""


def test_html_to_text():
    text = html_to_text(FILING_HTML)
    assert "Apple Inc. designs smartphones." in text      # inline spans joined
    assert "Item 1A. Risk Factors" in text
    assert "Net sales | $ | 391,035" in text               # table row on one line
    assert "EntityCentralIndexKey" not in text             # hidden XBRL removed
    assert "alert" not in text and "color:red" not in text
    assert "\n\n\n" not in text


def test_html_to_text_plain_text():
    assert html_to_text("  plain\t\ttext \n\n\n\nnext ") == "plain text\n\nnext"


# ---------- full run ----------

def _run_fixture():
    folder = "https://www.sec.gov/Archives/edgar/data/320193/"
    sub = {"filings": {"recent": _cols([
        ("0000320193-26-000010", "2026-10-30", "2026-09-27", "10-K", "k.htm"),
        ("0000320193-26-000009", "2026-10-30", "", "8-K", "e.htm"),
        ("0000320193-26-000008", "2026-08-01", "2026-06-28", "10-Q", "q.htm"),
    ])}}
    return {
        BASE + "CIK0000320193.json": sub,
        folder + "000032019326000010/k.htm": "<p>Annual report text</p>",
        folder + "000032019326000009/e.htm": "<p>Item 2.02 Results of Operations</p>",
        folder + "000032019326000009/0000320193-26-000009-index.htm": INDEX_HTML,
        folder + "000032019326000009/ex991.htm": "<p>Apple reports record revenue</p>",
        # q.htm deliberately missing -> one error, run continues
    }


def test_ingest_saves_records_and_is_resumable(tmp_path):
    settings = Settings(user_agent="t t@t.com", form_types=("10-K", "10-Q", "8-K"), lookback_days=730)
    responses = _run_fixture()
    logs: list[str] = []

    stats = ingest(FakeClient(responses), [APPLE], settings, tmp_path, log=logs.append)
    assert stats["downloaded"] == 2 and stats["filing_errors"] == 1

    files = sorted(p.name for p in (tmp_path / "filings" / "AAPL").glob("*.json"))
    assert files == ["000032019326000009.json", "000032019326000010.json"]

    eight_k = json.loads((tmp_path / "filings" / "AAPL" / "000032019326000009.json").read_text())
    assert eight_k["form_type"] == "8-K"
    assert "Results of Operations" in eight_k["text"]
    assert "record revenue" in eight_k["text"]           # exhibit 99.1 appended
    assert eight_k["ticker"] == "AAPL" and eight_k["filing_date"] == "2026-10-30"
    assert eight_k["char_count"] == len(eight_k["text"])

    # Second run: the missing 10-Q now exists; saved filings are not re-downloaded.
    responses["https://www.sec.gov/Archives/edgar/data/320193/000032019326000008/q.htm"] = "<p>Quarterly</p>"
    client = FakeClient(responses)
    stats = ingest(client, [APPLE], settings, tmp_path, log=logs.append)
    assert stats["downloaded"] == 1 and stats["skipped_existing"] == 2
    assert not any(c.endswith("k.htm") for c in client.calls)
    assert sum(stats[k] for k in stats if k.startswith("form:")) == 3


def test_output_path_layout(tmp_path):
    filings = list_filings(
        FakeClient({BASE + "CIK0000320193.json": _run_fixture()[BASE + "CIK0000320193.json"]}),
        APPLE, ("10-K",), CUTOFF,
    )
    assert output_path(tmp_path, filings[0]) == tmp_path / "filings/AAPL/000032019326000010.json"


@pytest.mark.parametrize("ua", ["", "Your Name your.email@example.com", "noemail"])
def test_settings_reject_placeholder_user_agent(monkeypatch, ua):
    from edgar import config
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("SEC_USER_AGENT", ua)
    with pytest.raises(SystemExit):
        config.load_settings()
