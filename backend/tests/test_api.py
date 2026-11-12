from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import Services, create_app
from app.models import AppliedFilters, Passage, QueryPlan, User
from app.ratelimit import SlidingWindowLimiter
from app.store import MemoryStore

COMPANIES = [
    {"ticker": "AAPL", "name": "Apple Inc.", "cik": 320193},
    {"ticker": "MSFT", "name": "Microsoft Corp", "cik": 789019},
]
FILINGS = [
    {"filing_id": "320193-1", "ticker": "AAPL", "company_name": "Apple Inc.", "form_type": "10-K",
     "filing_date": "2026-10-30", "source_url": "https://sec/a", "index_url": "https://sec/ai"},
    {"filing_id": "320193-2", "ticker": "AAPL", "company_name": "Apple Inc.", "form_type": "8-K",
     "filing_date": "2026-11-02", "source_url": "https://sec/b", "index_url": "https://sec/bi"},
    {"filing_id": "789019-1", "ticker": "MSFT", "company_name": "Microsoft Corp", "form_type": "10-Q",
     "filing_date": "2026-10-25", "source_url": "https://sec/c", "index_url": "https://sec/ci"},
]


def passage(n: int, ticker="AAPL") -> Passage:
    return Passage(doc_id=f"d{n}", content=f"Excerpt {n} about supply chain.", title=f"{ticker} 10-K",
                   ticker=ticker, company_name="Apple Inc.", form_type="10-K",
                   filing_date="2026-10-30", source_url=f"https://sec/{n}", filing_id=f"f{n}")


class FakeLLM:
    def __init__(self, plan: QueryPlan | None = None, answer: str = "Apple cites suppliers [1][3]."):
        self.plan_value = plan or QueryPlan(language="English", search_query="supply chain risk")
        self.answer_value = answer
        self.answer_calls: list[tuple] = []

    def plan(self, question):
        return self.plan_value

    def answer(self, question, language, passages):
        self.answer_calls.append((question, language, passages))
        return self.answer_value


class FakeRetriever:
    def __init__(self, results=None, empty_when_filtered=False):
        self.results = results if results is not None else [passage(1), passage(2), passage(3)]
        self.empty_when_filtered = empty_when_filtered
        self.calls: list[tuple[str, AppliedFilters]] = []

    def retrieve(self, query, filters, k):
        self.calls.append((query, filters))
        if self.empty_when_filtered and (filters.tickers or filters.form_types):
            return []
        return self.results[:k]


def verify(token: str) -> User:
    if not token.startswith("good-"):
        raise HTTPException(401, "Invalid or expired sign-in")
    uid = token.removeprefix("good-")
    return User(uid=uid, email=f"{uid}@example.com", name=uid)


def make_client(llm=None, retriever=None, **settings_kw):
    settings = Settings(_env_file=None, gcp_project_id="p", **settings_kw)
    services = Services(
        settings=settings,
        store=MemoryStore(COMPANIES, FILINGS),
        retriever=retriever or FakeRetriever(),
        llm=llm or FakeLLM(),
        verify_token=verify,
        limiter=SlidingWindowLimiter(settings.rate_limit_per_minute, 60),
    )
    client = TestClient(create_app(services))
    client.services = services
    return client


AUTH = {"Authorization": "Bearer good-alice"}


# ---------------------------------------------------------------- auth

def test_health_is_public():
    assert make_client().get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer bad"}, {"Authorization": "Basic x"}])
def test_endpoints_require_valid_sign_in(headers):
    client = make_client()
    assert client.post("/search", json={"query": "risk"}, headers=headers).status_code == 401
    assert client.get("/bookmarks", headers=headers).status_code == 401


def test_me_reports_quota():
    client = make_client(daily_user_quota=5)
    client.post("/search", json={"query": "supply chain"}, headers=AUTH)
    me = client.get("/me", headers=AUTH).json()
    assert me["user"]["email"] == "alice@example.com"
    assert me["searches_today"] == 1 and me["daily_quota"] == 5


# ---------------------------------------------------------------- search

def test_search_returns_answer_with_citations_and_history():
    client = make_client()
    r = client.post("/search", json={"query": "What supply chain risks does Apple face?"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Apple cites suppliers [1][3]."
    assert [c["n"] for c in body["citations"]] == [1, 2, 3]
    assert [c["cited"] for c in body["citations"]] == [True, False, True]
    assert body["citations"][0]["source_url"] == "https://sec/1"

    history = client.get("/history", headers=AUTH).json()
    assert history[0]["id"] == body["history_id"]
    assert history[0]["query"].startswith("What supply chain")


def test_multilingual_question_searches_in_english_and_answers_in_language():
    plan = QueryPlan(language="Spanish", search_query="Apple risk factors", tickers=["aapl"], form_types=["10-K"])
    llm, retriever = FakeLLM(plan=plan, answer="Apple menciona riesgos [1]."), FakeRetriever()
    client = make_client(llm=llm, retriever=retriever)
    body = client.post("/search", json={"query": "¿Qué riesgos menciona Apple en su 10-K?"}, headers=AUTH).json()

    query, filters = retriever.calls[0]
    assert query == "Apple risk factors"
    assert filters.tickers == ["AAPL"] and filters.form_types == ["10-K"]
    assert body["filters"]["inferred"] is True
    assert llm.answer_calls[0][1] == "Spanish"
    assert body["language"] == "Spanish"


def test_ui_filters_override_inferred_ones():
    plan = QueryPlan(language="English", search_query="revenue", tickers=["AAPL"])
    retriever = FakeRetriever()
    client = make_client(llm=FakeLLM(plan=plan), retriever=retriever)
    client.post("/search", json={"query": "revenue", "filters": {"tickers": ["msft"], "form_types": ["10-Q", "S-1"]}},
                headers=AUTH)
    _, filters = retriever.calls[0]
    assert filters.tickers == ["MSFT"] and filters.form_types == ["10-Q"]  # S-1 dropped
    assert filters.inferred is False


def test_unknown_inferred_ticker_is_ignored():
    plan = QueryPlan(language="English", search_query="x", tickers=["ZZZZ", "AAPL"])
    retriever = FakeRetriever()
    make_client(llm=FakeLLM(plan=plan), retriever=retriever).post("/search", json={"query": "xx"}, headers=AUTH)
    assert retriever.calls[0][1].tickers == ["AAPL"]


def test_inferred_filters_dropped_when_they_return_nothing():
    plan = QueryPlan(language="English", search_query="cloud revenue", tickers=["MSFT"])
    retriever = FakeRetriever(empty_when_filtered=True)
    body = make_client(llm=FakeLLM(plan=plan), retriever=retriever).post(
        "/search", json={"query": "cloud revenue"}, headers=AUTH).json()
    assert len(retriever.calls) == 2
    assert retriever.calls[1][1].tickers == []
    assert body["filters"]["tickers"] == [] and len(body["citations"]) == 3


def test_no_results_does_not_call_gemini_for_english():
    llm = FakeLLM()
    body = make_client(llm=llm, retriever=FakeRetriever(results=[])).post(
        "/search", json={"query": "nothing"}, headers=AUTH).json()
    assert body["citations"] == [] and "couldn't find" in body["answer"]
    assert llm.answer_calls == []


def test_search_failure_returns_502():
    class Broken(FakeRetriever):
        def retrieve(self, *a):
            raise RuntimeError("vertex down")
    r = make_client(retriever=Broken()).post("/search", json={"query": "risk"}, headers=AUTH)
    assert r.status_code == 502


def test_query_validation():
    client = make_client()
    assert client.post("/search", json={"query": "x"}, headers=AUTH).status_code == 422
    assert client.post("/search", json={"query": "x" * 501}, headers=AUTH).status_code == 422


# ---------------------------------------------------------------- limits

def test_per_minute_rate_limit():
    client = make_client(rate_limit_per_minute=2)
    codes = [client.post("/search", json={"query": "risk"}, headers=AUTH).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    # Another user has their own window.
    assert client.post("/search", json={"query": "risk"}, headers={"Authorization": "Bearer good-bob"}).status_code == 200


def test_daily_user_and_global_quota():
    client = make_client(daily_user_quota=1, daily_global_quota=2)
    bob = {"Authorization": "Bearer good-bob"}
    carol = {"Authorization": "Bearer good-carol"}
    assert client.post("/search", json={"query": "risk"}, headers=AUTH).status_code == 200
    r = client.post("/search", json={"query": "risk"}, headers=AUTH)
    assert r.status_code == 429 and "your account" in r.json()["detail"]
    assert client.post("/search", json={"query": "risk"}, headers=bob).status_code == 200
    r = client.post("/search", json={"query": "risk"}, headers=carol)
    assert r.status_code == 429 and "service" in r.json()["detail"]


def test_sliding_window_frees_slots_over_time():
    t = [0.0]
    limiter = SlidingWindowLimiter(2, 60, clock=lambda: t[0])
    assert limiter.hit("u") == 0 and limiter.hit("u") == 0
    assert limiter.hit("u") == pytest.approx(60)
    t[0] = 60.0
    assert limiter.hit("u") == 0


# ---------------------------------------------------------------- watchlist

def test_watchlist_flow_and_recent_filings():
    client = make_client()
    assert client.get("/companies", headers=AUTH).json()[0]["ticker"] == "AAPL"
    assert client.put("/watchlist/aapl", headers=AUTH).json()["name"] == "Apple Inc."
    assert client.put("/watchlist/ZZZZ", headers=AUTH).status_code == 404
    assert [w["ticker"] for w in client.get("/watchlist", headers=AUTH).json()] == ["AAPL"]

    filings = client.get("/watchlist/filings", headers=AUTH).json()
    assert [f["filing_date"] for f in filings] == ["2026-11-02", "2026-10-30"]  # newest first, AAPL only

    assert client.delete("/watchlist/AAPL", headers=AUTH).status_code == 204
    assert client.delete("/watchlist/AAPL", headers=AUTH).status_code == 404
    assert client.get("/watchlist/filings", headers=AUTH).json() == []


def test_watchlists_are_per_user():
    client = make_client()
    client.put("/watchlist/MSFT", headers=AUTH)
    assert client.get("/watchlist", headers={"Authorization": "Bearer good-bob"}).json() == []


# ---------------------------------------------------------------- bookmarks & history

def test_bookmarks_flow():
    client = make_client()
    search = client.post("/search", json={"query": "supply chain"}, headers=AUTH).json()
    r = client.post("/bookmarks", headers=AUTH, json={
        "kind": "answer", "title": "Apple supply chain", "query": search["query"],
        "answer": search["answer"], "citations": search["citations"][:2],
    })
    assert r.status_code == 201
    bm = r.json()
    r2 = client.post("/bookmarks", headers=AUTH, json={
        "kind": "filing", "title": "Apple 10-K", "filing": {k: FILINGS[0][k] for k in
            ("filing_id", "ticker", "company_name", "form_type", "filing_date", "source_url", "index_url")},
    })
    assert r2.status_code == 201
    assert len(client.get("/bookmarks", headers=AUTH).json()) == 2

    # Incomplete bookmarks are rejected.
    assert client.post("/bookmarks", headers=AUTH, json={"kind": "filing", "title": "x"}).status_code == 422

    assert client.delete(f"/bookmarks/{bm['id']}", headers=AUTH).status_code == 204
    assert client.delete(f"/bookmarks/{bm['id']}", headers=AUTH).status_code == 404
    # Another user can't see or delete them.
    assert client.get("/bookmarks", headers={"Authorization": "Bearer good-bob"}).json() == []


def test_clear_history():
    client = make_client()
    for _ in range(3):
        client.post("/search", json={"query": "supply chain"}, headers=AUTH)
    assert len(client.get("/history", headers=AUTH).json()) == 3
    assert client.delete("/history", headers=AUTH).json() == {"deleted": 3}
    assert client.get("/history", headers=AUTH).json() == []
