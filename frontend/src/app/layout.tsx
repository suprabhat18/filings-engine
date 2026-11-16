import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import Footer from "@/components/Footer";
import Header from "@/components/Header";
import { fontHref, LANG_COOKIE, LOCALE, pickLang, type Theme, THEME_COOKIE } from "@/i18n";
import Providers from "./providers";
import "./globals.css";

const SITE_URL = process.env.NEXTAUTH_URL ?? "https://filings-engine.vercel.app";
const TITLE = "Filings Research";
// LinkedIn asks for at least 100 characters.
const DESCRIPTION =
  "Ask questions in any language about the SEC filings of S&P 100 companies and get answers that cite the exact passage they came from.";

// The Open Graph and Twitter tags are what LinkedIn, WhatsApp, Slack and X read to
// build a link preview card; the image comes from app/opengraph-image.tsx.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: TITLE,
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    url: "/",
    siteName: TITLE,
    title: `${TITLE}: ask the SEC filings, in any language`,
    description: DESCRIPTION,
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: `${TITLE}: ask the SEC filings, in any language`,
    description: DESCRIPTION,
  },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Language and theme are decided on the server, so the first paint is already
  // in the visitor's language and theme (no flash of English or of light mode).
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const lang = pickLang(cookieStore.get(LANG_COOKIE)?.value, headerStore.get("accept-language"));
  const theme: Theme = cookieStore.get(THEME_COOKIE)?.value === "light" ? "light" : "dark";
  const extraFont = fontHref(lang);

  return (
    <html lang={LOCALE[lang]} data-lang={lang} data-theme={theme}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap"
        />
        {extraFont && <link rel="stylesheet" href={extraFont} data-font={lang} />}
      </head>
      <body>
        <Providers lang={lang}>
          <Header initialTheme={theme} />
          <main className="page">{children}</main>
          <Footer />
        </Providers>
      </body>
    </html>
  );
}
