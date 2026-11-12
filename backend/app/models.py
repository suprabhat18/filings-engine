"""Request and response shapes for the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .config import FORM_TYPES


class User(BaseModel):
    uid: str
    email: str
    name: str = ""
    picture: str = ""


# ---------- search ----------

class SearchFilters(BaseModel):
    tickers: list[str] = Field(default_factory=list, max_length=20)
    form_types: list[str] = Field(default_factory=list)
    from_year: int | None = Field(default=None, ge=1994, le=2100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class QueryPlan(BaseModel):
    """What Gemini extracts from the user's question before searching."""

    language: str = Field(description="Language of the question, e.g. 'English', 'Spanish', 'Hindi'.")
    search_query: str = Field(description="A concise English keyword query for searching SEC filings.")
    tickers: list[str] = Field(default_factory=list, description="Stock tickers of companies the question names, e.g. AAPL. Empty if none.")
    form_types: list[str] = Field(default_factory=list, description=f"Form types the question asks about, from {list(FORM_TYPES)}. Empty if not specified.")
    from_year: int | None = Field(default=None, description="Earliest filing year if the question names a time period, else null.")


class Passage(BaseModel):
    """One retrieved chunk of a filing."""

    doc_id: str
    content: str
    title: str = ""
    section: str = ""  # e.g. "Item 1A. Risk Factors", from the chunk's headings
    filing_id: str = ""
    ticker: str = ""
    company_name: str = ""
    form_type: str = ""
    filing_date: str = ""
    source_url: str = ""


class Citation(Passage):
    n: int
    cited: bool = False


class AppliedFilters(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    form_types: list[str] = Field(default_factory=list)
    from_year: int | None = None
    inferred: bool = False  # True when filters came from the question, not the UI


class SearchResponse(BaseModel):
    query: str
    language: str
    search_query: str
    filters: AppliedFilters
    answer: str
    citations: list[Citation]
    history_id: str | None = None


# ---------- user data ----------

class Company(BaseModel):
    ticker: str
    name: str
    cik: int | None = None


class WatchlistItem(BaseModel):
    ticker: str
    name: str = ""
    added_at: str = ""


class Filing(BaseModel):
    filing_id: str
    ticker: str
    company_name: str
    form_type: str
    filing_date: str
    source_url: str
    index_url: str = ""


class BookmarkIn(BaseModel):
    kind: Literal["answer", "filing"]
    title: str = Field(max_length=300)
    query: str | None = Field(default=None, max_length=500)
    answer: str | None = Field(default=None, max_length=20_000)
    citations: list[Citation] = Field(default_factory=list, max_length=20)
    filing: Filing | None = None
    note: str | None = Field(default=None, max_length=1000)


class Bookmark(BookmarkIn):
    id: str
    created_at: str


class HistoryEntry(BaseModel):
    id: str
    query: str
    language: str
    filters: AppliedFilters
    answer_preview: str
    created_at: str


class Me(BaseModel):
    user: User
    searches_today: int
    daily_quota: int
