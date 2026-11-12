/** Typed calls to the backend, through this app's /api/backend proxy. */

export type Filters = { tickers: string[]; form_types: string[]; from_year: number | null };

export type Citation = {
  n: number;
  cited: boolean;
  doc_id: string;
  content: string;
  title: string;
  section?: string;
  filing_id: string;
  ticker: string;
  company_name: string;
  form_type: string;
  filing_date: string;
  source_url: string;
};

export type SearchResult = {
  query: string;
  language: string;
  search_query: string;
  filters: Filters & { inferred: boolean };
  answer: string;
  citations: Citation[];
  history_id: string | null;
};

export type Company = { ticker: string; name: string; cik?: number };
export type WatchItem = { ticker: string; name: string; added_at: string };
export type Filing = {
  filing_id: string;
  ticker: string;
  company_name: string;
  form_type: string;
  filing_date: string;
  source_url: string;
  index_url: string;
};
export type Bookmark = {
  id: string;
  created_at: string;
  kind: "answer" | "filing";
  title: string;
  query?: string | null;
  answer?: string | null;
  citations: Citation[];
  filing?: Filing | null;
  note?: string | null;
};
export type HistoryEntry = {
  id: string;
  query: string;
  language: string;
  filters: Filters & { inferred: boolean };
  answer_preview: string;
  created_at: string;
};
export type Me = {
  user: { uid: string; email: string; name: string; picture: string };
  searches_today: number;
  daily_quota: number;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`/api/backend/${path}`, {
    method: init?.method ?? "GET",
    headers: init?.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string"
        ? data.detail
        : `Something went wrong (error ${res.status}). Try again.`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const FORM_TYPES = ["10-K", "10-Q", "8-K"] as const;

export function formatDate(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00Z` : iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function filingFromCitation(c: Citation): Filing {
  return {
    filing_id: c.filing_id,
    ticker: c.ticker,
    company_name: c.company_name,
    form_type: c.form_type,
    filing_date: c.filing_date,
    source_url: c.source_url,
    index_url: "",
  };
}
