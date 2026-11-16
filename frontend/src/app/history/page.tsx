"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import RequireSignIn from "@/components/RequireSignIn";
import { api, type HistoryEntry } from "@/lib/api";
import { useI18n } from "@/i18n/I18nProvider";

function History() {
  const { t, formatDate, errorText } = useI18n();
  const [items, setItems] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    api<HistoryEntry[]>("history?limit=100")
      .then(setItems)
      .catch((e) => setError(errorText(e, "loadHistory")));
  }, []);

  const clear = async () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    try {
      await api("history", { method: "DELETE" });
      setItems([]);
    } catch (e) {
      setError(errorText(e, "clearHistory"));
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="stack">
      <div className="title-row">
        <h1 className="page-title">{t.history.title}</h1>
        {items && items.length > 0 && (
          <button type="button" className="btn btn--quiet" onClick={clear} onBlur={() => setConfirming(false)}>
            {confirming ? t.history.confirmClear : t.history.clear}
          </button>
        )}
      </div>
      {error && <p className="notice notice--error" role="alert">{error}</p>}
      {items === null && !error && <p className="muted" role="status">{t.common.loading}</p>}
      {items?.length === 0 && <p className="empty">{t.history.empty}</p>}
      <ul className="rule-list">
        {items?.map((h) => (
          <li key={h.id} className="history-item">
            <Link href={`/?q=${encodeURIComponent(h.query)}&run=1`} className="history-item__query">
              {h.query}
            </Link>
            <p className="history-item__meta">
              {formatDate(h.created_at)}
              {h.language && !h.language.toLowerCase().startsWith("en") ? t.history.inLanguage(h.language) : ""}
            </p>
            {h.answer_preview && <p className="history-item__preview">{h.answer_preview}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function HistoryPage() {
  return (
    <RequireSignIn>
      <History />
    </RequireSignIn>
  );
}
