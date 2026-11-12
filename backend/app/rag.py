"""The search pipeline: plan the query, retrieve chunks, generate a cited answer."""

from __future__ import annotations

import re

from .config import FORM_TYPES
from .llm import LLM
from .models import AppliedFilters, Citation, QueryPlan, SearchFilters
from .retrieval import Retriever, valid_ticker

_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

NO_RESULTS = {
    "English": "I couldn't find anything in the indexed filings that matches this question. "
    "Try naming the company, the filing type, or using different keywords.",
}


def cited_numbers(answer: str) -> set[int]:
    """Numbers cited as [1], [2][3] or [1, 4]."""
    found: set[int] = set()
    for group in _CITATION.findall(answer):
        found.update(int(n) for n in group.split(","))
    return found


def resolve_filters(
    requested: SearchFilters, plan: QueryPlan, known_tickers: set[str]
) -> AppliedFilters:
    """Filters chosen in the UI win. Otherwise use what Gemini spotted in the question,
    keeping only tickers we actually index, so a guessed ticker can't empty the results."""
    def clean_tickers(values: list[str]) -> list[str]:
        out = []
        for v in values:
            t = v.strip().upper().replace(".", "-")
            if valid_ticker(t) and (not known_tickers or t in known_tickers) and t not in out:
                out.append(t)
        return out

    def clean_forms(values: list[str]) -> list[str]:
        return [f for f in dict.fromkeys(v.strip().upper() for v in values) if f in FORM_TYPES]

    if requested.tickers or requested.form_types or requested.from_year:
        return AppliedFilters(
            tickers=clean_tickers(requested.tickers),
            form_types=clean_forms(requested.form_types),
            from_year=requested.from_year,
        )
    year = plan.from_year if plan.from_year and 1994 <= plan.from_year <= 2100 else None
    filters = AppliedFilters(
        tickers=clean_tickers(plan.tickers),
        form_types=clean_forms(plan.form_types),
        from_year=year,
    )
    filters.inferred = bool(filters.tickers or filters.form_types or filters.from_year)
    return filters


def run_search(
    question: str,
    requested: SearchFilters,
    llm: LLM,
    retriever: Retriever,
    known_tickers: set[str],
    k: int = 8,
) -> tuple[QueryPlan, AppliedFilters, str, list[Citation]]:
    plan = llm.plan(question)
    search_query = plan.search_query.strip() or question
    filters = resolve_filters(requested, plan, known_tickers)

    passages = retriever.retrieve(search_query, filters, k)
    if not passages and filters.inferred:
        # The filters were our guess, not the user's choice: retry without them.
        filters = AppliedFilters()
        passages = retriever.retrieve(search_query, filters, k)

    if not passages:
        answer = NO_RESULTS["English"] if plan.language.lower().startswith("en") else (
            llm.answer(question, plan.language, [])
        )
        return plan, filters, answer, []

    answer = llm.answer(question, plan.language, passages)
    used = cited_numbers(answer)
    citations = [
        Citation(n=i, cited=i in used, **p.model_dump())
        for i, p in enumerate(passages, 1)
    ]
    return plan, filters, answer, citations
