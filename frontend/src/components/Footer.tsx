"use client";

import Link from "next/link";
import { useI18n } from "@/i18n/I18nProvider";

// Set NEXT_PUBLIC_LINKEDIN_URL in Vercel to show a LinkedIn link.
const LINKEDIN = process.env.NEXT_PUBLIC_LINKEDIN_URL ?? "";

export default function Footer() {
  const { t } = useI18n();
  return (
    <footer className="site-footer">
      <p>{t.footer.disclaimer}</p>
      <p className="site-footer__links">
        <span>{t.footer.builtBy}</span>
        <Link href="/privacy">{t.footer.privacy}</Link>
        <a href="https://github.com/suprabhat18/filings-engine" target="_blank" rel="noreferrer">
          GitHub
        </a>
        {LINKEDIN && (
          <a href={LINKEDIN} target="_blank" rel="noreferrer">
            LinkedIn
          </a>
        )}
      </p>
    </footer>
  );
}
