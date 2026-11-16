"use client";

import { useState } from "react";
import { THEME_COOKIE, type Theme } from "@/i18n";
import { useI18n } from "@/i18n/I18nProvider";

/** Sun/moon button. Dark is the default; the choice is kept in a cookie. */
export default function ThemeToggle({ initialTheme }: { initialTheme: Theme }) {
  const { t } = useI18n();
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const next: Theme = theme === "dark" ? "light" : "dark";
  const label = theme === "dark" ? t.common.toLight : t.common.toDark;

  return (
    <button
      type="button"
      className="header-btn header-btn--icon"
      aria-label={label}
      title={label}
      onClick={() => {
        setTheme(next);
        document.documentElement.dataset.theme = next;
        document.cookie = `${THEME_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
      }}
    >
      {theme === "dark" ? (
        <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <circle cx="12" cy="12" r="4.5" />
          <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" />
        </svg>
      ) : (
        <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
        </svg>
      )}
    </button>
  );
}
