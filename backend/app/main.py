"""FastAPI app for the Financial Filings Research & Analysis Engine.

Run locally:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import TokenVerifier, current_user
from .config import Settings, get_settings
from .errors import FREE_LIMIT, FREE_USED, GLOBAL_QUOTA, USER_QUOTA, ApiError
from .llm import LLM
from .models import (
    Bookmark,
    BookmarkIn,
    Company,
    Filing,
    FreeSearchRequest,
    HistoryEntry,
    Me,
    PublicStats,
    SearchFilters,
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

_VISITOR_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
STATS_CACHE_SECONDS = 600


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
    stats_cache: dict[str, object] = {}

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

    def answer_question(s: Services, query: str, filters: SearchFilters, who: str):
        """Plan, retrieve and answer. Shared by signed-in and free searches."""
        started = time.monotonic()
        known = {c["ticker"] for c in s.store.list_companies()}
        try:
            result = run_search(query, filters, s.llm, s.retriever, known, s.settings.results_per_query)
        except Exception:
            log.exception("search failed")
            raise ApiError(status.HTTP_502_BAD_GATEWAY, "search_unavailable",
                           "Search is temporarily unavailable.")
        log.info("search who=%s ms=%d results=%d", who, (time.monotonic() - started) * 1000, len(result[3]))
        return result

    @app.post("/search", response_model=SearchResponse)
    def search(body: SearchRequest, request: Request, user: User = Depends(signed_in)) -> SearchResponse:
        s = svc(request)
        retry_after = s.limiter.hit(user.uid)
        if retry_after:
            wait = int(retry_after) + 1
            raise ApiError(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited",
                           f"Too many searches. Try again in {wait} seconds.",
                           headers={"Retry-After": str(wait)})
        quota = s.store.consume_quota(
            user.uid, today(), s.settings.daily_user_quota, s.settings.daily_global_quota
        )
        if not quota.allowed:
            raise ApiError(status.HTTP_429_TOO_MANY_REQUESTS, quota.reason,
                           USER_QUOTA if quota.reason == "user_quota" else GLOBAL_QUOTA)

        plan, filters, answer, citations = answer_question(s, body.query, body.filters, f"uid:{user.uid}")
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
            raise ApiError(status.HTTP_404_NOT_FOUND, "not_in_index", f"{ticker} is not in the index")
        if len(s.store.get_watchlist(user.uid)) >= 30:
            raise ApiError(status.HTTP_400_BAD_REQUEST, "watchlist_full", "Watchlists hold up to 30 companies")
        return s.store.add_watch(user.uid, ticker, company["name"])

    @app.delete("/watchlist/{ticker}", status_code=204)
    def remove_watch(ticker: str, request: Request, user: User = Depends(signed_in)):
        if not svc(request).store.remove_watch(user.uid, ticker.upper()):
            raise ApiError(status.HTTP_404_NOT_FOUND, "not_on_watchlist", "Not on your watchlist")

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
            raise ApiError(status.HTTP_400_BAD_REQUEST, "bookmark_limit", "Bookmark limit (200) reached")
        if body.kind == "filing" and body.filing is None:
            raise HTTPException(422, "A filing bookmark needs `filing`")
        if body.kind == "answer" and not body.answer:
            raise HTTPException(422, "An answer bookmark needs `answer`")
        return s.store.add_bookmark(user.uid, body.model_dump())

    @app.delete("/bookmarks/{bookmark_id}", status_code=204)
    def delete_bookmark(bookmark_id: str, request: Request, user: User = Depends(signed_in)):
        if not svc(request).store.delete_bookmark(user.uid, bookmark_id):
            raise ApiError(status.HTTP_404_NOT_FOUND, "bookmark_not_found", "Bookmark not found")

    # ------------------------------------------------------------ history

    @app.get("/history", response_model=list[HistoryEntry])
    def history(request: Request, limit: int = 50, user: User = Depends(signed_in)):
        return svc(request).store.list_history(user.uid, min(max(limit, 1), 200))

    @app.delete("/history")
    def clear_history(request: Request, user: User = Depends(signed_in)) -> dict:
        return {"deleted": svc(request).store.clear_history(user.uid)}

    # ------------------------------------------------------------ public (no sign-in)

    @app.get("/public/stats", response_model=PublicStats)
    def public_stats(request: Request) -> PublicStats:
        """Live numbers for the homepage, cached so visits don't hit Firestore."""
        s = svc(request)
        cached = stats_cache.get("value")
        if cached and time.monotonic() - stats_cache["at"] < STATS_CACHE_SECONDS:
            return cached
        value = PublicStats(
            filings=s.store.count_filings(),
            companies=len(s.store.list_companies()),
            updated_at=s.store.index_updated_at(),
        )
        stats_cache.update(value=value, at=time.monotonic())
        return value

    @app.post("/public/try", response_model=SearchResponse)
    def free_search(body: FreeSearchRequest, request: Request) -> SearchResponse:
        """One free question from the homepage, without signing in.

        Only the website's server may call this (shared secret), because it is the one
        that knows the visitor's browser id and network address. Limits: one per
        browser and a few per network per day, plus a daily total for everyone.
        Nothing is saved to any history.
        """
        s = svc(request)
        cfg = s.settings
        sent = request.headers.get("x-proxy-secret", "")
        if not cfg.proxy_secret or not hmac.compare_digest(sent, cfg.proxy_secret):
            raise ApiError(status.HTTP_403_FORBIDDEN, "free_unavailable", "Free questions are not available.")
        query = body.query.strip()
        if len(query) > cfg.free_max_chars:
            raise ApiError(422, "free_too_long",
                           f"Free questions can be up to {cfg.free_max_chars} characters.")
        visitor = request.headers.get("x-visitor-id", "")
        network = request.headers.get("x-client-ip", "")
        if not _VISITOR_ID.match(visitor) or not network:
            raise ApiError(400, "free_unavailable", "Free questions are not available.")
        if cfg.turnstile_secret and not verify_turnstile(cfg.turnstile_secret, body.turnstile_token, network):
            raise ApiError(status.HTTP_403_FORBIDDEN, "bot_check_failed",
                           "The automatic check didn't pass. Please reload the page and try again.")

        day = today()
        # The network address is only kept as a one-way hash, reset daily.
        net_key = "n_" + hashlib.sha256(f"{day}|{network}".encode()).hexdigest()[:32]
        reason = s.store.consume_free(day, "v_" + visitor, net_key, cfg.free_per_visitor,
                                      cfg.free_per_network, cfg.free_daily_total)
        if reason:
            raise ApiError(status.HTTP_429_TOO_MANY_REQUESTS, reason,
                           FREE_USED if reason == "free_used" else FREE_LIMIT)

        plan, filters, answer, citations = answer_question(s, query, SearchFilters(), "free")
        return SearchResponse(
            query=query,
            language=plan.language,
            search_query=plan.search_query,
            filters=filters,
            answer=answer,
            citations=citations,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        body = {"detail": exc.detail}
        if getattr(exc, "code", None):
            body["code"] = exc.code
        return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover
        log.exception("unhandled error")
        return JSONResponse({"detail": "Internal error"}, status_code=500)

    return app



def verify_turnstile(secret: str, token: str, ip: str) -> bool:
    """Check a Cloudflare Turnstile token (the free, invisible bot check)."""
    if not token:
        return False
    import requests

    try:
        r = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": ip},
            timeout=10,
        )
        return bool(r.json().get("success"))
    except Exception:  # network trouble: fail closed, the visitor can retry
        log.exception("turnstile check failed")
        return False


app = create_app()  # uvicorn entry point: app.main:app
