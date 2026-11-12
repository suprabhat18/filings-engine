import { getToken } from "next-auth/jwt";
import { NextRequest, NextResponse } from "next/server";
import { needsRefresh, refreshIdToken } from "@/lib/auth";

/**
 * Forwards /api/backend/<path> to the FastAPI backend, adding the signed-in
 * user's Google ID token server-side. The browser only ever talks to this app.
 */

const ALLOWED = /^(me|search|companies|watchlist(\/filings|\/[A-Za-z0-9.\-]{1,10})?|bookmarks(\/[A-Za-z0-9]{1,64})?|history)$/;

async function handler(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = path.join("/");
  if (!ALLOWED.test(target)) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }

  let token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET });
  if (!token?.idToken) {
    return NextResponse.json({ detail: "Sign in required" }, { status: 401 });
  }
  if (needsRefresh(token)) token = await refreshIdToken(token);
  if (token.error || !token.idToken) {
    return NextResponse.json({ detail: "Your session expired. Sign in again." }, { status: 401 });
  }

  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
  const hasBody = !["GET", "HEAD", "DELETE"].includes(req.method);
  let res: Response;
  try {
    res = await fetch(`${backend}/${target}${req.nextUrl.search}`, {
      method: req.method,
      headers: {
        Authorization: `Bearer ${token.idToken}`,
        ...(hasBody ? { "Content-Type": "application/json" } : {}),
      },
      body: hasBody ? await req.text() : undefined,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "The search service is unreachable." }, { status: 502 });
  }

  if (res.status === 204) return new NextResponse(null, { status: 204 });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}

export { handler as GET, handler as POST, handler as PUT, handler as DELETE };
