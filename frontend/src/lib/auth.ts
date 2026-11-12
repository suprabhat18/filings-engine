import type { NextAuthOptions } from "next-auth";
import type { JWT } from "next-auth/jwt";
import GoogleProvider from "next-auth/providers/google";

/**
 * Google sign-in. We keep Google's ID token (what the backend verifies) and a
 * refresh token inside NextAuth's encrypted cookie. ID tokens expire after an
 * hour, so they are refreshed shortly before expiry. The token is never sent
 * to browser JavaScript: the session object only says who is signed in.
 */

const REFRESH_MARGIN_MS = 5 * 60 * 1000;

export async function refreshIdToken(token: JWT): Promise<JWT> {
  if (!token.refreshToken) return { ...token, error: "RefreshTokenMissing" };
  try {
    const res = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: process.env.GOOGLE_CLIENT_ID ?? "",
        client_secret: process.env.GOOGLE_CLIENT_SECRET ?? "",
        grant_type: "refresh_token",
        refresh_token: token.refreshToken,
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.id_token) throw new Error(data.error ?? "refresh failed");
    return {
      ...token,
      idToken: data.id_token,
      expiresAt: Date.now() + data.expires_in * 1000,
      refreshToken: data.refresh_token ?? token.refreshToken,
      error: undefined,
    };
  } catch {
    return { ...token, error: "RefreshFailed" };
  }
}

export function needsRefresh(token: JWT): boolean {
  return !token.expiresAt || Date.now() > token.expiresAt - REFRESH_MARGIN_MS;
}

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
      authorization: {
        params: { scope: "openid email profile", access_type: "offline", prompt: "consent" },
      },
    }),
  ],
  session: { strategy: "jwt", maxAge: 30 * 24 * 60 * 60 },
  pages: { signIn: "/" },
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        return {
          ...token,
          idToken: account.id_token,
          refreshToken: account.refresh_token,
          expiresAt: (account.expires_at ?? 0) * 1000,
        };
      }
      return needsRefresh(token) ? refreshIdToken(token) : token;
    },
    async session({ session, token }) {
      session.error = token.error;
      return session;
    },
  },
};
