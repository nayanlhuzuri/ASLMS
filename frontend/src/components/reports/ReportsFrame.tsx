"use client";

/**
 * "Reports" (design portal-reports, decisions 1 and 2; plan §5.10): one tab per report the caller may run. The tabs
 * come from `GET /reports`, because the server already says which reports and scopes the caller has (`data-health`
 * only for `reports.state`); the frame waits for that call. On the Report template (design portal-ui-redesign, decision
 * 26): the choices on top, the results below, and the Excel and PDF downloads always in the header's secondary actions. Without a reports function the catalogue answers 403 and
 * the screen says no report is available. Showing a tab is convenience only: the API decides every report.
 */
import { usePathname, useRouter } from "next/navigation";
import { createContext, useEffect, useState, type ReactNode } from "react";

import { Button, buttonClass, EmptyState, ErrorBanner, Loading, PageHeader, Tabs } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import { useReportCatalogue } from "@/lib/api/hooks";
import type { ReportCatalogue } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { REPORT_TABS, type ReportTab } from "@/lib/reports";

import s from "./reports.module.css";

/** The Excel and PDF addresses of the report on screen (carrying exactly its parameters). */
export interface Downloads {
  xlsx: string;
  pdf: string;
}

/**
 * The Report template (design portal-ui-redesign, decision 26): the downloads sit in the page header's secondary
 * actions. The tab tells the frame what to offer through this setter; without a frame (a tab rendered alone) the tab
 * draws them itself.
 */
export const DownloadsSlot = createContext<((downloads: Downloads | null) => void) | null>(null);

/** Download Excel and Download PDF: links once the report has loaded, disabled buttons before. */
export function ReportDownloads({ downloads }: { downloads: Downloads | null }) {
  return (
    <div className={s.actions} role="group" aria-label={T.reports.downloads}>
      {downloads ? (
        <>
          <a className={buttonClass("secondary")} href={downloads.xlsx} download>
            {T.reports.downloadXlsx}
          </a>
          <a className={buttonClass("secondary")} href={downloads.pdf} download>
            {T.reports.downloadPdf}
          </a>
        </>
      ) : (
        <>
          <Button variant="secondary" disabled title={T.reports.downloadWait}>
            {T.reports.downloadXlsx}
          </Button>
          <Button variant="secondary" disabled title={T.reports.downloadWait}>
            {T.reports.downloadPdf}
          </Button>
        </>
      )}
    </div>
  );
}

export function reportTabsFor(catalogue: ReportCatalogue | undefined): ReportTab[] {
  const keys = new Set((catalogue?.reports ?? []).map((r) => r.key));
  return REPORT_TABS.filter((t) => keys.has(t.key));
}

export function ReportsFrame({ children }: { children: ReactNode }) {
  const catalogue = useReportCatalogue();
  const pathname = usePathname() ?? "/reports";
  const tabs = reportTabsFor(catalogue.data);
  const forbidden = catalogue.error instanceof ApiError && catalogue.error.status === 403;
  const [downloads, setDownloads] = useState<Downloads | null>(null);
  return (
    <div className="stack">
      <PageHeader
        title={T.reports.title}
        subtitle={tabs.length > 0 ? T.reports.subtitle : undefined}
        actions={tabs.length > 0 ? <ReportDownloads downloads={downloads} /> : undefined}
      />
      {catalogue.isPending ? <Loading /> : null}
      {forbidden ? <EmptyState>{T.reports.notAvailable}</EmptyState> : null}
      {catalogue.error && !forbidden ? <ErrorBanner error={catalogue.error} onRetry={() => catalogue.refetch()} /> : null}
      {tabs.length > 0 ? (
        <Tabs
          label={T.reports.tabs}
          items={tabs.map((t) => ({ href: t.href, label: t.label, active: pathname === t.href }))}
        />
      ) : null}
      {catalogue.data ? <DownloadsSlot.Provider value={setDownloads}>{children}</DownloadsSlot.Provider> : null}
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
