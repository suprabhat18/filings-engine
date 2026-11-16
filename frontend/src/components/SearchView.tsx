"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AnswerText from "@/components/AnswerText";
import {
  api,
  type Citation,
  type Company,
  type Filters,
  FORM_TYPES,
  filingFromCitation,
  type Me,
  type SearchResult,
} from "@/lib/api";
import type { Dict } from "@/i18n";
import { useI18n } from "@/i18n/I18nProvider";

const EXAMPLES = [
  "How does Microsoft describe its AI infrastructure spending?",
  "¿Qué riesgos de cadena de suministro menciona Apple?",
  "JPMorgan ने अपनी पिछली तिमाही में शुद्ध ब्याज आय के बारे में क्या कहा?",
  "Which risks did Tesla add in its latest 10-K?",
];

const THIS_YEAR = new Date().getFullYear();
const YEARS = [THIS_YEAR, THIS_YEAR - 1, THIS_YEAR - 2];

function describeFilters(f: Filters, companies: Company[], t: Dict): string {
  const parts: string[] = [];
  if (f.tickers.length) {
    parts.push(f.tickers.map((tk) => companies.find((c) => c.ticker === tk)?.name ?? tk).join(", "));
  }
  if (f.form_types.length) parts.push(f.form_types.join(t.search.and));
  if (f.from_year) parts.push(t.search.since(f.from_year));
  return parts.join(", ");
}

export default function SearchView() {
  const params = useSearchParams();
  const router = useRouter();
  const { t, formatDate, errorText } = useI18n();

  const [query, setQuery] = useState(params.get("q") ?? "");
  const [tickers, setTickers] = useState<string[]>(params.getAll("ticker"));
  const [forms, setForms] = useState<string[]>(params.getAll("form"));
  const [fromYear, setFromYear] = useState<number | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyInput, setCompanyInput] = useState("");

  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slow, setSlow] = useState(false); // the backend may be starting up
  const [quota, setQuota] = useState<{ used: number; limit: number } | null>(null);
  const [activeSource, setActiveSource] = useState<number | null>(null);
  const [hoverSource, setHoverSource] = useState<number | null>(null);
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const sourceRefs = useRef<Record<number, HTMLLIElement | null>>({});
  const autoRan = useRef(false);

  useEffect(() => {
    api<Company[]>("companies").then(setCompanies).catch(() => setCompanies([]));
    api<Me>("me")
      .then((me) => setQuota({ used: me.searches_today, limit: me.daily_quota }))
      .catch(() => undefined);
  }, []);

  // The backend scales to zero when idle; the first search after a quiet spell
  // includes its start-up. Explain the wait instead of leaving people guessing.
  useEffect(() => {
    if (!loading) {
      setSlow(false);
      return;
    }
    const timer = setTimeout(() => setSlow(true), 6000);
    return () => clearTimeout(timer);
  }, [loading]);

  const runSearch = useCallback(
    async (q: string) => {
      const text = q.trim();
      if (text.length < 2) return;
      setLoading(true);
      setError(null);
      setActiveSource(null);
      setSaved({});
      try {
        const res = await api<SearchResult>("search", {
          method: "POST",
          body: { query: text, filters: { tickers, form_types: forms, from_year: fromYear } },
        });
        setResult(res);
        setQuota((q) => (q ? { ...q, used: q.used + 1 } : q));
        router.replace(`/?q=${encodeURIComponent(text)}`, { scroll: false });
      } catch (e) {
        setResult(null);
        setError(errorText(e, "network"));
      } finally {
        setLoading(false);
      }
    },
    [tickers, forms, fromYear, router, errorText],
  );

  // Re-run a search opened from History (?q=...&run=1)
  useEffect(() => {
    if (!autoRan.current && params.get("run") === "1" && query) {
      autoRan.current = true;
      void runSearch(query);
    }
  }, [params, query, runSearch]);

  const addCompany = (value: string) => {
    const v = value.trim().toUpperCase();
    const match = companies.find((c) => c.ticker === v || c.name.toUpperCase() === v);
    if (match && !tickers.includes(match.ticker)) setTickers([...tickers, match.ticker]);
    setCompanyInput("");
  };

  const toggleForm = (f: string) =>
    setForms(forms.includes(f) ? forms.filter((x) => x !== f) : [...forms, f]);

  const showSource = (n: number) => {
    setActiveSource(n);
    sourceRefs.current[n]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const validNumbers = useMemo(
    () => new Set(result?.citations.map((c) => c.n) ?? []),
    [result],
  );
  const sources = useMemo(() => {
    if (!result) return [];
    return [...result.citations].sort((a, b) => Number(b.cited) - Number(a.cited) || a.n - b.n);
  }, [result]);

  const saveAnswer = async () => {
    if (!result) return;
    try {
      await api("bookmarks", {
        method: "POST",
        body: {
          kind: "answer",
          title: result.query.slice(0, 300),
          query: result.query,
          answer: result.answer,
          citations: result.citations.filter((c) => c.cited).slice(0, 20),
        },
      });
      setSaved((s) => ({ ...s, answer: true }));
    } catch (e) {
      setError(errorText(e, "saveAnswer"));
    }
  };

  const saveFiling = async (c: Citation) => {
    try {
      await api("bookmarks", {
        method: "POST",
        body: { kind: "filing", title: c.title.slice(0, 300), filing: filingFromCitation(c) },
      });
      setSaved((s) => ({ ...s, [c.filing_id]: true }));
    } catch (e) {
      setError(errorText(e, "saveFiling"));
    }
  };

  const highlighted = hoverSource ?? activeSource;

  return (
    <div className="search">
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          void runSearch(query);
        }}
      >
        <label htmlFor="q" className="ask__label">
          {t.search.label}
        </label>
        <div className="ask__row">
          <textarea
            id="q"
            className="ask__input"
            rows={2}
            maxLength={500}
            value={query}
            placeholder={t.search.placeholder}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void runSearch(query);
              }
            }}
          />
          <button type="submit" className="btn btn--primary" disabled={loading || query.trim().length < 2}>
            {loading ? t.search.searching : t.search.submit}
          </button>
        </div>

        <fieldset className="filters">
          <legend className="visually-hidden">{t.search.narrow}</legend>
          <div className="filters__group">
            <label htmlFor="company" className="filters__label">{t.search.companies}</label>
            <div className="chips">
              {tickers.map((tk) => (
                <button
                  key={tk}
                  type="button"
                  className="chip"
                  onClick={() => setTickers(tickers.filter((x) => x !== tk))}
                  aria-label={t.search.removeTicker(tk)}
                >
                  {tk} <span aria-hidden="true">×</span>
                </button>
              ))}
              <input
                id="company"
                list="company-list"
                className="chips__input"
                placeholder={tickers.length ? t.search.addAnother : t.search.anyCompany}
                value={companyInput}
                onChange={(e) => {
                  setCompanyInput(e.target.value);
                  if (companies.some((c) => c.ticker === e.target.value.toUpperCase())) addCompany(e.target.value);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addCompany(companyInput);
                  }
                }}
              />
              <datalist id="company-list">
                {companies.map((c) => (
                  <option key={c.ticker} value={c.ticker}>{c.name}</option>
                ))}
              </datalist>
            </div>
          </div>

          <div className="filters__group">
            <span className="filters__label" id="forms-label">{t.search.filingTypes}</span>
            <div className="toggle-row" role="group" aria-labelledby="forms-label">
              {FORM_TYPES.map((f) => (
                <button
                  key={f}
                  type="button"
                  className="toggle"
                  aria-pressed={forms.includes(f)}
                  onClick={() => toggleForm(f)}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          <div className="filters__group">
            <label htmlFor="year" className="filters__label">{t.search.filedSince}</label>
            <select
              id="year"
              className="select"
              value={fromYear ?? ""}
              onChange={(e) => setFromYear(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">{t.search.anyTime}</option>
              {YEARS.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>
        </fieldset>
      </form>

      {quota && (
        <p className="quota-note">
          {t.search.left(Math.max(quota.limit - quota.used, 0), quota.limit)}
        </p>
      )}

      {error && <p className="notice notice--error" role="alert">{error}</p>}

      {loading && (
        <p className="reading" role="status">
          {slow ? t.search.wakingUp : t.search.reading}
        </p>
      )}

      {!result && !loading && !error && (
        <section className="examples" aria-label={t.search.examplesLabel}>
          <p className="muted">{t.search.tryOne}</p>
          <ul>
            {EXAMPLES.map((ex) => (
              <li key={ex}>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => {
                    setQuery(ex);
                    void runSearch(ex);
                  }}
                >
                  {ex}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {result && !loading && (
        <article className="result">
          <div className="answer">
            <h1 className="answer__question">{result.query}</h1>
            <p className="answer__meta">
              {result.language.toLowerCase().startsWith("en")
                ? t.search.searchedFor(result.search_query)
                : t.search.answeredIn(result.language, result.search_query)}
              {describeFilters(result.filters, companies, t) &&
                t.search.inScope(describeFilters(result.filters, companies, t))}
              {result.filters.inferred && t.search.inferred}.
            </p>
            <AnswerText
              text={result.answer}
              activeSource={highlighted}
              onCite={showSource}
              onHover={setHoverSource}
              validNumbers={validNumbers}
            />
            <div className="answer__actions">
              <button type="button" className="btn" onClick={saveAnswer} disabled={saved.answer}>
                {saved.answer ? t.search.answerSaved : t.search.saveAnswer}
              </button>
            </div>
          </div>

          {sources.length > 0 && (
            <aside className="sources" aria-label={t.search.sources}>
              <h2 className="sources__title">{t.search.sources}</h2>
              <ol className="sources__list">
                {sources.map((c) => (
                  <li
                    key={c.n}
                    ref={(el) => {
                      sourceRefs.current[c.n] = el;
                    }}
                    className="source"
                    data-active={highlighted === c.n || undefined}
                    data-cited={c.cited || undefined}
                  >
                    <span className="source__n" aria-label={t.search.sourceN(c.n)}>{c.n}</span>
                    <div className="source__body">
                      <p className="source__title">
                        {c.company_name || c.ticker} <span className="source__form">{c.form_type}</span>
                        {c.section && <span className="source__section">, {c.section}</span>}
                      </p>
                      <p className="source__date">{t.search.filed(formatDate(c.filing_date))}</p>
                      <blockquote className="source__excerpt">
                        {c.content.length > 320 ? `${c.content.slice(0, 320).trim()}…` : c.content}
                      </blockquote>
                      <p className="source__links">
                        {c.source_url && (
                          <a href={c.source_url} target="_blank" rel="noreferrer">
                            {t.search.openOnSec}
                          </a>
                        )}
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => saveFiling(c)}
                          disabled={saved[c.filing_id]}
                        >
                          {saved[c.filing_id] ? t.search.filingSaved : t.search.saveFiling}
                        </button>
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
              {sources.some((c) => !c.cited) && (
                <p className="fine-print">{t.search.uncitedLast}</p>
              )}
            </aside>
          )}
        </article>
      )}
    </div>
  );
}
