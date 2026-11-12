"use client";

import { SessionProvider } from "next-auth/react";

// Re-checking the session every 5 minutes keeps the Google ID token in the
// cookie fresh while a tab is open.
export default function Providers({ children }: { children: React.ReactNode }) {
  return <SessionProvider refetchInterval={5 * 60}>{children}</SessionProvider>;
}
