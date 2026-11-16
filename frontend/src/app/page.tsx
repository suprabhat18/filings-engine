import { getServerSession } from "next-auth";
import { Suspense } from "react";
import Home from "@/components/Home";
import SearchView from "@/components/SearchView";
import { authOptions } from "@/lib/auth";

/**
 * Signed-in users land on search; everyone else sees the public homepage.
 * Decided on the server, so neither flashes before the other.
 */
export default async function IndexPage() {
  const session = await getServerSession(authOptions);
  if (!session || session.error) return <Home />;
  return (
    <Suspense fallback={null}>
      <SearchView />
    </Suspense>
  );
}
