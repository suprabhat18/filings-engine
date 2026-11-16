"use client";

import { signIn, useSession } from "next-auth/react";
import { useI18n } from "@/i18n/I18nProvider";

/** Shows its children only to signed-in users; everyone else gets a sign-in prompt. */
export default function RequireSignIn({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();
  const { t } = useI18n();

  if (status === "loading") {
    return <p className="muted" role="status">{t.common.checkingSignIn}</p>;
  }

  if (status !== "authenticated" || session.error) {
    return (
      <section className="signin-card">
        <p>{session?.error ? t.common.sessionExpired : t.errors.sign_in_required}</p>
        <button type="button" className="btn btn--primary" onClick={() => signIn("google")}>
          {t.common.signInGoogle}
        </button>
      </section>
    );
  }

  return <>{children}</>;
}
