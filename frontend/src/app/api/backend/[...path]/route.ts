import { getToken } from "next-auth/jwt";
import { NextRequest, NextResponse } from "next/server";
import { needsRefresh, refreshIdToken } from "@/lib/auth";

/**
 * Forwards /api/backend/<path> to the FastAPI backend. For signed-in routes it adds
 * the user's Google ID token server-side; the browser only ever talks to this app.
 * The two public routes (homepage numbers and the free question) need no sign-in.
 */

// A search makes two Gemini calls plus a Vertex AI Search query, and the backend may be
// starting up from zero instances: allow up to a minute before Vercel gives up.
export const maxDuration = 60;

const ALLOWED = /^(me|search|companies|watchlist(\/filings|\/[A-Za-z0-9.\-]{1,10})?|bookmarks(\/[A-Za-z0-9]{1,64})?|history|public\/stats|public\/try)$/;
const PUBLIC = new Set(["public/stats", "public/try"]);

// A random id per browser, kept in an httpOnly cookie: limits free questions to one per browser.
const VISITOR_COOKIE = "fr_vid";
const VISITOR_ID = /^[A-Za-z0-9_-]{8,64}$/;

function error(status: number, code: string, detail: string) {
  return NextResponse.json({ detail, code }, { status });
}

/** The visitor's IP address as Vercel reports it (first entry of X-Forwarded-For). */
function clientIp(req: NextRequest): string {
  const forwarded = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || req.headers.get("x-real-ip") || "";
}

async function handler(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = path.join("/");
  if (!ALLOWED.test(target)) {
    return error(404, "not_found", "Not found");
  }

  const headers: Record<string, string> = {};
  let newVisitorId: string | null = null;

  if (PUBLIC.has(target)) {
    if (target === "public/try") {
      const secret = process.env.PROXY_SECRET;
      if (!secret) return error(503, "free_unavailable", "Free questions are not available.");
      let visitor = req.cookies.get(VISITOR_COOKIE)?.value ?? "";
      if (!VISITOR_ID.test(visitor)) {
        visitor = crypto.randomUUID().replaceAll("-", "");
        newVisitorId = visitor;
      }
      headers["X-Proxy-Secret"] = secret;
      headers["X-Visitor-Id"] = visitor;
      headers["X-Client-IP"] = clientIp(req);
    }
  } else {
    let token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET });
    if (!token?.idToken) {
      return error(401, "sign_in_required", "Sign in required");
    }
    if (needsRefresh(token)) token = await refreshIdToken(token);
    if (token.error || !token.idToken) {
      return error(401, "session_expired", "Your session expired. Sign in again.");
    }
    headers.Authorization = `Bearer ${token.idToken}`;
  }

  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
  const hasBody = !["GET", "HEAD", "DELETE"].includes(req.method);
  if (hasBody) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${backend}/${target}${req.nextUrl.search}`, {
      method: req.method,
      headers,
      body: hasBody ? await req.text() : undefined,
      cache: "no-store",
    });
  } catch {
    return error(502, "unreachable", "The search service is unreachable.");
  }

  const out =
    res.status === 204
      ? new NextResponse(null, { status: 204 })
      : new NextResponse(await res.text(), {
          status: res.status,
          headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
        });
  if (newVisitorId) {
    out.cookies.set(VISITOR_COOKIE, newVisitorId, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 365,
    });
  }
  return out;
}

export { handler as GET, handler as POST, handler as PUT, handler as DELETE };
