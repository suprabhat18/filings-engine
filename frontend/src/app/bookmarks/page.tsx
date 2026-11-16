"use client";

import { useEffect, useState } from "react";
import AnswerText from "@/components/AnswerText";
import RequireSignIn from "@/components/RequireSignIn";
import { api, type Bookmark } from "@/lib/api";
import { useI18n } from "@/i18n/I18nProvider";

function Bookmarks() {
  const { t, formatDate, errorText } = useI18n();
  const [items, setItems] = useState<Bookmark[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Bookmark[]>("bookmarks")
      .then(setItems)
      .catch((e) => setError(errorText(e, "loadBookmarks")));
  }, []);

  const remove = async (id: string) => {
    try {
      await api(`bookmarks/${id}`, { method: "DELETE" });
      setItems((list) => list?.filter((b) => b.id !== id) ?? null);
    } catch (e) {
      setError(errorText(e, "removeBookmark"));
    }
  };

  return (
    <div className="stack">
      <h1 className="page-title">{t.bookmarks.title}</h1>
      {error && <p className="notice notice--error" role="alert">{error}</p>}
      {items === null && !error && <p className="muted" role="status">{t.common.loading}</p>}
      {items?.length === 0 && (
        <p className="empty">{t.bookmarks.empty}</p>
      )}
      <ul className="bookmarks">
        {items?.map((b) => (
          <li key={b.id} className="bookmark">
            <div className="bookmark__head">
              <p className="bookmark__kind">
                {t.bookmarks.savedOn(b.kind === "answer" ? t.bookmarks.answer : t.bookmarks.filing, formatDate(b.created_at))}
              </p>
              <button type="button" className="link-button" onClick={() => remove(b.id)}>
                {t.common.remove}
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
                          {t.bookmarks.filingLine(c.company_name, c.form_type, formatDate(c.filing_date))}
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
                    {t.bookmarks.filingLine(b.filing.company_name, b.filing.form_type, formatDate(b.filing.filing_date))}
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
