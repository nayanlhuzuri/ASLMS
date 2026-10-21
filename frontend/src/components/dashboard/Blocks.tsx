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

import { Badge, Card, CaseLink, EmptyState, ErrorBanner, Kpi, Loading, numCell, SelectField, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import { labelOf, useLabels, useMe } from "@/lib/api/hooks";
import type {
  AlertCase,
  DashboardDepartment,
  DashboardFile,
  DashboardHearings,
  DashboardIndex,
  DashboardMe,
  DashboardState,
  Me,
  TicketCounts,
} from "@/lib/api/types";
import { can, canIn } from "@/lib/can";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { sourceLabel, statusLabel } from "@/lib/nextDates";
import { navFor } from "@/lib/routes";

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
    <Table caption={caption}>
      <thead>
        <tr>
          <th scope="col">{T.dash.date}</th>
          <th scope="col">{T.dash.case}</th>
          <th scope="col">{T.dash.court}</th>
          <th scope="col">{T.dash.item}</th>
          <th scope="col">
            <span className="visually-hidden">{T.dash.within48}</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {hearings.items.map((h) => (
          <tr key={`${h.case.id}-${h.date}-${h.item_no ?? ""}`}>
            <td>{formatDate(h.date)}</td>
            <td>
              <CaseRef value={h.case} />
            </td>
            <td>{h.court_no ?? "—"}</td>
            <td>{h.item_no ?? "—"}</td>
            <td>{h.critical ? <Badge tone="danger">{T.dash.within48}</Badge> : <Badge>{T.dash.thisWeek}</Badge>}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function FileList({ items, caption }: { items: DashboardFile[]; caption: string }) {
  if (items.length === 0) return null;
  return (
    <Table caption={caption}>
      <thead>
        <tr>
          <th scope="col">{T.dash.case}</th>
          <th scope="col">{T.dash.action}</th>
          <th scope="col">{T.dash.due}</th>
          <th scope="col" className={numCell}>
            {T.dash.overdueCol}
          </th>
        </tr>
      </thead>
      <tbody>
        {items.map((f) => (
          <tr key={`${f.case.id}-${f.since}`}>
            <td>
              <CaseRef value={f.case} />
            </td>
            <td>{f.pending_action}</td>
            <td>{formatDate(f.due_date)}</td>
            <td className={numCell}>{f.overdue_days > 0 ? formatNumber(f.overdue_days) : "—"}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
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
      <Link href={`/reports/pending-cases?department=${encodeURIComponent(code)}`}>{T.reports.departmentReports}</Link>
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
            <Table caption={T.dash.recentOrders}>
              <thead>
                <tr>
                  <th scope="col">{T.dash.case}</th>
                  <th scope="col">{T.dash.date}</th>
                  <th scope="col">{T.nd.colSource}</th>
                  <th scope="col">{T.nd.colStatus}</th>
                </tr>
              </thead>
              <tbody>
                {att.recent_order_next_dates.map((o) => (
                  <tr key={`${o.case.id}-${o.next_date}`}>
                    <td>
                      <CaseRef value={o.case} />
                    </td>
                    <td>{formatDate(o.next_date)}</td>
                    <td>{sourceLabel(o.source)}</td>
                    <td>{statusLabel(o.review_status)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}
        </Card>
      </div>
      {pending?.items && pending.items.length > 0 ? (
        <Card title={T.dash.pending}>
          <FileList items={pending.items} caption={T.dash.pending} />
        </Card>
      ) : null}
      {data.custody_by_office ? (
        <Card title={T.dash.custody}>
          <Table caption={T.dash.custody}>
            <thead>
              <tr>
                <th scope="col">{T.dash.office}</th>
                <th scope="col" className={numCell}>
                  {T.dash.held}
                </th>
                <th scope="col" className={numCell}>
                  {T.dash.withAction}
                </th>
                <th scope="col" className={numCell}>
                  {T.dash.overdueCol}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.custody_by_office.map((o) => (
                <tr key={o.office_code}>
                  <td>
                    {o.office_name} <span className="mono muted">{o.office_code}</span>
                  </td>
                  <td className={numCell}>{n(o.held)}</td>
                  <td className={numCell}>{n(o.with_pending_action)}</td>
                  <td className={numCell}>{n(o.overdue)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
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
            href="/files/mine"
          />,
          <Kpi key="alerts" label={T.dash.myAlerts} value={data.alerts.unread} sub={T.dash.unread(n(data.alerts.unread))} href="/alerts" />,
          <Kpi key="drafts" label={T.dash.drafts} value={data.drafts} />,
        ]}
      </Kpis>
      {data.cases.length > 0 ? (
        <Table caption={T.dash.ownCases}>
          <thead>
            <tr>
              <th scope="col">{T.dash.department}</th>
              <th scope="col" className={numCell}>
                {T.dash.allotted}
              </th>
              <th scope="col" className={numCell}>
                {T.dash.disposed}
              </th>
              {showCounsel ? (
                <th scope="col" className={numCell}>
                  {T.dash.counsel}
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {data.cases.map((c) => (
              <tr key={c.department_code}>
                <td className="mono">{c.department_code}</td>
                <td className={numCell}>{n(c.allotted_active)}</td>
                <td className={numCell}>{n(c.allotted_disposed)}</td>
                {showCounsel ? <td className={numCell}>{n(c.counsel_active)}</td> : null}
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
      <FileList items={data.files.items} caption={T.dash.files} />
      <div id="alerts">
        <h3>
          <Link href="/alerts">{T.dash.myAlerts}</Link>
        </h3>
        {data.alerts.items.length === 0 ? (
          <EmptyState>{T.dash.noAlerts}</EmptyState>
        ) : (
          <ul className={s.alerts}>
            {data.alerts.items.map((a) => (
              <li key={a.id}>
                <Badge tone={a.severity === "critical" ? "danger" : a.severity === "high" ? "warning" : undefined}>{a.kind_label}</Badge>{" "}
                {a.title} {a.case ? <CaseLink value={a.case} visible={a.case_visible} /> : null}
                <span className="muted"> · {formatDate(a.due_at ?? a.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function StateBlock({ data }: { data: DashboardState }) {
  const me = useMe();
  const n = formatNumber;
  const nc = data.not_claimed;
  const reports = can(me.data, "reports.state") ? <Link href="/reports/pending-cases">{T.reports.dashboardLink}</Link> : null;
  return (
    <Block title={T.dash.state} sub={T.dash.generated(formatDateTime(data.generated_at))} action={reports}>
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
        <Table caption={T.dash.byDepartment}>
          <thead>
            <tr>
              <th scope="col">{T.dash.department}</th>
              <th scope="col" className={numCell}>
                {T.dash.claimedCol}
              </th>
              <th scope="col" className={numCell}>
                {T.dash.recommendedCol}
              </th>
              <th scope="col" className={numCell}>
                {T.dash.hearingsCol}
              </th>
              <th scope="col" className={numCell}>
                {T.dash.pendingCol}
              </th>
              <th scope="col" className={numCell}>
                {T.dash.overdueCol}
              </th>
              <th scope="col" className={numCell}>
                {T.dash.complianceCol}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.by_department.map((d) => (
              <tr key={d.code}>
                <td>
                  {d.name} <span className="mono muted">{d.code}</span>
                </td>
                <td className={numCell}>{n(d.claimed_active)}</td>
                <td className={numCell}>{n(d.recommended_high + d.recommended_medium)}</td>
                <td className={numCell}>{n(d.hearings_7d)}</td>
                <td className={numCell}>{n(d.pending_actions)}</td>
                <td className={numCell}>{n(d.overdue_actions)}</td>
                <td className={numCell}>
                  {n(d.compliance_due_soon)} / {n(d.compliance_overdue)}
                </td>
              </tr>
            ))}
            <tr>
              <th scope="row">{T.dash.notClaimed}</th>
              <td className={numCell}>{n(nc.active)}</td>
              <td className={numCell}>{n(nc.recommended)}</td>
              <td className={numCell}>{n(nc.hearing_7d)}</td>
              <td className={numCell}>—</td>
              <td className={numCell}>—</td>
              <td className={numCell}>—</td>
            </tr>
          </tbody>
        </Table>
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
              <Table key={caption} caption={caption}>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.code}>
                      <td className="mono">{r.code}</td>
                      <td className={numCell}>{n(r.overdue)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
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
      {data.open === 0 ? <p className="muted">{T.dash.ticketsNone}</p> : null}
      {kinds.length > 0 || departments.length > 0 ? (
        <div className={s.panels}>
          {kinds.length > 0 ? (
            <Table caption={T.dash.ticketsByKind}>
              <tbody>
                {kinds.map(([kind, n]) => (
                  <tr key={kind}>
                    <th scope="row">{labelOf(labels.data?.ticket_kinds, kind)}</th>
                    <td className={numCell}>{formatNumber(n)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}
          {departments.length > 0 ? (
            <Table caption={T.dash.ticketsByDepartment}>
              <tbody>
                {departments.map(([code, n]) => (
                  <tr key={code}>
                    <th scope="row" className="mono">
                      {code}
                    </th>
                    <td className={numCell}>{formatNumber(n)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}
        </div>
      ) : null}
    </Block>
  );
}

export function NoDashboard({ me }: { me: Me }) {
  const entries = navFor(me).filter((e) => e.href !== "/");
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
