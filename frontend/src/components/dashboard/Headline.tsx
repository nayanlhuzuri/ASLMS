"use client";

/**
 * The personal dashboard (design portal-ui-redesign, decision 23; API A7): the greeting by the IST hour, the five
 * headline numbers (each a link to its list; a figure the API returns as `null` is left out and the grid closes up),
 * Upcoming hearings and Needs your attention. Every figure and row comes from `GET /dashboard/me`; the browser works
 * out only the greeting and the day words from IST dates.
 */
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge, Card, CaseLink, DateChip, EmptyState, Kpi, Lead, ListRow, type Tone } from "@/components/ui";
import type { DashboardHeadline, DashboardMe, DashboardMeAttention, DashboardUpcoming, Me } from "@/lib/api/types";
import { daysBetween, formatDayLong, formatNumber, istDay, istHour } from "@/lib/format";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";

import s from "./dashboard.module.css";

/** "Good morning / afternoon / evening, <first name>" by the IST hour. */
export function greeting(fullName: string | null | undefined, now: Date = new Date()): string {
  const first = (fullName ?? "").trim().split(/\s+/)[0] ?? "";
  const hour = istHour(now);
  const g = hour < 12 ? T.dash.greeting.morning : hour < 17 ? T.dash.greeting.afternoon : T.dash.greeting.evening;
  return g(first).replace(/,\s*$/, "");
}

/** The line under the greeting: the primary membership's office and the IST date ("Tuesday, 21 October"). */
export function greetingLine(me: Me | undefined, now: Date = new Date()): string {
  const primary = (me?.memberships ?? []).find((m) => m.is_primary && m.is_active !== false) ?? me?.memberships?.[0];
  return T.dash.greetingLine([primary?.office.name ?? "", formatDayLong(now)]);
}

/** Whether the login has personal work to show (a State-wide reader without any opens on the State view). */
export function hasPersonalWork(data: DashboardMe | undefined): boolean {
  if (!data) return false;
  const h = data.headline;
  return (
    data.cases.length > 0 ||
    h.to_claim !== null ||
    h.files_with_me.total > 0 ||
    h.hearings_week.total > 0 ||
    (h.next_dates_to_confirm ?? 0) > 0 ||
    data.upcoming.length > 0 ||
    data.attention.length > 0
  );
}

/** The five headline numbers; a `null` figure is not shown. */
export function HeadlineKpis({ headline }: { headline: DashboardHeadline }) {
  const n = formatNumber;
  const claim = headline.to_claim;
  const overdue = headline.overdue_actions;
  const items = [
    claim
      ? (
          <Kpi
            key="claim"
            label={T.dash.kpiClaim}
            value={claim.high + claim.medium}
            sub={T.dash.kpiClaimSub(n(claim.high), n(claim.medium))}
            href="/claim/recommended"
          />
        )
      : null,
    <Kpi
      key="hearings"
      label={T.dash.kpiHearings}
      value={headline.hearings_week.total}
      sub={T.dash.kpiHearingsSub(n(headline.hearings_week.within_48h))}
      tone={headline.hearings_week.within_48h > 0 ? "danger" : undefined}
      href="/calendar"
    />,
    <Kpi
      key="files"
      label={T.dash.kpiFiles}
      value={headline.files_with_me.total}
      sub={T.dash.kpiFilesSub(n(headline.files_with_me.due_today))}
      tone={headline.files_with_me.due_today > 0 ? "warning" : undefined}
      href="/inbox/files"
    />,
    <Kpi
      key="overdue"
      label={T.dash.kpiOverdue}
      value={overdue.total}
      sub={overdue.oldest_days !== null && overdue.oldest_days !== undefined ? T.dash.kpiOverdueSub(overdue.oldest_days) : T.dash.kpiOverdueNone}
      tone={overdue.total > 0 ? "danger" : undefined}
      href="/inbox/files?action=overdue"
    />,
    headline.next_dates_to_confirm !== null && headline.next_dates_to_confirm !== undefined ? (
      <Kpi
        key="confirm"
        label={T.dash.kpiConfirm}
        value={headline.next_dates_to_confirm}
        sub={T.dash.kpiConfirmSub}
        href="/alerts/next-dates"
      />
    ) : null,
  ].filter(Boolean);
  return (
    <section className={s.kpis} data-count={items.length} aria-label={T.dash.headline}>
      {items}
    </section>
  );
}

/**
 * Today / Tomorrow / In n days (within 48 hours, red) / This week / In n days (neutral), from IST dates and the API's
 * flags. Every row of the 8-day window gets a badge: the last line covers hearings 2 to 7 days ahead that fall in the
 * next calendar week (design portal-ui-polish, decision 14). Only a past date (never served) gets none.
 */
export function dayWords(item: Pick<DashboardUpcoming, "date" | "critical" | "this_week">, now: Date = new Date()): { text: string; tone?: Tone } | null {
  const days = daysBetween(istDay(now), item.date);
  if (days === 0) return { text: T.dash.today, tone: item.critical ? "danger" : undefined };
  if (days === 1) return { text: T.dash.tomorrow, tone: item.critical ? "danger" : undefined };
  if (item.critical) return { text: T.dash.inDays(days), tone: "danger" };
  if (item.this_week) return { text: T.dash.thisWeek };
  if (days > 1) return { text: T.dash.inDays(days) };
  return null;
}

export function UpcomingPanel({ items }: { items: DashboardUpcoming[] }) {
  return (
    <Card title={T.dash.upcoming} actions={<Link href="/calendar">{T.dash.openCalendar}</Link>}>
      {items.length === 0 ? (
        <EmptyState title={T.dash.upcomingNoneTitle}>{T.dash.upcomingNone}</EmptyState>
      ) : (
        <ul className={s.list} aria-label={T.dash.upcoming}>
          {items.map((h) => {
            const words = dayWords(h);
            const where = T.dash.courtItem(h.court_no, h.item_no);
            return (
              <ListRow
                as="li"
                key={`${h.case.id}-${h.date}`}
                lead={<DateChip date={h.date} hot={h.critical} />}
                trail={words ? <Badge tone={words.tone}>{words.text}</Badge> : null}
              >
                <CaseLink value={h.case} />
                {where ? <div className="muted">{where}</div> : null}
              </ListRow>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

const LEAD_TONE: Record<string, Tone> = {
  overdue_action: "danger",
  confirm_next_date: "warning",
  due_soon: "warning",
  file_received: "info",
};

function attentionHref(item: DashboardMeAttention): string {
  // a next date goes to its review item, as My calendar's agenda (design portal-ui-redesign, decision 8)
  if (item.kind === "confirm_next_date") return `/alerts/next-dates?q=${encodeURIComponent(item.case.id)}`;
  return casePath(item.case.ref_no);
}

export function AttentionPanel({ items }: { items: DashboardMeAttention[] }) {
  return (
    <Card title={T.dash.needsAttention}>
      {items.length === 0 ? (
        <EmptyState title={T.dash.attentionNoneTitle}>{T.dash.attentionNone}</EmptyState>
      ) : (
        <ul className={s.list} aria-label={T.dash.needsAttention}>
          {items.map((a) => {
            const label = T.dash.leads[a.kind] ?? a.kind;
            return (
              <ListRow
                as="li"
                key={`${a.kind}-${a.case.id}-${a.next_date_id ?? ""}`}
                lead={
                  <Lead>
                    <Badge tone={LEAD_TONE[a.kind]} title={label}>
                      {label}
                    </Badge>
                  </Lead>
                }
              >
                <Link href={attentionHref(a)} className={s.title}>
                  {a.title}
                </Link>
                <div className="muted">{T.dash.caseDetail(a.case.case_no_text || a.case.ref_no, a.detail ?? null)}</div>
              </ListRow>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

/** The "My work" view: the headline numbers and the two panels. */
export function MyWork({ data, children }: { data: DashboardMe; children?: ReactNode }) {
  return (
    <section className="stack" aria-label={T.dash.personal}>
      <HeadlineKpis headline={data.headline} />
      <div className={s.panels}>
        <UpcomingPanel items={data.upcoming} />
        <AttentionPanel items={data.attention} />
      </div>
      {children}
    </section>
  );
}
