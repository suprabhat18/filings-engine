"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import RequireSignIn from "@/components/RequireSignIn";
import { api, ApiError, type Company, type Filing, formatDate, type WatchItem } from "@/lib/api";

function Watchlist() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [items, setItems] = useState<WatchItem[]>([]);
  const [filings, setFilings] = useState<Filing[]>([]);
  const [choice, setChoice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    const [w, f] = await Promise.all([
      api<WatchItem[]>("watchlist"),
      api<Filing[]>("watchlist/filings?limit=30"),
    ]);
    setItems(w);
    setFilings(f);
  };

  useEffect(() => {
    Promise.all([api<Company[]>("companies").then(setCompanies), reload()])
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load your watchlist."))
      .finally(() => setLoading(false));
  }, []);

  const add = async () => {
    if (!choice) return;
    setError(null);
    try {
      await api(`watchlist/${encodeURIComponent(choice)}`, { method: "PUT" });
      setChoice("");
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't add the company.");
    }
  };

  const remove = async (ticker: string) => {
    setError(null);
    try {
      await api(`watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't remove the company.");
    }
  };

  const watched = new Set(items.map((i) => i.ticker));
  const available = companies.filter((c) => !watched.has(c.ticker));

  return (
    <div className="stack">
      <h1 className="page-title">Watchlist</h1>
      <p className="muted">Follow companies to see their newest filings here, refreshed daily from EDGAR.</p>

      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          void add();
        }}
      >
        <label htmlFor="add-company" className="visually-hidden">Company to follow</label>
        <select id="add-company" className="select" value={choice} onChange={(e) => setChoice(e.target.value)}>
          <option value="">Choose a company…</option>
          {available.map((c) => (
            <option key={c.ticker} value={c.ticker}>
              {c.ticker}: {c.name}
            </option>
          ))}
        </select>
        <button type="submit" className="btn btn--primary" disabled={!choice}>
          Follow
        </button>
      </form>

      {error && <p className="notice notice--error" role="alert">{error}</p>}
      {loading && <p className="muted" role="status">Loading…</p>}

      {!loading && items.length === 0 && (
        <p className="empty">You aren’t following any companies yet. Choose one above to start.</p>
      )}

      {items.length > 0 && (
        <div className="two-col">
          <section aria-labelledby="following">
            <h2 id="following" className="section-title">Following</h2>
            <ul className="rule-list">
              {items.map((i) => (
                <li key={i.ticker} className="rule-list__row">
                  <span>
                    <strong>{i.ticker}</strong> <span className="muted">{i.name}</span>
                  </span>
                  <button type="button" className="link-button" onClick={() => remove(i.ticker)}>
                    Unfollow
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="latest">
            <h2 id="latest" className="section-title">Latest filings</h2>
            {filings.length === 0 ? (
              <p className="empty">No filings yet for these companies.</p>
            ) : (
              <table className="filings-table">
                <thead>
                  <tr>
                    <th scope="col">Filed</th>
                    <th scope="col">Company</th>
                    <th scope="col">Form</th>
                    <th scope="col"><span className="visually-hidden">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {filings.map((f) => (
                    <tr key={f.filing_id}>
                      <td className="nowrap">{formatDate(f.filing_date)}</td>
                      <td>{f.company_name}</td>
                      <td className="nowrap">{f.form_type}</td>
                      <td className="table-actions">
                        <Link href={`/?ticker=${encodeURIComponent(f.ticker)}&form=${encodeURIComponent(f.form_type)}`}>
                          Ask about it
                        </Link>
                        <a href={f.source_url} target="_blank" rel="noreferrer">SEC.gov</a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export default function WatchlistPage() {
  return (
    <RequireSignIn>
      <Watchlist />
    </RequireSignIn>
  );
}
