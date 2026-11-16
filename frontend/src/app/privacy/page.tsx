"use client";

import Link from "next/link";
import { useI18n } from "@/i18n/I18nProvider";

// Public page (no sign-in), linked from the footer and from Google's sign-in screen.
export default function PrivacyPage() {
  const { t } = useI18n();
  const p = t.privacy;
  return (
    <article className="stack legal">
      <h1 className="page-title">{p.title}</h1>
      <p className="muted">{p.updated}</p>
      <p>{p.intro}</p>

      <h2>{p.collectedTitle}</h2>
      <ul>
        {p.collected.map(([title, body]) => (
          <li key={title}>
            <strong>{title}</strong>: {body}
          </li>
        ))}
      </ul>

      <h2>{p.usedTitle}</h2>
      <p>{p.used}</p>

      <h2>{p.storedTitle}</h2>
      <p>{p.stored}</p>

      <h2>{p.choicesTitle}</h2>
      <ul>
        <li>
          <Link href="/history">{t.nav.history}</Link>: {p.clearHistory}
        </li>
        <li>
          <a href="https://github.com/suprabhat18/filings-engine/issues" target="_blank" rel="noreferrer">
            GitHub
          </a>
          : {p.deleteAll}
        </li>
      </ul>

      <h2>{p.adviceTitle}</h2>
      <p>{p.advice}</p>

      <p>
        <Link href="/">{p.back}</Link>
      </p>
    </article>
  );
}
