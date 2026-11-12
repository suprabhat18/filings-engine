from __future__ import annotations

from datetime import date, timedelta

from edgar.config import Settings
from edgar.daily import run_daily
from test_ingestion import APPLE, FakeClient, _cols
from test_publish import FakeCatalog, FakeStore

BASE = "https://data.sec.gov/submissions/"
FOLDER = "https://www.sec.gov/Archives/edgar/data/320193/"


def _day(offset: int) -> str:
    return (date.today() - timedelta(days=offset)).isoformat()


def responses():
    sub = {"filings": {"recent": _cols([
        ("0000320193-26-000020", _day(1), "", "8-K", "new8k.htm"),
        ("0000320193-26-000019", _day(3), _day(40), "10-Q", "newq.htm"),
        ("0000320193-26-000010", _day(5), _day(60), "10-K", "oldk.htm"),   # already published
        ("0000320193-25-000001", _day(400), "", "10-K", "ancient.htm"),    # outside 14-day window
    ])}}
    return {
        BASE + "CIK0000320193.json": sub,
        FOLDER + "000032019326000020/new8k.htm": "<p>Item 2.02 Results</p>",
        FOLDER + "000032019326000020/0000320193-26-000020-index.htm": "<html></html>",
        FOLDER + "000032019326000019/newq.htm": "<p>Quarterly report</p>",
    }


def test_daily_publishes_only_new_recent_filings():
    settings = Settings(user_agent="t t@t.com", form_types=("10-K", "10-Q", "8-K"), lookback_days=14)
    store = FakeStore()
    catalog = FakeCatalog(existing=["320193-000032019326000010"])
    imported: list[str] = []
    client = FakeClient(responses())

    summary = run_daily(client, [APPLE], settings, store, catalog, imported.append, log=lambda _: None)

    assert summary["seen"] == 3            # the 400-day-old 10-K is outside the window
    assert summary["new"] == 2
    assert summary["new_by_form"] == {"8-K": 1, "10-Q": 1}
    assert imported == [summary["manifest_uri"]]
    assert not any("oldk.htm" in c or "ancient.htm" in c for c in client.calls)
    assert "320193-000032019326000020" in catalog.filings

    # Next day, nothing new: no downloads, no import.
    imported.clear()
    client2 = FakeClient(responses())
    summary2 = run_daily(client2, [APPLE], settings, store, catalog, imported.append, log=lambda _: None)
    assert summary2["new"] == 0 and imported == []
    assert len(client2.calls) == 1        # just the submissions lookup
