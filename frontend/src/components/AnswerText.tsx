"use client";

import { Fragment, type ReactNode } from "react";

/**
 * Renders Gemini's answer: paragraphs, "-"/"*" bullet lists, **bold**, and
 * citation markers like [1] or [2, 3] as buttons tied to the source margin.
 * Built as React nodes, so no model output is ever injected as raw HTML.
 */

type Props = {
  text: string;
  activeSource?: number | null;
  onCite?: (n: number) => void;
  onHover?: (n: number | null) => void;
  validNumbers?: Set<number>;
};

const TOKEN = /(\*\*[^*]+\*\*|\[\d+(?:\s*,\s*\d+)*\])/g;
const CITE = /^\[(\d+(?:\s*,\s*\d+)*)\]$/;
const LEADING_PUNCT = /^[.,;:!?)]+/;

export default function AnswerText({ text, activeSource, onCite, onHover, validNumbers }: Props) {
  /** Citation numbers in a token, or null if it isn't a real citation. */
  const citeNumbers = (part: string | undefined): number[] | null => {
    const m = part?.match(CITE);
    if (!m) return null;
    const nums = m[1].split(",").map((n) => Number(n.trim()));
    const shown = validNumbers ? nums.filter((n) => validNumbers.has(n)) : nums;
    return shown.length ? shown : null;
  };

  const inline = (line: string, key: string): ReactNode[] => {
    const parts = line.split(TOKEN).filter(Boolean);
    return parts.map((raw, i) => {
      const k = `${key}-${i}`;
      const nums = citeNumbers(raw);
      if (nums) {
        // Keep punctuation that follows a citation on the same line as it.
        const trailing = parts[i + 1]?.match(LEADING_PUNCT)?.[0] ?? "";
        return (
          <span key={k} className="cite-group">
            {nums.map((n) => (
              <button
                key={n}
                type="button"
                className="cite"
                aria-pressed={activeSource === n}
                aria-label={`Show source ${n}`}
                onClick={() => onCite?.(n)}
                onMouseEnter={() => onHover?.(n)}
                onMouseLeave={() => onHover?.(null)}
                onFocus={() => onHover?.(n)}
                onBlur={() => onHover?.(null)}
              >
                {n}
              </button>
            ))}
            {trailing}
          </span>
        );
      }
      const part = citeNumbers(parts[i - 1]) ? raw.replace(LEADING_PUNCT, "") : raw;
      if (!part) return null;
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={k}>{part.slice(2, -2)}</strong>;
      }
      return <Fragment key={k}>{part}</Fragment>;
    });
  };

  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flushList = () => {
    if (!list.length) return;
    const items = list;
    const n = blocks.length;
    blocks.push(
      <ul key={`ul-${n}`}>
        {items.map((item, i) => (
          <li key={i}>{inline(item, `li-${n}-${i}`)}</li>
        ))}
      </ul>,
    );
    list = [];
  };

  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      list.push(bullet[1]);
      continue;
    }
    flushList();
    if (line) blocks.push(<p key={`p-${blocks.length}`}>{inline(line, `p-${blocks.length}`)}</p>);
  }
  flushList();

  return <div className="answer__text">{blocks}</div>;
}
