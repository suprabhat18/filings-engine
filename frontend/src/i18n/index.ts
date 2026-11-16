import de from "./de";
import en, { type Dict } from "./en";
import es from "./es";
import hi from "./hi";
import ja from "./ja";
import zh from "./zh";

export type { Dict };

export const LANGS = ["en", "zh", "de", "ja", "es", "hi"] as const;
export type Lang = (typeof LANGS)[number];

export const DICTS: Record<Lang, Dict> = { en, zh, de, ja, es, hi };

/** English names, shown next to each language in the menu. */
export const ENGLISH_NAMES: Record<Lang, string> = {
  en: "English", zh: "Chinese", de: "German", ja: "Japanese", es: "Spanish", hi: "Hindi",
};

/** BCP 47 tags for <html lang> and date formatting. */
export const LOCALE: Record<Lang, string> = {
  en: "en-US", zh: "zh-CN", de: "de-DE", ja: "ja-JP", es: "es-ES", hi: "hi-IN",
};

/** Scripts our main fonts lack get a matching Noto font, loaded only when needed. */
export const NOTO_FONT: Partial<Record<Lang, string>> = {
  zh: "Noto+Sans+SC:wght@400;500;600",
  ja: "Noto+Sans+JP:wght@400;500;600",
  hi: "Noto+Sans+Devanagari:wght@400;500;600",
};

export const LANG_COOKIE = "lang";
export const THEME_COOKIE = "theme";
export type Theme = "dark" | "light";

export function isLang(value: unknown): value is Lang {
  return typeof value === "string" && (LANGS as readonly string[]).includes(value);
}

/** Pick a language from a saved cookie, else the browser's Accept-Language header. */
export function pickLang(cookie: string | undefined, acceptLanguage: string | null): Lang {
  if (isLang(cookie)) return cookie;
  for (const part of (acceptLanguage ?? "").split(",")) {
    const code = part.split(";")[0].trim().toLowerCase().split("-")[0];
    if (isLang(code)) return code;
  }
  return "en";
}

export function fontHref(lang: Lang): string | null {
  const family = NOTO_FONT[lang];
  return family ? `https://fonts.googleapis.com/css2?family=${family}&display=swap` : null;
}
