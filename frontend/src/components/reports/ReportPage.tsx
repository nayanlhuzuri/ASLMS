"use client";

/**
 * One report tab (design portal-reports, decisions 3-11): the parameters come from the URL, the defaults are filled
 * and the JSON report is requested at once; "Show report" writes the choices to the URL so a link, a bookmark or Back
 * restores the same report. A department-only reader without a department in the URL gets their first written there.
 * The Excel and PDF links carry exactly the parameters of the report shown and appear only once it has loaded; the
 * API writes the `report.exported` audit row, the screen writes nothing. A path the caller's catalogue does not hold
 * says so and requests nothing.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { EmptyState, ErrorBanner, Loading } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useDepartments, useMe, useReportCatalogue } from "@/lib/api/hooks";
import type { Report } from "@/lib/api/types";
import { tracksDepartment } from "@/lib/can";
import { istDay } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { exportUrl, reportParams, type ReportKey } from "@/lib/reports";

import { ReportForm } from "./ReportForm";
import { ReportView } from "./ReportView";
import s from "./reports.module.css";

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
  const loaded = query.isSuccess && !!query.data;

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
              <div className={s.actions} role="group" aria-label={T.reports.downloads}>
                <a className="button-link" href={exportUrl(reportKey, apiParams, "xlsx")} download>
                  {T.reports.downloadXlsx}
                </a>
                <a className="button-link" href={exportUrl(reportKey, apiParams, "pdf")} download>
                  {T.reports.downloadPdf}
                </a>
              </div>
              <p className="muted">{T.reports.downloadNote}</p>
            </div>
          }
        />
      ) : null}
      {reportKey === "data-health" ? (
        <p>
          {T.reports.liveHealthLine} <Link href="/data/health">{T.reports.liveHealth}</Link>
        </p>
      ) : null}
      {reportKey === "pending-actions" && tracksDepartment(me.data) ? (
        <p>
          {T.reports.departmentFilesLine} <Link href="/files/department">{T.reports.departmentFiles}</Link>
        </p>
      ) : null}
    </div>
  );
}
