"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError } from "@/lib/api";
import { DICTS, type Dict, fontHref, type Lang, LANG_COOKIE, LOCALE } from "./index";

type ErrorKey = {
  [K in keyof Dict["errors"]]: Dict["errors"][K] extends string ? K : never;
}[keyof Dict["errors"]];

type I18n = {
  lang: Lang;
  t: Dict;
  setLang: (lang: Lang) => void;
  formatDate: (iso: string) => string;
  /** The translated message for an error from the API, else `fallback`. */
  errorText: (e: unknown, fallback: ErrorKey) => string;
};

const I18nContext = createContext<I18n | null>(null);

function loadFont(lang: Lang) {
  const href = fontHref(lang);
  if (!href || document.querySelector(`link[data-font="${lang}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.font = lang;
  document.head.appendChild(link);
}

export function I18nProvider({ initialLang, children }: { initialLang: Lang; children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    // A cookie (not localStorage), so the server renders the right language next time.
    document.cookie = `${LANG_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
  }, []);

  useEffect(() => {
    document.documentElement.lang = LOCALE[lang];
    document.documentElement.dataset.lang = lang;
    loadFont(lang);
  }, [lang]);

  const value = useMemo<I18n>(() => {
    const t = DICTS[lang];
    return {
      lang,
      t,
      setLang,
      formatDate: (iso: string) => {
        const d = new Date(iso.length === 10 ? `${iso}T12:00:00Z` : iso);
        return Number.isNaN(d.getTime())
          ? iso
          : d.toLocaleDateString(LOCALE[lang], { year: "numeric", month: "short", day: "numeric" });
      },
      errorText: (e: unknown, fallback: ErrorKey) => {
        if (e instanceof ApiError) {
          const known = e.code ? (t.errors as Record<string, unknown>)[e.code] : undefined;
          if (typeof known === "string") return known;
          return e.status >= 500 || !e.message ? t.errors.generic(e.status) : e.message;
        }
        return t.errors[fallback];
      },
    };
  }, [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>");
  return ctx;
}
