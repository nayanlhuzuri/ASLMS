"use client";

/**
 * One report tab (design portal-reports, decisions 3-11): the parameters come from the URL, the defaults are filled
 * and the JSON report is requested at once; "Show report" writes the choices to the URL so a link, a bookmark or Back
 * restores the same report. A department-only reader without a department in the URL gets their first written there.
 * The Excel and PDF links carry exactly the parameters of the report shown and become links only once it has loaded
 * (in the frame's header, decision 26 of portal-ui-redesign); the
 * API writes the `report.exported` audit row, the screen writes nothing. A path the caller's catalogue does not hold
 * says so and requests nothing.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useContext, useEffect } from "react";

import { EmptyState, ErrorBanner, Loading } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useDepartments, useMe, useReportCatalogue } from "@/lib/api/hooks";
import type { Report } from "@/lib/api/types";
import { tracksDepartment } from "@/lib/can";
import { istDay } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { exportUrl, reportParams, scopeLabel, type ReportKey } from "@/lib/reports";

import { ReportForm } from "./ReportForm";
import { DownloadsSlot, ReportDownloads } from "./ReportsFrame";
import { ReportView } from "./ReportView";

export function ReportPage({ reportKey, params }: { reportKey: ReportKey; params: Params }) {
  const catalogue = useReportCatalogue();
  const me = useMe();
  const router = useRouter();
  const pathname = usePathname() ?? `/reports/${reportKey}`;
  const today = istDay();
  const item = catalogue.data?.reports.find((r) => r.key === reportKey);
  const firstDepartment =
    item && reportKey !== "data-health" && !item.scopes.includes("state") && !params.department
      ? item.departments[0]
      : undefined;
  const apiParams = reportParams(reportKey, params, today);
  const holders = useDepartments(reportKey === "pending-actions" && !!item);
  const query = useQuery({
    queryKey: ["reports", reportKey, apiParams],
    queryFn: () => api<Report>(`/reports/${reportKey}`, { query: apiParams }),
    staleTime: 60_000,
    enabled: !!item && !firstDepartment,
  });

  const setDownloads = useContext(DownloadsSlot);
  const loaded = query.isSuccess && !!query.data;
  const xlsx = exportUrl(reportKey, apiParams, "xlsx");
  const pdf = exportUrl(reportKey, apiParams, "pdf");
  // the frame's header offers the downloads of the report on screen only (decision 26: the Report template)
  useEffect(() => {
    setDownloads?.(loaded ? { xlsx, pdf } : null);
  }, [setDownloads, loaded, xlsx, pdf]);
  useEffect(() => () => setDownloads?.(null), [setDownloads]);

  useEffect(() => {
    if (firstDepartment) router.replace(pathname + queryString({ ...params, department: firstDepartment }));
  }, [firstDepartment, params, pathname, router]);

  if (catalogue.isPending) return <Loading />;
  if (!catalogue.data) return null; // the frame shows the catalogue's error
  if (!item) return <EmptyState>{T.reports.notAvailable}</EmptyState>;

  const error = query.error;
  const periodError = error instanceof ApiError && error.code === "bad_period" ? error.message : null;
  const departments = catalogue.data.departments;
  const holderList = holders.data?.departments ?? [];
  const holderNames: Record<string, string> = {};
  for (const d of holderList) holderNames[d.code] = d.name;

  return (
    <div className="stack">
      <ReportForm
        key={queryString(params)}
        reportKey={reportKey}
        item={item}
        departments={departments}
        holders={holderList}
        params={params}
        today={today}
        periodError={periodError}
        busy={query.isFetching}
        onShow={(next) => router.push(pathname + queryString(next))}
        onRefresh={() => void query.refetch()}
        summary={loaded ? <span>{T.reports.scopeLine(scopeLabel(query.data, departments))}</span> : null}
      />
      {firstDepartment || query.isPending ? (
        error ? null : (
          <p className="muted" role="status" aria-live="polite">
            {T.reports.preparing}
          </p>
        )
      ) : null}
      {error && !periodError ? <ErrorBanner error={error} onRetry={() => void query.refetch()} /> : null}
      {loaded ? (
        <ReportView
          report={query.data}
          departments={departments}
          holderNames={holderNames}
          actions={
            <div className="stack">
              {setDownloads ? null : <ReportDownloads downloads={{ xlsx, pdf }} />}
              <p className="muted">{T.reports.downloadNote}</p>
            </div>
          }
        />
      ) : null}
      {reportKey === "data-health" ? (
        <p>
          {T.reports.liveHealthLine} <Link href="/data/overview">{T.reports.liveHealth}</Link>
        </p>
      ) : null}
      {reportKey === "pending-actions" && tracksDepartment(me.data) ? (
        <p>
          {T.reports.departmentFilesLine} <Link href="/inbox/pending">{T.reports.departmentFiles}</Link>
        </p>
      ) : null}
    </div>
  );
}
