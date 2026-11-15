import { ImageResponse } from "next/og";

// The preview image shown when a link to the site is shared (LinkedIn, WhatsApp,
// Slack, X...). Generated once at build time; it mirrors the landing page.
export const alt =
  "Filings Research: ask about S&P 100 SEC filings in any language, with answers that cite their sources";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const PAPER = "#f4f6f8";
const SHEET = "#ffffff";
const INK = "#1a2332";
const SLATE = "#566173";
const RULE = "#d4dbe3";
const HIGHLIGHT = "#ffe47a";
const ANSWER =
  "La mayor parte del hardware de Apple se fabrica con socios externos en China, India y otros países de Asia";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          background: PAPER,
          padding: "64px 72px",
          color: INK,
          fontFamily: "sans-serif",
        }}
      >
        {/* Left: brand, headline, pitch */}
        <div style={{ display: "flex", flexDirection: "column", width: 560, paddingRight: 40 }}>
          <div style={{ display: "flex", alignItems: "center", fontSize: 30, fontWeight: 700 }}>
            Filings
            <div
              style={{
                width: 34,
                height: 14,
                background: HIGHLIGHT,
                margin: "0 12px",
                transform: "skewX(-12deg)",
              }}
            />
            Research
          </div>
          <div style={{ fontSize: 76, fontWeight: 700, marginTop: 70, letterSpacing: -2 }}>
            Ask the filings.
          </div>
          <div style={{ fontSize: 30, lineHeight: 1.4, color: SLATE, marginTop: 24 }}>
            Questions in any language, answered from the SEC filings of S&amp;P 100 companies.
            Every claim cites its source.
          </div>
          <div style={{ fontSize: 24, color: SLATE, marginTop: "auto" }}>filings-engine.vercel.app</div>
        </div>

        {/* Right: an example answer with its highlighted source */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            flex: 1,
            background: SHEET,
            border: `2px solid ${RULE}`,
            padding: "34px 36px",
            boxShadow: "0 12px 40px rgba(26,35,50,0.12)",
          }}
        >
          <div style={{ fontSize: 22, color: SLATE }}>¿Qué riesgos de cadena de suministro menciona Apple?</div>
          {/* Each word is its own flex item, so the citation marker wraps like a word
              and stays right after "Asia" (the image renderer has no inline layout). */}
          <div style={{ display: "flex", flexWrap: "wrap", fontSize: 27, lineHeight: 1.45, marginTop: 20 }}>
            {ANSWER.split(" ").map((word, i) => (
              <span key={i} style={{ marginRight: 7 }}>
                {word}
              </span>
            ))}
            <span
              style={{
                display: "flex",
                alignItems: "center",
                background: HIGHLIGHT,
                fontSize: 18,
                padding: "0 7px",
                height: 26,
                marginTop: 6,
                borderRadius: 3,
              }}
            >
              1
            </span>
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              background: HIGHLIGHT,
              padding: "16px 20px",
              marginTop: "auto",
            }}
          >
            <div style={{ fontSize: 19, fontWeight: 700 }}>1  Apple Inc. 10-K · Item 1A. Risk Factors</div>
            <div style={{ fontSize: 19, marginTop: 8, lineHeight: 1.4 }}>
              “Substantially all of the Company’s hardware products are manufactured by outsourcing
              partners…”
            </div>
          </div>
        </div>
      </div>
    ),
    size,
  );
}
