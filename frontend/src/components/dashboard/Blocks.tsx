"use client";

/**
 * The Department and State views of the dashboard and the ticket panel (design reports-dashboards, decisions 9-11;
 * design portal-ui-redesign, decision 23: today's figures on the Dashboard template, their numbers as headline `Kpi`s,
 * their lists as panels), and the rest of the personal block folded under "More about my work". Counts are shown
 * exactly as the API gives them; a section the API returns as `null` is not shown; the portal computes nothing.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Badge, Card, CaseLink, DataTable, EmptyState, ErrorBanner, HeadLink, HearingDate, Kpi, Loading, OfficeName, SelectField } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useLabels, useMe } from "@/lib/api/hooks";
import { labelOf, serverLabel } from "@/lib/displayLabels";
import type {
  AlertCase,
  DashboardAlert,
  DashboardDepartment,
  DashboardFile,
  DashboardHearings,
  DashboardIndex,
  DashboardMe,
  DashboardState,
  Me,
  TicketCounts,
} from "@/lib/api/types";
import { can, canAny, canIn } from "@/lib/can";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { sourceLabel, statusLabel } from "@/lib/nextDates";
import { DATA_READERS, navFor } from "@/lib/routes";

import s from "./dashboard.module.css";

/** A case reference as a link to its case page (design portal-cases, decision 2). */
export function CaseRef({ value }: { value: AlertCase | null | undefined }) {
  return <CaseLink value={value} />;
}

/** A view's region: its title, the time of the figures and an optional link beside the heading. */
export function Block({
  title,
  sub,
  action,
  children,
}: {
  title: string;
  sub?: ReactNode;
  /** A link beside the heading (the reports of design portal-reports, decision 10). */
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={s.block} aria-label={title}>
      <div className={s.blockHead}>
        <h2>{title}</h2>
        <div className={s.blockSide}>
          {action}
          {sub ? <span className="muted">{sub}</span> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

export function HearingList({ hearings, caption }: { hearings: DashboardHearings; caption: string }) {
  if (hearings.items.length === 0) return <EmptyState>{T.dash.noHearings}</EmptyState>;
  return (
    <DataTable
      caption={caption}
      rows={hearings.items}
      rowKey={(h) => `${h.case.id}-${h.date}-${h.item_no ?? ""}`}
      columns={[
        // design next-hearing-highlight, decision 11: the date cell carries the band, so no separate badge column
        // design next-date-direct, decision 10: an around date says Around
        { key: "date", header: T.dash.date, cell: (h) => <HearingDate date={h.date} kind={h.approximate ? "around" : undefined} /> },
        { key: "case", header: T.dash.case, primary: true, cell: (h) => <CaseRef value={h.case} /> },
        { key: "court", header: T.dash.court, cell: (h) => h.court_no ?? "—" },
        { key: "item", header: T.dash.item, cell: (h) => h.item_no ?? "—" },
      ]}
    />
  );
}

/**
 * The files of a block. Empty, it shows `empty` when given and otherwise nothing, so a section a design keeps hidden
 * when empty (Cases with Me under More About My Work) stays hidden (design portal-ui-kit-fixes, decision 19).
 * The pending action is the server's label, as every other screen shows it (design dashboard-my-work-polish, decision
 * 9). `mergedDue` (only More About My Work) folds the Overdue column into one Due column (decision 10).
 */
function FileList({
  items,
  caption,
  empty,
  mergedDue,
}: {
  items: DashboardFile[];
  caption: string;
  empty?: ReactNode;
  mergedDue?: boolean;
}) {
  if (items.length === 0) return empty ? <>{empty}</> : null;
  return (
    <DataTable
      caption={caption}
      rows={items}
      rowKey={(f) => `${f.case.id}-${f.since}`}
      columns={[
        { key: "case", header: T.dash.case, primary: true, cell: (f) => <CaseRef value={f.case} /> },
        { key: "action", header: T.dash.action, cell: (f) => serverLabel(f.pending_action_label) },
        ...(mergedDue
          ? [{ key: "due", header: T.dash.due, cell: (f: DashboardFile) => <DueCell file={f} /> }]
          : [
              { key: "due", header: T.dash.due, cell: (f: DashboardFile) => formatDate(f.due_date) },
              {
                key: "overdue",
                header: T.dash.overdueCol,
                align: "right" as const,
                cell: (f: DashboardFile) => (f.overdue_days > 0 ? formatNumber(f.overdue_days) : "—"),
              },
            ]),
      ]}
    />
  );
}

/** One Due cell (design dashboard-my-work-polish, decision 10): the server's `overdue_days` decides. */
function DueCell({ file }: { file: DashboardFile }) {
  if (file.overdue_days > 0) {
    return (
      <Badge tone="danger" title={formatDate(file.due_date)}>
        {T.due.overdueBy(file.overdue_days)}
      </Badge>
    );
  }
  if (!file.due_date) return <span className="muted">{T.due.none}</span>;
  return <>{formatDate(file.due_date)}</>;
}

function Kpis({ children }: { children: ReactNode[] }) {
  const items = children.filter(Boolean);
  return (
    <div className={s.kpis} data-count={items.length}>
      {items}
    </div>
  );
}

export function DepartmentBlock({ data }: { data: DashboardDepartment }) {
  const me = useMe();
  const n = formatNumber;
  const rec = data.recommendations;
  const pending = data.pending_actions;
  const att = data.attention;
  const code = data.department.code;
  // design portal-reports, decision 10: a link, not a gate; the Reports screen asks the API
  const reports =
    canIn(me.data, code, "reports.department") || can(me.data, "reports.state") ? (
      <HeadLink href={`/reports/pending-cases?department=${encodeURIComponent(code)}`}>{T.reports.departmentReports}</HeadLink>
    ) : null;
  return (
    <Block title={`${T.dash.department}: ${data.department.name}`} sub={T.dash.generated(formatDateTime(data.generated_at))} action={reports}>
      <Kpis>
        {[
          rec ? (
            <Kpi key="rec" label={T.dash.recommendations} value={rec.high + rec.medium} sub={T.dash.recommendationsSub(n(rec.high), n(rec.medium))} />
          ) : null,
          <Kpi
            key="hearings"
            label={T.dash.hearings7}
            value={data.hearings.total}
            sub={T.dash.hearings48(n(data.hearings.critical))}
            tone={data.hearings.critical > 0 ? "danger" : undefined}
          />,
          pending ? (
            <Kpi
              key="pending"
              label={T.dash.pending}
              value={pending.held}
              sub={T.dash.overdue(n(pending.overdue))}
              tone={pending.overdue > 0 ? "danger" : undefined}
              href={`/inbox/department?department=${encodeURIComponent(code)}`}
            />
          ) : null,
          <Kpi key="claimed" label={T.dash.claimed} value={data.cases.claimed_active} sub={T.dash.claimedSub(n(data.cases.claimed_disposed))} />,
        ]}
      </Kpis>
      <div className={s.panels}>
        <Card title={T.dash.upcoming}>
          <HearingList hearings={data.hearings} caption={T.dash.upcoming} />
        </Card>
        <Card title={T.dash.attention}>
          <ul className={s.attention}>
            {att.next_dates_to_review !== null ? (
              <li>
                {/* design portal-next-dates, decision 13: a link, not a gate; the list shows the reader's own items */}
                {att.next_dates_to_review > 0 ? (
                  <Link href={`/alerts/next-dates?owner=${encodeURIComponent(code)}`}>{T.dash.nextDatesReview}</Link>
                ) : (
                  <span>{T.dash.nextDatesReview}</span>
                )}
                <strong>{n(att.next_dates_to_review)}</strong>
              </li>
            ) : null}
            {att.next_dates_differ !== null && att.next_dates_differ !== undefined ? (
              <li>
                {/* design next-date-direct, decision 5: to Department Cases with the shared filter */}
                {att.next_dates_differ > 0 ? (
                  <Link href={`/inbox/department?department=${encodeURIComponent(code)}&next_differs=true`}>{T.dash.nextDatesDiffer}</Link>
                ) : (
                  <span>{T.dash.nextDatesDiffer}</span>
                )}
                <strong>{n(att.next_dates_differ)}</strong>
              </li>
            ) : null}
            <li>
              {/* design close-case, decision 22: to Department Cases, Open, with the disposed filter */}
              {att.to_close > 0 ? (
                <Link href={`/inbox/department?department=${encodeURIComponent(code)}&case_status=disposed`}>{T.dash.readyToClose}</Link>
              ) : (
                <span>{T.dash.readyToClose}</span>
              )}
              <strong>{n(att.to_close)}</strong>
            </li>
            <li>
              <span>{T.dash.complianceSoon}</span>
              <strong>{n(att.compliance_due_soon)}</strong>
            </li>
            <li>
              <span>{T.dash.complianceOverdue}</span>
              <strong>{n(att.compliance_overdue)}</strong>
            </li>
            {rec ? (
              <li>
                <span>{T.dash.openTransfers}</span>
                <strong>{n(rec.transfers_in_open)}</strong>
              </li>
            ) : null}
          </ul>
          {att.recent_order_next_dates.length > 0 ? (
            <DataTable
              caption={T.dash.recentOrders}
              showCaption
              rows={att.recent_order_next_dates}
              rowKey={(o) => `${o.case.id}-${o.next_date}`}
              columns={[
                { key: "case", header: T.dash.case, primary: true, cell: (o) => <CaseRef value={o.case} /> },
                { key: "date", header: T.dash.date, cell: (o) => formatDate(o.next_date) },
                { key: "source", header: T.nd.colSource, cell: (o) => sourceLabel(o.source) },
                { key: "status", header: T.nd.colStatus, cell: (o) => statusLabel(o.review_status) },
              ]}
            />
          ) : null}
        </Card>
      </div>
      {/* the list of overdue files, sent only to readers with the tracking function or State scope (`items` null for
          the others, and the card hidden); empty, it says so inside the card instead of vanishing, and "none at all"
          only when the count is 0 (design portal-ui-kit-fixes, decision 19 and Deviations) */}
      {pending && pending.items ? (
        <Card title={T.dash.pending}>
          <FileList
            items={pending.items}
            caption={T.dash.pending}
            empty={
              <EmptyState compact>{pending.held === 0 ? T.dash.noPendingActions : T.dash.noOverdueActions}</EmptyState>
            }
          />
        </Card>
      ) : null}
      {data.custody_by_office ? (
        <Card title={T.dash.custody}>
          <DataTable
            caption={T.dash.custody}
            rows={data.custody_by_office}
            rowKey={(o) => o.office_code}
            columns={[
              {
                key: "office",
                header: T.dash.office,
                primary: true,
                cell: (o) => (
                  <>
                    <OfficeName code={o.office_code} name={o.office_name} />
                  </>
                ),
              },
              { key: "held", header: T.dash.held, align: "right", cell: (o) => n(o.held) },
              { key: "action", header: T.dash.withAction, align: "right", cell: (o) => n(o.with_pending_action) },
              { key: "overdue", header: T.dash.overdueCol, align: "right", cell: (o) => n(o.overdue) },
            ]}
          />
        </Card>
      ) : null}
    </Block>
  );
}

export function DepartmentSection({ departments }: { departments: DashboardIndex["departments"] }) {
  const [code, setCode] = useState(departments[0]?.code ?? "");
  const query = useQuery({
    queryKey: ["dashboard", "department", code],
    queryFn: () => api<DashboardDepartment>("/dashboard/department", { query: { department: code } }),
    enabled: !!code,
  });
  if (!code) return null;
  return (
    <div className="stack">
      {departments.length > 1 ? (
        <SelectField
          label={T.dash.chooseDepartment}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          options={departments.map((d) => ({ value: d.code, label: d.name }))}
        />
      ) : null}
      {query.isPending ? (
        <Block title={T.dash.department}>
          <Loading />
        </Block>
      ) : query.error || !query.data ? (
        <Block title={T.dash.department}>
          <p>{T.dash.blockFailed}</p>
          <ErrorBanner error={query.error} onRetry={() => query.refetch()} />
        </Block>
      ) : (
        <DepartmentBlock data={query.data} />
      )}
    </div>
  );
}

/** The type badge of an alert (design dashboard-my-work-polish, decisions 6 and 7): fixed meanings, never severity. */
function AlertTypeBadge({ alert }: { alert: DashboardAlert }) {
  if ((alert.kind === "hearing_due" || alert.kind === "listed_tomorrow") && alert.hearing_date) {
    return <HearingDate date={alert.hearing_date} showDate={false} label={T.dash.alertHearingBadge} />;
  }
  if (alert.kind === "recommendation") {
    const match = alert.band ? T.dash.matchBadges[alert.band] : undefined;
    if (!match) return <Badge>{T.dash.alertRecommendationBadge}</Badge>;
    return (
      <Badge tone="info" look={alert.band === "high" ? "solid" : "outline"} title={match}>
        {T.dash.alertRecommendationBadge}
        <span className="visually-hidden"> {match}</span>
      </Badge>
    );
  }
  return <Badge>{serverLabel(alert.kind_label)}</Badge>;
}

type OwnCases = DashboardMe["cases"][number];

/** A figure column of My Cases (decision 11): right-aligned in a fixed width, so the name takes the rest. */
function figure(key: string, header: string, value: (c: OwnCases) => number | null | undefined) {
  return {
    key,
    header,
    align: "right" as const,
    width: "var(--lead-w)",
    cell: (c: OwnCases) => formatNumber(value(c) ?? 0),
  };
}

/** The personal block's other figures, folded under "More about my work": own cases, alerts, files held, drafts. */
export function PersonalExtras({ data }: { data: DashboardMe }) {
  const n = formatNumber;
  const showCounsel = data.cases.some((c) => c.counsel_active !== null && c.counsel_active !== undefined);
  return (
    <div className="stack">
      <Kpis>
        {[
          <Kpi
            key="files"
            label={T.dash.files}
            value={data.files.held}
            sub={T.dash.filesSub(n(data.files.with_pending_action), n(data.files.overdue))}
            href="/inbox/with-me"
          />,
          <Kpi key="alerts" label={T.dash.myAlerts} value={data.alerts.unread} sub={T.dash.unread(n(data.alerts.unread))} href="/alerts" />,
          <Kpi key="drafts" label={T.dash.drafts} value={data.drafts} />,
        ]}
      </Kpis>
      {/* design dashboard-my-work-polish, decisions 1-4: three full-width cards, each with View All in its head; the
          tables keep their caption as their accessible name and show none, the card's heading names them */}
      {data.cases.length > 0 ? (
        <Card
          title={T.dash.ownCases}
          actions={
            <HeadLink href="/inbox/my-cases" srSuffix={T.dash.ownCases}>
              {T.viewAll}
            </HeadLink>
          }
        >
          <DataTable
            caption={T.dash.ownCases}
            rows={data.cases}
            rowKey={(c) => c.department_code}
            columns={[
              {
                key: "department",
                header: T.dash.department,
                primary: true,
                cell: (c) => <OfficeName code={c.department_code} name={c.department_name} />,
              },
              figure("allotted", T.dash.allotted, (c) => c.allotted_active),
              figure("disposed", T.dash.disposed, (c) => c.allotted_disposed),
              ...(showCounsel ? [figure("counsel", T.dash.counsel, (c) => c.counsel_active)] : []),
            ]}
          />
        </Card>
      ) : null}
      {data.files.items.length > 0 ? (
        <Card
          title={T.dash.files}
          actions={
            <HeadLink href="/inbox/with-me" srSuffix={T.dash.files}>
              {T.viewAll}
            </HeadLink>
          }
        >
          <FileList items={data.files.items} caption={T.dash.files} mergedDue />
        </Card>
      ) : null}
      <Card
        id="alerts"
        title={T.dash.myAlerts}
        actions={
          <HeadLink href="/alerts" srSuffix={T.dash.myAlerts}>
            {T.viewAll}
          </HeadLink>
        }
      >
        {data.alerts.items.length === 0 ? (
          <EmptyState compact>{T.dash.noAlerts}</EmptyState>
        ) : (
          <DataTable
            caption={T.dash.myAlerts}
            rows={data.alerts.items}
            rowKey={(a) => a.id}
            columns={[
              {
                key: "type",
                header: T.dash.alertCols.type,
                width: "calc(2 * var(--lead-w))",
                cell: (a) => <AlertTypeBadge alert={a} />,
              },
              {
                key: "case",
                header: T.dash.alertCols.case,
                cell: (a) => (a.case ? <CaseLink value={a.case} visible={a.case_visible} /> : "—"),
              },
              { key: "what", header: T.dash.alertCols.what, primary: true, cell: (a) => a.summary },
              {
                key: "raised",
                header: T.dash.alertCols.raised,
                cell: (a) =>
                  a.notified_at ? (
                    <time dateTime={a.notified_at} title={formatDateTime(a.notified_at)}>
                      {formatDate(a.notified_at)}
                    </time>
                  ) : (
                    "—"
                  ),
              },
            ]}
          />
        )}
      </Card>
    </div>
  );
}

export function StateBlock({ data }: { data: DashboardState }) {
  const me = useMe();
  const n = formatNumber;
  const nc = data.not_claimed;
  const reports = can(me.data, "reports.state") ? <Link href="/reports/pending-cases">{T.reports.dashboardLink}</Link> : null;
  // design data-collection-redesign, decision 5: a link only, no figure, so no extra query
  const collection = canAny(me.data, DATA_READERS) ? <Link href="/data/overview">{T.dash.dataCollectionLink}</Link> : null;
  const action =
    reports && collection ? (
      <span className="actions">
        {collection}
        {reports}
      </span>
    ) : (
      (collection ?? reports)
    );
  return (
    <Block title={T.dash.state} sub={T.dash.generated(formatDateTime(data.generated_at))} action={action}>
      <Kpis>
        {[
          <Kpi
            key="hearings"
            label={T.dash.stateHearings}
            value={data.hearings.total}
            sub={T.dash.hearings48(n(data.hearings.critical))}
            tone={data.hearings.critical > 0 ? "danger" : undefined}
          />,
          <Kpi key="overdue" label={T.dash.overdueFiles} value={data.overdue_actions.total} />,
          <Kpi key="compliance" label={T.dash.complianceSoon} value={data.compliance.due_soon} sub={T.dash.overdue(n(data.compliance.overdue))} />,
          <Kpi key="nc" label={T.dash.notClaimed} value={nc.active} />,
        ]}
      </Kpis>
      <Card title={T.dash.byDepartment}>
        <DataTable
          caption={T.dash.byDepartment}
          rows={[
            ...data.by_department.map((d) => ({ key: d.code, d })),
            { key: "__not_claimed", d: null as DashboardState["by_department"][number] | null },
          ]}
          rowKey={(r) => r.key}
          columns={[
            {
              key: "department",
              header: T.dash.department,
              primary: true,
              rowHeader: true,
              cell: ({ d }) =>
                d ? (
                  <>
                    <OfficeName code={d.code} name={d.name} />
                  </>
                ) : (
                  T.dash.notClaimed
                ),
            },
            { key: "claimed", header: T.dash.claimedCol, align: "right", cell: ({ d }) => n(d ? d.claimed_active : nc.active) },
            {
              key: "recommended",
              header: T.dash.recommendedCol,
              align: "right",
              cell: ({ d }) => n(d ? d.recommended_high + d.recommended_medium : nc.recommended),
            },
            { key: "hearings", header: T.dash.hearingsCol, align: "right", cell: ({ d }) => n(d ? d.hearings_7d : nc.hearing_7d) },
            { key: "pending", header: T.dash.pendingCol, align: "right", cell: ({ d }) => (d ? n(d.pending_actions) : "—") },
            { key: "overdue", header: T.dash.overdueCol, align: "right", cell: ({ d }) => (d ? n(d.overdue_actions) : "—") },
            {
              key: "compliance",
              header: T.dash.complianceCol,
              align: "right",
              cell: ({ d }) =>
                d ? (
                  <>
                    {n(d.compliance_due_soon)} / {n(d.compliance_overdue)}
                  </>
                ) : (
                  "—"
                ),
            },
          ]}
        />
      </Card>
      <div className={s.panels}>
        <Card title={T.dash.stateHearings}>
          <HearingList hearings={data.hearings} caption={T.dash.stateHearings} />
        </Card>
        <Card title={T.dash.overdueFiles}>
          <div className={s.panels}>
            {(
              [
                [T.dash.byHolder, data.overdue_actions.by_holder],
                [T.dash.byOwner, data.overdue_actions.by_owner],
              ] as const
            ).map(([caption, rows]) => (
              <DataTable
                key={caption}
                caption={caption}
                showCaption
                rows={[...rows]}
                rowKey={(r) => r.code}
                columns={[
                  { key: "code", header: T.dash.office, primary: true, rowHeader: true, cell: (r) => <OfficeName code={r.code} /> },
                  { key: "overdue", header: T.dash.overdueCol, align: "right", cell: (r) => n(r.overdue) },
                ]}
              />
            ))}
          </div>
        </Card>
      </div>
    </Block>
  );
}

/**
 * Admin tickets awaiting action (user-memberships decisions 15-20 and the owner's rule that these requests are
 * shown on the super admin's dashboard so they are addressed at the earliest). At the top of its view; counts only.
 */
export function TicketsBlock({ data }: { data: TicketCounts }) {
  const labels = useLabels();
  const kinds = Object.entries(data.open_by_kind).filter(([, n]) => n > 0);
  const departments = Object.entries(data.open_by_department).filter(([, n]) => n > 0);
  return (
    <Block title={T.dash.tickets} sub={<Link href="/admin/tickets">{T.dash.ticketsOpenList}</Link>}>
      <Kpis>
        {[
          <Kpi
            key="open"
            label={T.dash.ticketsOpen}
            value={data.open}
            sub={data.oldest_open_at ? T.dash.ticketsOldest(formatDate(data.oldest_open_at)) : undefined}
          />,
          data.departments_without_head != null ? (
            <Kpi key="nohead" label={T.dash.ticketsWithoutHead} value={data.departments_without_head} />
          ) : null,
        ]}
      </Kpis>
      {data.open === 0 ? <EmptyState compact>{T.dash.ticketsNone}</EmptyState> : null}
      {kinds.length > 0 || departments.length > 0 ? (
        <div className={s.panels}>
          {kinds.length > 0 ? (
            <DataTable
              caption={T.dash.ticketsByKind}
              showCaption
              rows={kinds}
              rowKey={([kind]) => kind}
              columns={[
                { key: "kind", header: T.tickets.kind, primary: true, rowHeader: true, cell: ([kind]) => labelOf(labels.data?.ticket_kinds, kind) },
                { key: "open", header: T.dash.ticketsOpenCol, align: "right", cell: ([, count]) => formatNumber(count) },
              ]}
            />
          ) : null}
          {departments.length > 0 ? (
            <DataTable
              caption={T.dash.ticketsByDepartment}
              showCaption
              rows={departments}
              rowKey={([code]) => code}
              columns={[
                { key: "department", header: T.dash.department, primary: true, rowHeader: true, cell: ([code]) => <OfficeName code={code} /> },
                { key: "open", header: T.dash.ticketsOpenCol, align: "right", cell: ([, count]) => formatNumber(count) },
              ]}
            />
          ) : null}
        </div>
      ) : null}
    </Block>
  );
}

export function NoDashboard({ me }: { me: Me }) {
  const entries = navFor(me).filter((e) => e.href !== "/");
  // design office-head-picker, decision 19: a login with no office yet (or none left) holds no function
  if ((me.memberships ?? []).filter((m) => m.is_active !== false).length === 0) {
    return (
      <Card title={T.dash.noOfficeTitle}>
        <p>{T.dash.noOfficeText}</p>
        <p>
          <Link href="/profile">{T.shell.profile}</Link>
        </p>
      </Card>
    );
  }
  return (
    <Card title={T.dash.noDashboard}>
      <p>{T.dash.noDashboardText}</p>
      <ul>
        {entries.map((e) => (
          <li key={e.key}>
            <Link href={e.href}>{e.label}</Link>
          </li>
        ))}
        <li>
          <Link href="/profile">{T.shell.profile}</Link>
        </li>
      </ul>
    </Card>
  );
}
