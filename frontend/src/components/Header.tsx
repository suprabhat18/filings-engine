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
        { href: "/", label: t.nav.search },
        { href: "/watchlist", label: t.nav.watchlist },
        { href: "/bookmarks", label: t.nav.bookmarks },
        { href: "/history", label: t.nav.history },
        { href: "/about", label: t.nav.about },
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
                  className="nav__link"
                  aria-current={pathname === item.href ? "page" : undefined}
                >
                  {item.label}
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
