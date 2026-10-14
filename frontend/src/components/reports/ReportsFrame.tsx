"use client";

/**
 * "Reports" (design portal-reports, decisions 1 and 2; plan §5.10): one tab per report the caller may run. The tabs
 * come from `GET /reports`, because the server already says which reports and scopes the caller has (`data-health`
 * only for `reports.state`); the frame waits for that call. Without a reports function the catalogue answers 403 and
 * the screen says no report is available. Showing a tab is convenience only: the API decides every report.
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { EmptyState, ErrorBanner, Loading, Tabs } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import { useReportCatalogue } from "@/lib/api/hooks";
import type { ReportCatalogue } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { REPORT_TABS, type ReportTab } from "@/lib/reports";

export function reportTabsFor(catalogue: ReportCatalogue | undefined): ReportTab[] {
  const keys = new Set((catalogue?.reports ?? []).map((r) => r.key));
  return REPORT_TABS.filter((t) => keys.has(t.key));
}

export function ReportsFrame({ children }: { children: ReactNode }) {
  const catalogue = useReportCatalogue();
  const pathname = usePathname() ?? "/reports";
  const tabs = reportTabsFor(catalogue.data);
  const forbidden = catalogue.error instanceof ApiError && catalogue.error.status === 403;
  return (
    <div className="stack">
      <h1>{T.reports.title}</h1>
      {catalogue.isPending ? <Loading /> : null}
      {forbidden ? <EmptyState>{T.reports.notAvailable}</EmptyState> : null}
      {catalogue.error && !forbidden ? <ErrorBanner error={catalogue.error} onRetry={() => catalogue.refetch()} /> : null}
      {tabs.length > 0 ? (
        <Tabs
          label={T.reports.tabs}
          items={tabs.map((t) => ({ href: t.href, label: t.label, active: pathname === t.href }))}
        />
      ) : null}
      {catalogue.data ? children : null}
    </div>
  );
}

/** `/reports`: the first tab the caller may run. */
export function ReportsIndex() {
  const catalogue = useReportCatalogue();
  const router = useRouter();
  const first = reportTabsFor(catalogue.data)[0];
  useEffect(() => {
    if (first) router.replace(first.href);
  }, [first, router]);
  if (catalogue.isPending || first) return <Loading />;
  if (!catalogue.data) return null;
  return <EmptyState>{T.reports.noReports}</EmptyState>;
}
