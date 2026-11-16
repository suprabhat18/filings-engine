"use client";

import { SessionProvider } from "next-auth/react";
import type { Lang } from "@/i18n";
import { I18nProvider } from "@/i18n/I18nProvider";

// Re-checking the session every 5 minutes keeps the Google ID token in the
// cookie fresh while a tab is open.
export default function Providers({ lang, children }: { lang: Lang; children: React.ReactNode }) {
  return (
    <SessionProvider refetchInterval={5 * 60}>
      <I18nProvider initialLang={lang}>{children}</I18nProvider>
    </SessionProvider>
  );
}
