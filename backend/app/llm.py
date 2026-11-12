"""Gemini calls: understand the question, then write a cited answer."""

from __future__ import annotations

from typing import Protocol

from .config import FORM_TYPES
from .models import Passage, QueryPlan

PLAN_INSTRUCTIONS = f"""You prepare searches over SEC filings (10-K, 10-Q, 8-K) of S&P 100 companies.
Given a user's question in any language, return:
- language: the language the question is written in (e.g. "English", "Spanish", "Hindi").
- search_query: a short English keyword query that will find the relevant passages.
  Translate if needed. Drop filler words; keep company names, metrics and topics.
- tickers: US stock tickers of companies explicitly named (Apple -> AAPL, Alphabet/Google -> GOOG,
  Berkshire Hathaway -> BRK-B). Empty if no company is named.
- form_types: only if the question names a filing type; allowed values {list(FORM_TYPES)}.
  Annual report -> 10-K, quarterly report -> 10-Q, current report / press release -> 8-K.
- from_year: earliest filing year only if the question names a period (e.g. "since 2025"), else null.
Return JSON only."""

ANSWER_INSTRUCTIONS = """You are a research assistant for SEC filings.
Answer the question using ONLY the numbered excerpts provided.
- Cite every claim with the excerpt number in square brackets, like [1] or [2][4].
- Quote figures exactly as written in the excerpts, with their units and periods.
- If the excerpts do not contain the answer, say so plainly and suggest how to rephrase.
  Do not use outside knowledge.
- Write the whole answer in {language}. Keep company names, tickers and form names as they are.
- Be concise: a short paragraph, or bullet points for lists. No investment advice."""


class LLM(Protocol):
    def plan(self, question: str) -> QueryPlan: ...
    def answer(self, question: str, language: str, passages: list[Passage]) -> str: ...


def format_passages(passages: list[Passage], max_chars: int = 2_500) -> str:
    blocks = []
    for i, p in enumerate(passages, 1):
        header = p.title or f"{p.company_name} ({p.ticker}) {p.form_type} filed {p.filing_date}"
        blocks.append(f"[{i}] {header}\n{p.content[:max_chars]}")
    return "\n\n".join(blocks)


class GeminiLLM:
    def __init__(self, project: str, location: str, model: str) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = model

    def plan(self, question: str) -> QueryPlan:
        t = self._types
        response = self._client.models.generate_content(
            model=self._model,
            contents=question,
            config=t.GenerateContentConfig(
                system_instruction=PLAN_INSTRUCTIONS,
                response_mime_type="application/json",
                response_schema=QueryPlan,
                # Gemini 3.x: thinking_level replaces thinking_budget and temperature.
                thinking_config=t.ThinkingConfig(thinking_level=t.ThinkingLevel.LOW),
            ),
        )
        if isinstance(response.parsed, QueryPlan):
            return response.parsed
        return QueryPlan.model_validate_json(response.text or "{}")

    def answer(self, question: str, language: str, passages: list[Passage]) -> str:
        t = self._types
        prompt = f"Excerpts:\n\n{format_passages(passages)}\n\nQuestion: {question}"
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=t.GenerateContentConfig(
                system_instruction=ANSWER_INSTRUCTIONS.format(language=language or "English"),
                thinking_config=t.ThinkingConfig(thinking_level=t.ThinkingLevel.LOW),
                max_output_tokens=4096,  # includes thinking tokens, so leave headroom
            ),
        )
        return (response.text or "").strip()
