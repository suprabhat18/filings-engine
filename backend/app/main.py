"""FastAPI app for the Financial Filings Research & Analysis Engine.

Run locally:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import TokenVerifier, current_user
from .config import Settings, get_settings
from .llm import LLM
from .models import (
    Bookmark,
    BookmarkIn,
    Company,
    Filing,
    HistoryEntry,
    Me,
    SearchRequest,
    SearchResponse,
    User,
    WatchlistItem,
)
from .rag import run_search
from .ratelimit import SlidingWindowLimiter
from .retrieval import Retriever, valid_ticker
from .store import Store, today

log = logging.getLogger("filings")


@dataclass
class Services:
    settings: Settings
    store: Store
    retriever: Retriever
    llm: LLM
    verify_token: TokenVerifier
    limiter: SlidingWindowLimiter


def build_services(settings: Settings) -> Services:
    from .auth import GoogleTokenVerifier
    from .llm import GeminiLLM
    from .retrieval import VertexRetriever
    from .store import FirestoreStore

    return Services(
        settings=settings,
        store=FirestoreStore(settings.gcp_project_id),
        retriever=VertexRetriever(settings.serving_config, settings.gcp_location),
        llm=GeminiLLM(settings.gcp_project_id, settings.gemini_location, settings.gemini_model),
        verify_token=GoogleTokenVerifier(settings.google_oauth_client_id, settings.allowed_email_set),
        limiter=SlidingWindowLimiter(settings.rate_limit_per_minute, 60),
    )


def create_app(services: Services | None = None) -> FastAPI:
    settings = services.settings if services else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Google clients are created once at startup (tests pass in fakes instead).
        if getattr(app.state, "services", None) is None:
            app.state.services = build_services(settings)
        yield

    app = FastAPI(title="Financial Filings Research API", version="1.0.0", lifespan=lifespan)
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def svc(request: Request) -> Services:
        return request.app.state.services

    def signed_in(request: Request, user: User = Depends(current_user)) -> User:
        svc(request).store.upsert_user(user.uid, user.email, user.name)
        return user

    # ------------------------------------------------------------ health

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/me", response_model=Me)
    def me(request: Request, user: User = Depends(signed_in)) -> Me:
        s = svc(request)
        return Me(
            user=user,
            searches_today=s.store.searches_on(user.uid, today()),
            daily_quota=s.settings.daily_user_quota,
            index_updated_at=s.store.index_updated_at(),
        )

    # ------------------------------------------------------------ search

    @app.post("/search", response_model=SearchResponse)
    def search(body: SearchRequest, request: Request, user: User = Depends(signed_in)) -> SearchResponse:
        s = svc(request)
        retry_after = s.limiter.hit(user.uid)
        if retry_after:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Too many searches. Try again in {int(retry_after) + 1} seconds.",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        quota = s.store.consume_quota(
            user.uid, today(), s.settings.daily_user_quota, s.settings.daily_global_quota
        )
        if not quota.allowed:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Search limit: {quota.reason}.")

        started = time.monotonic()
        known = {c["ticker"] for c in s.store.list_companies()}
        try:
            plan, filters, answer, citations = run_search(
                body.query, body.filters, s.llm, s.retriever, known, s.settings.results_per_query
            )
        except Exception:
            log.exception("search failed")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Search is temporarily unavailable.")
        log.info("search uid=%s ms=%d results=%d", user.uid, (time.monotonic() - started) * 1000, len(citations))

        history_id = s.store.add_history(user.uid, {
            "query": body.query,
            "language": plan.language,
            "filters": filters.model_dump(),
            "answer_preview": answer[:280],
        })
        return SearchResponse(
            query=body.query,
            language=plan.language,
            search_query=plan.search_query,
            filters=filters,
            answer=answer,
            citations=citations,
            history_id=history_id,
        )

    # ------------------------------------------------------------ companies & watchlist

    @app.get("/companies", response_model=list[Company])
    def companies(request: Request, user: User = Depends(signed_in)) -> list[Company]:
        return [Company(**c) for c in svc(request).store.list_companies()]

    @app.get("/watchlist", response_model=list[WatchlistItem])
    def get_watchlist(request: Request, user: User = Depends(signed_in)):
        return svc(request).store.get_watchlist(user.uid)

    @app.put("/watchlist/{ticker}", response_model=WatchlistItem)
    def add_watch(ticker: str, request: Request, user: User = Depends(signed_in)):
        s = svc(request)
        ticker = ticker.upper()
        company = next((c for c in s.store.list_companies() if c["ticker"] == ticker), None)
        if not valid_ticker(ticker) or company is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{ticker} is not in the index")
        if len(s.store.get_watchlist(user.uid)) >= 30:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Watchlists hold up to 30 companies")
        return s.store.add_watch(user.uid, ticker, company["name"])

    @app.delete("/watchlist/{ticker}", status_code=204)
    def remove_watch(ticker: str, request: Request, user: User = Depends(signed_in)):
        if not svc(request).store.remove_watch(user.uid, ticker.upper()):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on your watchlist")

    @app.get("/watchlist/filings", response_model=list[Filing])
    def watchlist_filings(request: Request, limit: int = 25, user: User = Depends(signed_in)):
        s = svc(request)
        tickers = [w["ticker"] for w in s.store.get_watchlist(user.uid)]
        rows = s.store.recent_filings(tickers, min(max(limit, 1), 100))
        return [Filing(**{k: r.get(k, "") for k in Filing.model_fields}) for r in rows]

    # ------------------------------------------------------------ bookmarks

    @app.get("/bookmarks", response_model=list[Bookmark])
    def list_bookmarks(request: Request, user: User = Depends(signed_in)):
        return svc(request).store.list_bookmarks(user.uid)

    @app.post("/bookmarks", response_model=Bookmark, status_code=201)
    def add_bookmark(body: BookmarkIn, request: Request, user: User = Depends(signed_in)):
        s = svc(request)
        if len(s.store.list_bookmarks(user.uid)) >= 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bookmark limit (200) reached")
        if body.kind == "filing" and body.filing is None:
            raise HTTPException(422, "A filing bookmark needs `filing`")
        if body.kind == "answer" and not body.answer:
            raise HTTPException(422, "An answer bookmark needs `answer`")
        return s.store.add_bookmark(user.uid, body.model_dump())

    @app.delete("/bookmarks/{bookmark_id}", status_code=204)
    def delete_bookmark(bookmark_id: str, request: Request, user: User = Depends(signed_in)):
        if not svc(request).store.delete_bookmark(user.uid, bookmark_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bookmark not found")

    # ------------------------------------------------------------ history

    @app.get("/history", response_model=list[HistoryEntry])
    def history(request: Request, limit: int = 50, user: User = Depends(signed_in)):
        return svc(request).store.list_history(user.uid, min(max(limit, 1), 200))

    @app.delete("/history")
    def clear_history(request: Request, user: User = Depends(signed_in)) -> dict:
        return {"deleted": svc(request).store.clear_history(user.uid)}

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover
        log.exception("unhandled error")
        return JSONResponse({"detail": "Internal error"}, status_code=500)

    return app


app = create_app()  # uvicorn entry point: app.main:app
