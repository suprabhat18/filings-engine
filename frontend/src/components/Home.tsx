"use client";

import { useRouter } from "next/navigation";
import { signIn, useSession } from "next-auth/react";
import { useEffect, useMemo, useRef, useState } from "react";
import AnswerText from "@/components/AnswerText";
import { LOCALE } from "@/i18n";
import { useI18n } from "@/i18n/I18nProvider";
import { api, ApiError, type PublicStats, type SearchResult } from "@/lib/api";

const FREE_MAX_CHARS = 200;
const FREE_USED_KEY = "fr_free_used";
const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";
const STACK = ["Python", "FastAPI", "Cloud Run", "Vertex AI Search", "Gemini", "Firestore", "Next.js", "Vercel"];
const TAGS = ["NVDA · 10-K", "GOOGL · 10-Q", "10-Q", "TSLA · 8-K"];

type Turnstile = {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  reset: (id: string) => void;
};

function readFlag(): boolean {
  try {
    return window.localStorage.getItem(FREE_USED_KEY) === "1";
  } catch {
    return false;
  }
}

function setFlag() {
  try {
    window.localStorage.setItem(FREE_USED_KEY, "1");
  } catch {
    /* private mode: the server still enforces the limit */
  }
}

/** The public homepage: pitch, one free question, coverage, how it works, FAQ. */
export default function Home() {
  const { t, lang, formatDate, errorText } = useI18n();
  const { status } = useSession();
  const router = useRouter();
  const signedIn = status === "authenticated";

  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [freeUsed, setFreeUsed] = useState(false);
  const [stats, setStats] = useState<PublicStats | null>(null);
  const [activeSource, setActiveSource] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLElement>(null);
  const turnstileBox = useRef<HTMLDivElement>(null);
  const turnstileId = useRef<string | null>(null);
  const turnstileToken = useRef("");

  useEffect(() => {
    setFreeUsed(readFlag());
    api<PublicStats>("public/stats").then(setStats).catch(() => setStats(null));
  }, []);

  useEffect(() => {
    if (!loading) {
      setSlow(false);
      return;
    }
    // Bring the answer area into view: on a laptop it starts below the hero.
    resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    const timer = setTimeout(() => setSlow(true), 6000);
    return () => clearTimeout(timer);
  }, [loading]);

  // Optional Cloudflare Turnstile bot check: invisible unless Cloudflare has doubts.
  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || signedIn || !turnstileBox.current) return;
    const mount = () => {
      const ts = (window as unknown as { turnstile?: Turnstile }).turnstile;
      if (!ts || !turnstileBox.current || turnstileId.current) return;
      turnstileId.current = ts.render(turnstileBox.current, {
        sitekey: TURNSTILE_SITE_KEY,
        appearance: "interaction-only",
        callback: (token: string) => {
          turnstileToken.current = token;
        },
      });
    };
    if (document.querySelector("script[data-turnstile]")) {
      mount();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.dataset.turnstile = "1";
    script.onload = mount;
    document.head.appendChild(script);
  }, [signedIn]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (q.length < 2) return;
    if (signedIn) {
      router.push(`/?q=${encodeURIComponent(q)}&run=1`);
      return;
    }
    if (q.length > FREE_MAX_CHARS) {
      setError(t.home.tooLong(FREE_MAX_CHARS));
      return;
    }
    setLoading(true);
    setError(null);
    setActiveSource(null);
    try {
      const res = await api<SearchResult>("public/try", {
        method: "POST",
        body: { query: q, turnstile_token: turnstileToken.current },
      });
      setResult(res);
      setFlag();
      setFreeUsed(true);
    } catch (e) {
      setResult(null);
      if (e instanceof ApiError && (e.code === "free_used" || e.code === "free_limit")) {
        setFlag();
        setFreeUsed(true);
      }
      setError(errorText(e, "network"));
    } finally {
      setLoading(false);
      const ts = (window as unknown as { turnstile?: Turnstile }).turnstile;
      if (ts && turnstileId.current) {
        turnstileToken.current = "";
        ts.reset(turnstileId.current);
      }
    }
  };

  const signInToContinue = () =>
    signIn("google", { callbackUrl: query.trim() ? `/?q=${encodeURIComponent(query.trim())}&run=1` : "/" });

  const pick = (q: string) => {
    setQuery(q);
    inputRef.current?.focus();
    inputRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const number = useMemo(() => new Intl.NumberFormat(LOCALE[lang]), [lang]);
  const cited = result?.citations.filter((c) => c.cited) ?? [];
  const validNumbers = useMemo(() => new Set(result?.citations.map((c) => c.n) ?? []), [result]);
  const showSignIn = !signedIn && freeUsed;

  return (
    <div className="home">
      {/* Hero */}
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero__inner">
          <div className="hero__copy">
            <h1 id="hero-title" className="hero__title">{t.home.heroTitle}</h1>
            <p className="hero__sub">{t.home.heroSub}</p>
            <form
              className="try"
              onSubmit={(e) => {
                e.preventDefault();
                void ask(query);
              }}
            >
              <label htmlFor="try-q" className="try__label">{t.home.tryLabel}</label>
              <div className="try__row">
                <input
                  id="try-q"
                  ref={inputRef}
                  className="try__input"
                  type="text"
                  value={query}
                  maxLength={signedIn ? 500 : FREE_MAX_CHARS}
                  placeholder={t.home.placeholder}
                  onChange={(e) => setQuery(e.target.value)}
                />
                {showSignIn ? (
                  <button type="button" className="btn btn--primary try__btn" onClick={signInToContinue}>
                    {t.common.signInGoogle}
                  </button>
                ) : (
                  <button type="submit" className="btn btn--primary try__btn" disabled={loading || query.trim().length < 2}>
                    {loading ? t.search.searching : t.home.ask}
                  </button>
                )}
              </div>
              <div className="try__chips">
                {t.home.suggestions.map((s) => (
                  <button key={s} type="button" className="try__chip" onClick={() => pick(s)}>
                    {s}
                  </button>
                ))}
              </div>
              <div ref={turnstileBox} className="try__check" />
            </form>
          </div>

          <figure className="example" aria-label={t.home.exampleLabel}>
            <figcaption className="example__q">{t.home.exampleQ}</figcaption>
            <p className="example__a">
              {t.home.exampleA} <span className="example__cite" aria-hidden="true">1</span>
            </p>
            <div className="example__source" lang="en">
              <p className="example__source-title">
                <strong>1 · Apple Inc.</strong> 10-K · Item 1A. Risk Factors
              </p>
              <p className="example__quote">
                “Substantially all of the Company’s hardware products are manufactured by outsourcing partners
                that are located primarily in China mainland, India, Japan, South Korea, Taiwan and Vietnam.”
              </p>
            </div>
          </figure>
        </div>
      </section>

      {/* The free answer, then the sign-in prompt */}
      {(loading || error || result) && (
        <section ref={resultRef} className="home-section free-result" aria-live="polite">
          {loading && <p className="reading" role="status">{slow ? t.search.wakingUp : t.search.reading}</p>}
          {error && !loading && <p className="notice notice--error" role="alert">{error}</p>}
          {result && !loading && (
            <div className="free-result__card">
              <div className="free-result__answer">
                <h2 className="free-result__q">{result.query}</h2>
                <AnswerText
                  text={result.answer}
                  activeSource={activeSource}
                  onCite={setActiveSource}
                  onHover={setActiveSource}
                  validNumbers={validNumbers}
                />
              </div>
              {cited.length > 0 && (
                <aside className="free-result__sources" aria-label={t.search.sources}>
                  <h3 className="free-result__sources-title">{t.search.sources}</h3>
                  <ol>
                    {cited.slice(0, 4).map((c) => (
                      <li key={c.n} data-active={activeSource === c.n || undefined}>
                        <p className="free-result__source-title">
                          <strong>{c.n} · {c.company_name || c.ticker}</strong> {c.form_type}
                          {c.section ? ` · ${c.section}` : ""}
                        </p>
                        <p className="free-result__date">{t.search.filed(formatDate(c.filing_date))}</p>
                        {c.source_url && (
                          <a href={c.source_url} target="_blank" rel="noreferrer">{t.search.openOnSec}</a>
                        )}
                      </li>
                    ))}
                  </ol>
                </aside>
              )}
            </div>
          )}
          {!signedIn && (result || showSignIn) && !loading && (
            <div className="free-banner">
              <p>{t.home.banner}</p>
              <button type="button" className="btn btn--primary" onClick={signInToContinue}>
                {t.common.signInGoogle}
              </button>
            </div>
          )}
        </section>
      )}

      {/* Live numbers */}
      <section className="home-section" aria-label={t.home.statsLabel}>
        <ul className="stats">
          <li className="stat">
            <span className="stat__value">{stats ? number.format(stats.filings) : "—"}</span>
            <span className="stat__label">{t.home.statFilings}</span>
          </li>
          <li className="stat">
            <span className="stat__value">{stats ? number.format(stats.companies) : "—"}</span>
            <span className="stat__label">{t.home.statCompanies}</span>
          </li>
          <li className="stat">
            <span className="stat__value">{number.format(6)}</span>
            <span className="stat__label">{t.home.statLanguages}</span>
          </li>
          <li className="stat">
            <span className="stat__value stat__value--date">{stats?.updated_at ? formatDate(stats.updated_at) : "—"}</span>
            <span className="stat__label">{t.home.statUpdated}</span>
          </li>
        </ul>
      </section>

      {/* Suggested questions */}
      <section className="home-section" aria-labelledby="suggested-title">
        <h2 id="suggested-title" className="home-title">{t.home.suggestedTitle}</h2>
        <div className="cards">
          {t.home.suggested.map((q, i) => (
            <button key={q} type="button" className="card card--button" onClick={() => pick(q)}>
              <span className="card__q">{q}</span>
              <span className="card__tag" lang="en">{TAGS[i]}</span>
            </button>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="home-section" aria-labelledby="how-title">
        <h2 id="how-title" className="home-title">{t.home.howTitle}</h2>
        <ol className="cards steps">
          {t.home.steps.map(([title, body], i) => (
            <li key={title} className="card">
              <span className="step__n" aria-hidden="true">{i + 1}</span>
              <span className="card__title">{title}</span>
              <span className="card__body">{body}</span>
            </li>
          ))}
        </ol>
        <div className="built-with">
          <span className="built-with__label">{t.home.builtWith}</span>
          {STACK.map((s) => (
            <span key={s} className="built-with__chip" lang="en">{s}</span>
          ))}
        </div>
      </section>

      {/* Trust */}
      <section className="home-section" aria-labelledby="trust-title">
        <h2 id="trust-title" className="home-title">{t.home.trustTitle}</h2>
        <div className="cards">
          {t.home.trust.map(([title, body]) => (
            <div key={title} className="card card--accent">
              <span className="card__title">{title}</span>
              <span className="card__body">{body}</span>
            </div>
          ))}
        </div>
      </section>

      {/* FAQ */}
      <section className="home-section" aria-labelledby="faq-title">
        <h2 id="faq-title" className="home-title">{t.home.faqTitle}</h2>
        <div className="faq">
          {t.home.faq.map(([q, a]) => (
            <div key={q} className="faq__item">
              <h3 className="faq__q">{q}</h3>
              <p className="faq__a">{a}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
