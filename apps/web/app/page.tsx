"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { StateMessage } from "@ngsirs/design";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const { status } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (status === "ready") router.replace("/dashboard");
    else if (status !== "loading") router.replace("/login");
  }, [status, router]);
  return (
    <main id="main" className="center-page">
      <StateMessage state="loading" title="Opening the NGSIRS console" />
    </main>
  );
}
