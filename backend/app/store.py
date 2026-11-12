"""User data: watchlists, bookmarks, search history and usage quotas.

Firestore layout
    users/{uid}                      profile + today's search count
    users/{uid}/watchlist/{ticker}   companies the user tracks
    users/{uid}/bookmarks/{id}       saved answers and filings
    users/{uid}/history/{id}         past searches
    usage/{YYYY-MM-DD}               searches across all users that day
    companies/{ticker}, filings/{id} written by the ingestion job (read-only here)
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass
class QuotaResult:
    allowed: bool
    used: int
    reason: str = ""


class Store(Protocol):
    def upsert_user(self, uid: str, email: str, name: str) -> None: ...
    def consume_quota(self, uid: str, day: str, user_limit: int, global_limit: int) -> QuotaResult: ...
    def searches_on(self, uid: str, day: str) -> int: ...

    def list_companies(self) -> list[dict[str, Any]]: ...
    def index_updated_at(self) -> str | None: ...
    def recent_filings(self, tickers: list[str], limit: int) -> list[dict[str, Any]]: ...

    def get_watchlist(self, uid: str) -> list[dict[str, Any]]: ...
    def add_watch(self, uid: str, ticker: str, name: str) -> dict[str, Any]: ...
    def remove_watch(self, uid: str, ticker: str) -> bool: ...

    def add_bookmark(self, uid: str, data: dict[str, Any]) -> dict[str, Any]: ...
    def list_bookmarks(self, uid: str) -> list[dict[str, Any]]: ...
    def delete_bookmark(self, uid: str, bookmark_id: str) -> bool: ...

    def add_history(self, uid: str, data: dict[str, Any]) -> str: ...
    def list_history(self, uid: str, limit: int) -> list[dict[str, Any]]: ...
    def clear_history(self, uid: str) -> int: ...


# ---------------------------------------------------------------- in memory

class MemoryStore:
    """Same behaviour as FirestoreStore, kept in dicts. Used by tests and local demos."""

    def __init__(self, companies: list[dict] | None = None, filings: list[dict] | None = None):
        self.users: dict[str, dict] = {}
        self.usage: dict[str, int] = {}
        self.companies = list(companies or [])
        self.filings = list(filings or [])
        self.runs: list[dict] = []
        self.watch: dict[str, dict[str, dict]] = {}
        self.bookmarks: dict[str, dict[str, dict]] = {}
        self.history: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def upsert_user(self, uid, email, name):
        self.users.setdefault(uid, {"created_at": now_iso()}).update(
            {"email": email, "name": name, "last_seen": now_iso()}
        )

    def consume_quota(self, uid, day, user_limit, global_limit):
        with self._lock:
            used = self.searches_on(uid, day)
            if used >= user_limit:
                return QuotaResult(False, used, "daily limit reached for your account")
            if self.usage.get(day, 0) >= global_limit:
                return QuotaResult(False, used, "the service's daily limit has been reached")
            self.users.setdefault(uid, {})["usage"] = {"day": day, "count": used + 1}
            self.usage[day] = self.usage.get(day, 0) + 1
            return QuotaResult(True, used + 1)

    def searches_on(self, uid, day):
        usage = self.users.get(uid, {}).get("usage", {})
        return usage.get("count", 0) if usage.get("day") == day else 0

    def list_companies(self):
        return sorted(self.companies, key=lambda c: c["ticker"])

    def index_updated_at(self):
        done = [r["finished_at"] for r in self.runs if r.get("finished_at")]
        return max(done) if done else None

    def recent_filings(self, tickers, limit):
        rows = [f for f in self.filings if f["ticker"] in set(tickers)]
        return sorted(rows, key=lambda f: f["filing_date"], reverse=True)[:limit]

    def get_watchlist(self, uid):
        return sorted(self.watch.get(uid, {}).values(), key=lambda w: w["ticker"])

    def add_watch(self, uid, ticker, name):
        item = {"ticker": ticker, "name": name, "added_at": now_iso()}
        self.watch.setdefault(uid, {})[ticker] = item
        return item

    def remove_watch(self, uid, ticker):
        return self.watch.get(uid, {}).pop(ticker, None) is not None

    def add_bookmark(self, uid, data):
        item = {**data, "id": uuid.uuid4().hex, "created_at": now_iso()}
        self.bookmarks.setdefault(uid, {})[item["id"]] = item
        return item

    def list_bookmarks(self, uid):
        return sorted(self.bookmarks.get(uid, {}).values(), key=lambda b: b["created_at"], reverse=True)

    def delete_bookmark(self, uid, bookmark_id):
        return self.bookmarks.get(uid, {}).pop(bookmark_id, None) is not None

    def add_history(self, uid, data):
        hid = uuid.uuid4().hex
        self.history.setdefault(uid, {})[hid] = {**data, "id": hid, "created_at": data.get("created_at") or now_iso()}
        return hid

    def list_history(self, uid, limit):
        rows = sorted(self.history.get(uid, {}).values(), key=lambda h: h["created_at"], reverse=True)
        return rows[:limit]

    def clear_history(self, uid):
        return len(self.history.pop(uid, {}))


# ---------------------------------------------------------------- Firestore

class FirestoreStore:
    COMPANY_CACHE_SECONDS = 600

    def __init__(self, project: str, database: str = "(default)") -> None:
        from google.cloud import firestore

        self._fs = firestore
        self.db = firestore.Client(project=project, database=database)
        self._companies: tuple[float, list[dict]] | None = None

    def _user(self, uid: str):
        return self.db.collection("users").document(uid)

    def upsert_user(self, uid, email, name):
        self._user(uid).set({"email": email, "name": name, "last_seen": now_iso()}, merge=True)

    def consume_quota(self, uid, day, user_limit, global_limit):
        user_ref = self._user(uid)
        usage_ref = self.db.collection("usage").document(day)

        @self._fs.transactional
        def txn(transaction) -> QuotaResult:
            user = user_ref.get(transaction=transaction).to_dict() or {}
            usage = user.get("usage") or {}
            used = usage.get("count", 0) if usage.get("day") == day else 0
            if used >= user_limit:
                return QuotaResult(False, used, "daily limit reached for your account")
            total = (usage_ref.get(transaction=transaction).to_dict() or {}).get("count", 0)
            if total >= global_limit:
                return QuotaResult(False, used, "the service's daily limit has been reached")
            transaction.set(user_ref, {"usage": {"day": day, "count": used + 1}}, merge=True)
            transaction.set(usage_ref, {"count": total + 1}, merge=True)
            return QuotaResult(True, used + 1)

        return txn(self.db.transaction())

    def searches_on(self, uid, day):
        usage = (self._user(uid).get().to_dict() or {}).get("usage") or {}
        return usage.get("count", 0) if usage.get("day") == day else 0

    def list_companies(self):
        if self._companies and time.monotonic() - self._companies[0] < self.COMPANY_CACHE_SECONDS:
            return self._companies[1]
        rows = sorted((d.to_dict() for d in self.db.collection("companies").stream()),
                      key=lambda c: c["ticker"])
        self._companies = (time.monotonic(), rows)
        return rows

    def index_updated_at(self):
        """Finish time of the latest ingestion run (written by ingestion/edgar/update.py)."""
        query = (
            self.db.collection("ingestion_runs")
            .order_by("finished_at", direction=self._fs.Query.DESCENDING)
            .limit(1)
        )
        for snap in query.stream():
            return snap.to_dict().get("finished_at")
        return None

    def recent_filings(self, tickers, limit):
        if not tickers:
            return []
        # Needs the composite index (ticker ASC, filing_date DESC); see firestore.indexes.json.
        query = (
            self.db.collection("filings")
            .where(filter=self._fs.FieldFilter("ticker", "in", tickers[:30]))
            .order_by("filing_date", direction=self._fs.Query.DESCENDING)
            .limit(limit)
        )
        return [d.to_dict() for d in query.stream()]

    def get_watchlist(self, uid):
        return [d.to_dict() for d in self._user(uid).collection("watchlist").order_by("ticker").stream()]

    def add_watch(self, uid, ticker, name):
        item = {"ticker": ticker, "name": name, "added_at": now_iso()}
        self._user(uid).collection("watchlist").document(ticker).set(item)
        return item

    def remove_watch(self, uid, ticker):
        ref = self._user(uid).collection("watchlist").document(ticker)
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def add_bookmark(self, uid, data):
        ref = self._user(uid).collection("bookmarks").document()
        item = {**data, "id": ref.id, "created_at": now_iso()}
        ref.set(item)
        return item

    def list_bookmarks(self, uid):
        col = self._user(uid).collection("bookmarks")
        return [d.to_dict() for d in col.order_by("created_at", direction=self._fs.Query.DESCENDING).stream()]

    def delete_bookmark(self, uid, bookmark_id):
        ref = self._user(uid).collection("bookmarks").document(bookmark_id)
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def add_history(self, uid, data):
        ref = self._user(uid).collection("history").document()
        ref.set({**data, "id": ref.id, "created_at": data.get("created_at") or now_iso()})
        return ref.id

    def list_history(self, uid, limit):
        col = self._user(uid).collection("history")
        query = col.order_by("created_at", direction=self._fs.Query.DESCENDING).limit(limit)
        return [d.to_dict() for d in query.stream()]

    def clear_history(self, uid):
        col = self._user(uid).collection("history")
        deleted = 0
        while True:
            docs = list(col.limit(400).stream())
            if not docs:
                return deleted
            batch = self.db.batch()
            for d in docs:
                batch.delete(d.reference)
            batch.commit()
            deleted += len(docs)
