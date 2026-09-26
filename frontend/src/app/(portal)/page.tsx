"use client";

import Link from "next/link";
import { HearingRow, HearingRows } from "@/components/case/CaseBits";
import { NeedsAttention } from "@/components/dashboard/NeedsAttention";
import s from "@/components/dashboard/dashboard.module.css";
import { useMe } from "@/components/shell/MeContext";
import { Card, CardHead, Kpi, KpiRow, PageHeader } from "@/components/ui/Layout";
import { Async, Empty, ErrorState, Loading } from "@/components/ui/States";
import { DataTable } from "@/components/ui/Table";
import { fmtLongDate, fmtNumber, todayIST } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { isDeptLead, isStateTier } from "@/lib/roles";
import type { Alert, CaseCard, DashboardSummary, Page } from "@/lib/types";

function Kpis({ d, kind }: { d: DashboardSummary; kind: "dept" | "state" | "officer" | "other" }) {
  if (kind === "dept") {
    return (
      <KpiRow>
        <Kpi
          label="Recommended cases"
          value={fmtNumber(d.recommended_total ?? 0)}
          tone="accent"
          note={`${fmtNumber(d.recommended_high ?? 0)} strong, awaiting your review`}
          href="/inbox"
        />
        <Kpi label="Hearings in 7 days" value={fmtNumber(d.hearings_week)} tone="critical" note={`${fmtNumber(d.hearings_48h)} within 48 hours`} href="/alerts" />
        <Kpi label="Open critical alerts" value={fmtNumber(d.open_critical_alerts)} tone="warning" note="hearings and actions due soon" href="/alerts?severity=critical" />
        <Kpi label="Cases held" value={fmtNumber(d.pending_cases)} note="pending before the High Court" href="/inbox?tab=claimed" />
      </KpiRow>
    );
  }
  if (kind === "state") {
    return (
      <KpiRow>
        <Kpi label="Pending cases" value={fmtNumber(d.pending_cases)} note={`${fmtNumber(d.cases_in_scope)} recorded in the portal`} />
        <Kpi label="Unclaimed, pending" value={fmtNumber(d.unclaimed_pending ?? 0)} tone="warning" note="not yet claimed by any department" href="/inbox?tab=unclaimed" />
        <Kpi label="Unclaimed, listed this week" value={fmtNumber(d.unclaimed_listed_week ?? 0)} tone="critical" note="hearing within 7 days, no owner" href="/search?ownership=unclaimed" />
        <Kpi label="Hearings in 7 days" value={fmtNumber(d.hearings_week)} tone="accent" note={`${fmtNumber(d.hearings_48h)} within 48 hours`} href="/alerts" />
      </KpiRow>
    );
  }
  if (kind === "officer") {
    return (
      <KpiRow>
        <Kpi label="Allotted to me" value={fmtNumber(d.allotted_to_me ?? 0)} tone="accent" note="cases in your charge" href="/search?mine=true" />
        <Kpi label="Hearings in 7 days" value={fmtNumber(d.hearings_week)} tone="critical" note={`${fmtNumber(d.hearings_48h)} within 48 hours`} href="/alerts" />
        <Kpi label="Open critical alerts" value={fmtNumber(d.open_critical_alerts)} tone="warning" note="hearings and actions due soon" href="/alerts?severity=critical" />
        <Kpi label="Cases I can see" value={fmtNumber(d.pending_cases)} note="pending before the High Court" />
      </KpiRow>
    );
  }
  return (
    <KpiRow>
      <Kpi label="Pending cases" value={fmtNumber(d.pending_cases)} note="within your access" href="/search?mine=true" />
      <Kpi label="Hearings in 7 days" value={fmtNumber(d.hearings_week)} tone="critical" note={`${fmtNumber(d.hearings_48h)} within 48 hours`} href="/alerts" />
      <Kpi label="Open critical alerts" value={fmtNumber(d.open_critical_alerts)} tone="warning" href="/alerts?severity=critical" />
      <Kpi label="Unread notifications" value={fmtNumber(d.unread_notifications)} href="/notifications" />
    </KpiRow>
  );
}

export default function DashboardPage() {
  const { me } = useMe();
  const summary = useApi<DashboardSummary>("/dashboard");
  const hearings = useApi<CaseCard[]>("/dashboard/hearings", { days: 7 });
  const alerts = useApi<Page<Alert>>("/alerts", { status: "open", size: 6 });

  const kind = isDeptLead(me) ? "dept" : isStateTier(me) ? "state" : me.role === "dept_officer" || me.role === "referral_reviewer" ? "officer" : "other";
  const title = me.department?.name ?? me.office.name;
  const sub = `${fmtLongDate(todayIST())} · ${kind === "state" ? "State dashboard" : kind === "dept" ? "Department dashboard" : "My dashboard"}`;

  return (
    <>
      <PageHeader title={title} sub={sub} />
      <Async state={summary} loadingLabel="Loading figures">
        {(d) => <Kpis d={d} kind={kind} />}
      </Async>
      {summary.data?.undelivered_email ? (
        <ErrorState message={`${fmtNumber(summary.data.undelivered_email)} e-mail notifications to you could not be delivered. Check your e-mail address in Settings.`} />
      ) : null}
      <div className={s.columns}>
        <div className={s.wide} style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <Card labelledBy="upcoming-h">
            <CardHead
              id="upcoming-h"
              title={kind === "officer" ? "My upcoming hearings" : "Upcoming hearings"}
              actions={
                <Link href="/alerts" className={s.headLink}>
                  Open calendar
                </Link>
              }
            />
            {hearings.error ? (
              <ErrorState message={hearings.error} onRetry={hearings.reload} />
            ) : !hearings.data ? (
              <Loading label="Loading hearings" />
            ) : hearings.data.length === 0 ? (
              <Empty title="No hearings in the next 7 days">Cases within your access with a next date this week appear here.</Empty>
            ) : (
              <HearingRows>
                {hearings.data.map((c) => (
                  <HearingRow key={c.id} c={c} />
                ))}
              </HearingRows>
            )}
          </Card>
          {kind === "state" && summary.data?.by_department ? (
            <Card labelledBy="bydept-h">
              <CardHead id="bydept-h" title="Pending cases by department" actions={<Link href="/reports" className={s.headLink}>Reports</Link>} />
              {summary.data.by_department.length === 0 ? (
                <Empty title="No department has claimed a case yet" />
              ) : (
                <DataTable
                  bare
                  caption="Pending cases by department"
                  rows={summary.data.by_department}
                  rowKey={(r) => r.office_id}
                  columns={[
                    { key: "code", header: "Code", mono: true, render: (r) => r.code },
                    { key: "name", header: "Department", render: (r) => r.name },
                    { key: "pending", header: "Pending", num: true, render: (r) => fmtNumber(r.pending) },
                  ]}
                />
              )}
            </Card>
          ) : null}
          {kind === "dept" && summary.data?.by_unit && summary.data.by_unit.length > 0 ? (
            <Card labelledBy="byunit-h">
              <CardHead id="byunit-h" title="Cases held, by unit" />
              <DataTable
                bare
                caption="Cases held by unit"
                rows={summary.data.by_unit}
                rowKey={(r) => r.unit}
                columns={[
                  { key: "unit", header: "Unit", mono: true, render: (r) => r.unit },
                  { key: "cases", header: "Cases", num: true, render: (r) => fmtNumber(r.cases) },
                ]}
              />
            </Card>
          ) : null}
        </div>
        <div className={s.narrow}>
          <Card labelledBy="attention-h">
            <CardHead id="attention-h" title="Needs attention" />
            {alerts.error ? (
              <ErrorState message={alerts.error} onRetry={alerts.reload} />
            ) : !alerts.data || !summary.data ? (
              <Loading />
            ) : (
              <NeedsAttention
                recommended={summary.data.recommended_total}
                recommendedHigh={summary.data.recommended_high}
                transfersIn={summary.data.transfers_incoming}
                alerts={alerts.data.items}
              />
            )}
            {alerts.data && alerts.data.total > alerts.data.items.length ? (
              <Link href="/alerts" className={s.headLink}>
                All {fmtNumber(alerts.data.total)} open alerts
              </Link>
            ) : null}
          </Card>
        </div>
      </div>
    </>
  );
}
