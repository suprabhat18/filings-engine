"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import RequireSignIn from "@/components/RequireSignIn";
import { api, type Company, type Filing, type Me, type WatchItem } from "@/lib/api";
import { useI18n } from "@/i18n/I18nProvider";

function Watchlist() {
  const { t, formatDate, errorText } = useI18n();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [items, setItems] = useState<WatchItem[]>([]);
  const [filings, setFilings] = useState<Filing[]>([]);
  const [choice, setChoice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);

  const reload = async () => {
    const [w, f] = await Promise.all([
      api<WatchItem[]>("watchlist"),
      api<Filing[]>("watchlist/filings?limit=30"),
    ]);
    setItems(w);
    setFilings(f);
  };

  useEffect(() => {
    // "Last updated" is a nice-to-have: never let it block the page.
    api<Me>("me").then((me) => setUpdatedAt(me.index_updated_at)).catch(() => undefined);
    Promise.all([api<Company[]>("companies").then(setCompanies), reload()])
      .catch((e) => setError(errorText(e, "loadWatchlist")))
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
      setError(errorText(e, "addCompany"));
    }
  };

  const remove = async (ticker: string) => {
    setError(null);
    try {
      await api(`watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });
      await reload();
    } catch (e) {
      setError(errorText(e, "removeCompany"));
    }
  };

  const watched = new Set(items.map((i) => i.ticker));
  const available = companies.filter((c) => !watched.has(c.ticker));

  return (
    <div className="stack">
      <h1 className="page-title">{t.watchlist.title}</h1>
      <p className="muted">
        {t.watchlist.intro}
        {updatedAt && t.watchlist.updated(formatDate(updatedAt))}
      </p>

      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          void add();
        }}
      >
        <label htmlFor="add-company" className="visually-hidden">{t.watchlist.companyToFollow}</label>
        <select id="add-company" className="select" value={choice} onChange={(e) => setChoice(e.target.value)}>
          <option value="">{t.watchlist.choose}</option>
          {available.map((c) => (
            <option key={c.ticker} value={c.ticker}>
              {c.ticker}: {c.name}
            </option>
          ))}
        </select>
        <button type="submit" className="btn btn--primary" disabled={!choice}>
          {t.watchlist.follow}
        </button>
      </form>

      {error && <p className="notice notice--error" role="alert">{error}</p>}
      {loading && <p className="muted" role="status">{t.common.loading}</p>}

      {!loading && items.length === 0 && (
        <p className="empty">{t.watchlist.empty}</p>
      )}

      {items.length > 0 && (
        <div className="two-col">
          <section aria-labelledby="following">
            <h2 id="following" className="section-title">{t.watchlist.following}</h2>
            <ul className="rule-list">
              {items.map((i) => (
                <li key={i.ticker} className="rule-list__row">
                  <span>
                    <strong>{i.ticker}</strong> <span className="muted">{i.name}</span>
                  </span>
                  <button type="button" className="link-button" onClick={() => remove(i.ticker)}>
                    {t.watchlist.unfollow}
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="latest">
            <h2 id="latest" className="section-title">{t.watchlist.latest}</h2>
            {filings.length === 0 ? (
              <p className="empty">{t.watchlist.noFilings}</p>
            ) : (
              <table className="filings-table">
                <thead>
                  <tr>
                    <th scope="col">{t.watchlist.filed}</th>
                    <th scope="col">{t.watchlist.company}</th>
                    <th scope="col">{t.watchlist.form}</th>
                    <th scope="col"><span className="visually-hidden">{t.watchlist.actions}</span></th>
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
                          {t.watchlist.askAboutIt}
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
