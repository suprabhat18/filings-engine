"use client";

import { useEffect, useRef, useState } from "react";
import { DICTS, ENGLISH_NAMES, LANGS } from "@/i18n";
import { useI18n } from "@/i18n/I18nProvider";

/** Wikipedia-style "文A" language menu: switches the whole site in place. */
export default function LanguageMenu() {
  const { lang, t, setLang } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on a click outside or Escape.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="lang-menu" ref={ref}>
      <button
        type="button"
        className="header-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${t.common.language}: ${DICTS[lang].langName}`}
        onClick={() => setOpen(!open)}
      >
        <span aria-hidden="true" className="lang-menu__glyph">文A</span>
        <span className="lang-menu__current">{DICTS[lang].langName}</span>
        <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M2.5 4.5 6 8l3.5-3.5" />
        </svg>
      </button>
      {open && (
        <div className="lang-menu__list" role="menu">
          {LANGS.map((code) => (
            <button
              key={code}
              type="button"
              role="menuitemradio"
              aria-checked={code === lang}
              lang={code}
              className="lang-menu__item"
              data-font={code}
              onClick={() => {
                setLang(code);
                setOpen(false);
              }}
            >
              <span>{DICTS[code].langName}</span>
              <span className="lang-menu__en" lang="en">{ENGLISH_NAMES[code]}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
