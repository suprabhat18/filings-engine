# Financial Filings Research & Analysis Engine

Ask a question about S&P 100 companies in any language ("¿Qué riesgos de cadena de
suministro menciona Apple?") and get an answer drawn from their SEC 10-K, 10-Q and 8-K
filings, in your language, with every claim linked to the passage it came from.

**Stack:** Google Cloud Platform (Vertex AI Search, Gemini 3.8 Flash, Firestore, Cloud Storage,
Cloud Run, Cloud Scheduler) · FastAPI (Python) · Next.js (TypeScript)

## What it does

- **Multilingual RAG search.** Gemini reads the question, detects its language, rewrites it
  as an English search query and spots company and form-type filters. Vertex AI Search
  retrieves the most relevant filing passages. Gemini then answers in the user's language
  using only those passages, citing each claim as [1], [2] and so on.
- **Incremental ingestion on demand.** One command (`python -m edgar.update`) checks SEC
  EDGAR for new filings, downloads only the ones not already in the Firestore catalog,
  splits them into section-labelled passages and imports them into the index.
- **Google OAuth 2.0 sign-in** with per-user rate limiting and daily quotas.
- **Firestore-backed watchlists, bookmarks and search history.** Follow companies to see
  their latest filings, save answers or filings, and re-run past searches.

## Architecture

```
                         python -m edgar.update   (run whenever you choose)
                                     │
                                     ▼
 SEC EDGAR APIs ─────►  ingestion/
                        │  list filings → skip known → download → clean HTML → text
                        │  → split into ~350-word passages, each tagged with its section
                        │
                        ├──► Cloud Storage: JSONL import files (passages inline)
                        ├──► Firestore: filings catalog, companies, run log
                        └──► Vertex AI Search: import (default parser, free)
                                     │
 Browser ──► frontend/ (Next.js) ──► backend/ (FastAPI on Cloud Run)
   Google     NextAuth sign-in,       1. verify Google ID token, rate limit + quota
   sign-in    server-side proxy       2. Gemini: language + English query + filters
              adds the ID token       3. Vertex AI Search: top passages (filtered)
                                      4. Gemini: cited answer in the user's language
                                      5. Firestore: history, bookmarks, watchlist
```

## Repository layout

| Folder | Contents |
|---|---|
| `ingestion/edgar/` | `run.py` initial bulk download · `publish.py` upload + catalog + import · `search_index.py` index setup, test, delete · `update.py` fetch + import new filings · `clean.py` HTML → text · `documents.py` filing → section-labelled passages |
| `backend/app/` | `main.py` API routes · `rag.py` search pipeline · `llm.py` Gemini prompts · `retrieval.py` Vertex AI Search · `auth.py` Google token check · `ratelimit.py` · `store.py` Firestore |
| `frontend/src/` | Next.js App Router pages (search, watchlist, bookmarks, history), NextAuth config, backend proxy |
| `deploy/` | Scripts for GCP setup and backend deploy |
| `docs/SETUP.md` | Step-by-step setup and deployment guide |

## Design decisions

- **Our own section-aware passages, not paid parsing.** Each filing is split in code into
  ~350-word passages that never cross a section boundary ("Item 1A. Risk Factors",
  "Exhibit 99.1"), and each passage is imported as its own plain-text document with its
  section as metadata. Vertex AI Search's default parser handles that for free, whereas
  its layout parser bills per page (an early version of this project spent its whole
  trial credit on one import that way). Citations still point to a labelled passage.
- **Query planning before retrieval.** The question is translated and reduced to an English
  keyword query, because the filings are in English. Filters that Gemini guesses are
  checked against the indexed companies, and dropped if they return no results. Filters
  the user picks always take priority.
- **Grounded answers.** The answer prompt only allows the retrieved excerpts, requires a
  citation for every claim, and the UI marks which sources were actually cited.
- **Idempotent ingestion.** Firestore holds a catalog of published filings. Both the bulk
  load and `edgar.update` check it first, so re-runs never duplicate work, and imports use
  INCREMENTAL mode, so they never delete existing documents.
- **Cost and abuse limits.** A per-user sliding window (10 searches/minute) stops bursts.
  Firestore-backed daily quotas (per user and global) cap Gemini and search spend across
  Cloud Run instances.
- **Token handling.** The browser never sees the Google ID token. The Next.js server keeps
  it in NextAuth's encrypted cookie, refreshes it before its one-hour expiry, and attaches
  it when proxying requests to the backend, which verifies its signature and audience.
- **Least-privilege service accounts.** The API runs as its own service account with only
  the roles it needs; ingestion has a separate account for running it as a job.

## Testing

```bash
cd ingestion && python -m pytest     # 21 tests: EDGAR parsing, cleaning, passages, publishing, updates
cd backend && python -m pytest       # 25 tests: auth, RAG pipeline, filters, limits, user data
cd frontend && npm run typecheck && npm run build
```

Tests run offline. Google services are replaced with fakes behind the same interfaces
(`Retriever`, `LLM`, `Store`), and the Vertex AI response parsing is tested against real
client-library objects.

## Setup

See [docs/SETUP.md](docs/SETUP.md).

## Data source

Filings come from SEC EDGAR's public APIs, accessed with a declared User-Agent and below
the SEC's 10 requests/second limit. The company list (`ingestion/sp100.txt`) should be
checked against the current S&P 100 membership. Answers are AI-generated, can be wrong,
and are not investment advice.
