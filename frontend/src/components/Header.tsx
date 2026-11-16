"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signIn, signOut, useSession } from "next-auth/react";
import type { Theme } from "@/i18n";
import { useI18n } from "@/i18n/I18nProvider";
import LanguageMenu from "./LanguageMenu";
import ThemeToggle from "./ThemeToggle";

export default function Header({ initialTheme }: { initialTheme: Theme }) {
  const { data: session, status } = useSession();
  const pathname = usePathname();
  const { t } = useI18n();
  const signedIn = status === "authenticated" && !session?.error;

  const nav = signedIn
    ? [
        { href: "/about", label: t.nav.home, icon: true },
        { href: "/", label: t.nav.search },
        { href: "/watchlist", label: t.nav.watchlist },
        { href: "/bookmarks", label: t.nav.bookmarks },
        { href: "/history", label: t.nav.history },
      ]
    : [{ href: pathname === "/" ? "#how" : "/#how", label: t.nav.about }];

  return (
    <header className="site-header">
      <div className="site-header__inner">
        <Link href="/" className="wordmark">
          Filings<span className="wordmark__rule" aria-hidden="true" />Research
        </Link>
        <nav aria-label={t.nav.main} className="site-nav">
          <ul className="nav">
            {nav.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={"icon" in item ? "nav__link nav__link--icon" : "nav__link"}
                  aria-current={pathname === item.href ? "page" : undefined}
                  title={"icon" in item ? item.label : undefined}
                >
                  {"icon" in item ? (
                    <>
                      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M3.5 10.5 12 3.5l8.5 7" />
                        <path d="M5.5 9v11h4.5v-6h4v6h4.5V9" />
                      </svg>
                      <span className="visually-hidden">{item.label}</span>
                    </>
                  ) : (
                    item.label
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="header-tools">
          <LanguageMenu />
          <ThemeToggle initialTheme={initialTheme} />
          {signedIn ? (
            <>
              <span className="account__name">{session?.user?.name ?? session?.user?.email}</span>
              <button type="button" className="header-btn" onClick={() => signOut({ callbackUrl: "/" })}>
                {t.common.signOut}
              </button>
            </>
          ) : (
            status !== "loading" && (
              <button type="button" className="btn btn--primary btn--small" onClick={() => signIn("google")}>
                {t.common.signIn}
              </button>
            )
          )}
        </div>
      </div>
    </header>
  );
}
