"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";

const NAV = [
  { href: "/", label: "Search" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/bookmarks", label: "Bookmarks" },
  { href: "/history", label: "History" },
];

export default function Header() {
  const { data: session, status } = useSession();
  const pathname = usePathname();

  return (
    <header className="site-header">
      <div className="site-header__inner">
        <Link href="/" className="wordmark">
          Filings<span className="wordmark__rule" aria-hidden="true" />Research
        </Link>
        {status === "authenticated" && (
          <>
            <nav aria-label="Main">
              <ul className="nav">
                {NAV.map((item) => (
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
            <div className="account">
              <span className="account__name">{session.user?.name ?? session.user?.email}</span>
              <button type="button" className="btn btn--quiet" onClick={() => signOut({ callbackUrl: "/" })}>
                Sign out
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  );
}
