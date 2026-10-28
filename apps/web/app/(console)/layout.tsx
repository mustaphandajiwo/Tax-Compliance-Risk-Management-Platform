"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { StateMessage } from "@ngsirs/design";
import { AppShell } from "@/components/AppShell";
import { ErrorNotice } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function ConsoleLayout({ children }: { children: ReactNode }) {
  const { status, error, signOut } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "signed_out") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [status, router, pathname]);

  if (status === "ready") return <AppShell>{children}</AppShell>;
  return (
    <main id="main" className="center-page">
      {status === "error" ? (
        <div className="stack">
          <ErrorNotice error={error} />
          <button type="button" className="btn" onClick={signOut}>
            Return to sign-in
          </button>
        </div>
      ) : (
        <StateMessage state="loading" title="Checking your session" />
      )}
    </main>
  );
}
