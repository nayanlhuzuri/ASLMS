"use client";

import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { MeProvider } from "@/components/shell/MeContext";
import { ErrorState, Loading } from "@/components/ui/States";

export default function PortalLayout({ children }: { children: ReactNode }) {
  return (
    <MeProvider
      fallback={(error, retry) => (
        <div style={{ maxWidth: 520, margin: "80px auto", padding: "0 16px" }}>
          {error ? <ErrorState message={error} onRetry={retry} /> : <Loading label="Opening the portal" center />}
        </div>
      )}
    >
      <AppShell>{children}</AppShell>
    </MeProvider>
  );
}
