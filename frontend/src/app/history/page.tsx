"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import RequireSignIn from "@/components/RequireSignIn";
import { api, ApiError, formatDate, type HistoryEntry } from "@/lib/api";

function History() {
  const [items, setItems] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    api<HistoryEntry[]>("history?limit=100")
      .then(setItems)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load your history."));
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
      setError(e instanceof ApiError ? e.message : "Couldn't clear your history.");
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="stack">
      <div className="title-row">
        <h1 className="page-title">History</h1>
        {items && items.length > 0 && (
          <button type="button" className="btn btn--quiet" onClick={clear} onBlur={() => setConfirming(false)}>
            {confirming ? "Click again to clear all" : "Clear history"}
          </button>
        )}
      </div>
      {error && <p className="notice notice--error" role="alert">{error}</p>}
      {items === null && !error && <p className="muted" role="status">Loading…</p>}
      {items?.length === 0 && <p className="empty">Your searches will appear here.</p>}
      <ul className="rule-list">
        {items?.map((h) => (
          <li key={h.id} className="history-item">
            <Link href={`/?q=${encodeURIComponent(h.query)}&run=1`} className="history-item__query">
              {h.query}
            </Link>
            <p className="history-item__meta">
              {formatDate(h.created_at)}
              {h.language && !h.language.toLowerCase().startsWith("en") ? `, in ${h.language}` : ""}
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
