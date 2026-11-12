import { Suspense } from "react";
import RequireSignIn from "@/components/RequireSignIn";
import SearchView from "@/components/SearchView";

export default function SearchPage() {
  return (
    <RequireSignIn>
      <Suspense fallback={null}>
        <SearchView />
      </Suspense>
    </RequireSignIn>
  );
}
