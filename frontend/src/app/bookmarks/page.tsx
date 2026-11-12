"use client";

import { useEffect, useState } from "react";
import AnswerText from "@/components/AnswerText";
import RequireSignIn from "@/components/RequireSignIn";
import { api, ApiError, type Bookmark, formatDate } from "@/lib/api";

function Bookmarks() {
  const [items, setItems] = useState<Bookmark[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Bookmark[]>("bookmarks")
      .then(setItems)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load bookmarks."));
  }, []);

  const remove = async (id: string) => {
    try {
      await api(`bookmarks/${id}`, { method: "DELETE" });
      setItems((list) => list?.filter((b) => b.id !== id) ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't remove the bookmark.");
    }
  };

  return (
    <div className="stack">
      <h1 className="page-title">Bookmarks</h1>
      {error && <p className="notice notice--error" role="alert">{error}</p>}
      {items === null && !error && <p className="muted" role="status">Loading…</p>}
      {items?.length === 0 && (
        <p className="empty">
          Nothing saved yet. Use “Save answer” or “Save filing” on a search result to keep it here.
        </p>
      )}
      <ul className="bookmarks">
        {items?.map((b) => (
          <li key={b.id} className="bookmark">
            <div className="bookmark__head">
              <p className="bookmark__kind">
                {b.kind === "answer" ? "Answer" : "Filing"}, saved {formatDate(b.created_at)}
              </p>
              <button type="button" className="link-button" onClick={() => remove(b.id)}>
                Remove
              </button>
            </div>
            {b.kind === "answer" ? (
              <>
                <h2 className="bookmark__title">{b.query ?? b.title}</h2>
                <AnswerText text={b.answer ?? ""} validNumbers={new Set(b.citations.map((c) => c.n))} />
                {b.citations.length > 0 && (
                  <ol className="bookmark__sources">
                    {b.citations.map((c) => (
                      <li key={c.n} value={c.n}>
                        <a href={c.source_url} target="_blank" rel="noreferrer">
                          {c.company_name} {c.form_type}, filed {formatDate(c.filing_date)}
                        </a>
                      </li>
                    ))}
                  </ol>
                )}
              </>
            ) : (
              b.filing && (
                <p className="bookmark__title">
                  <a href={b.filing.source_url} target="_blank" rel="noreferrer">
                    {b.filing.company_name} {b.filing.form_type}, filed {formatDate(b.filing.filing_date)}
                  </a>
                </p>
              )
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function BookmarksPage() {
  return (
    <RequireSignIn>
      <Bookmarks />
    </RequireSignIn>
  );
}
