"use client";

/**
 * The held lists (design case-workspace-admin, decisions 17 and 19; custody-workflow decision 24), tabs of the Case
 * inbox (design case-inbox-simplify, decisions 2 and 11): With Me, whose "Show" reads With Me (`scope=me`, the default)
 * or With My Offices (`scope=office`, `?held=offices`), with a Next Hearing column; and, for a tracker without
 * whole-department sight, the Department tab's list (`scope=owned` narrowed to the selected department through its
 * `owner` filter, "Department it is with", its Overdue chip the URL key `action=overdue`). The API's order (due date,
 * then since), paged
 * by 50 in the query string. No action buttons: sending and recalling happen on the case page, where the card's flags
 * are current. The one filter bar (design portal-filters): the shared case filters with the owning department (on
 * Pending action only the departments the login tracks), Overdue only and the list's own controls. On the Work list
 * template: the lead badge in a 96 px `Lead`, case and parties, action needed, due by, From (Cases with me) or With
 * (Pending action), and the chevron; cards on phones; the row opens the side panel with the full remark.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar, type OwnControl } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import { Chevron } from "@/components/inbox/rows";
import { Badge, CaseLink, DataTable, EmptyState, ErrorBanner, HearingDate, Lead, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useDepartments, useMe } from "@/lib/api/hooks";
import type { HeldItem, HeldList, Me } from "@/lib/api/types";
import { cardHolder, cardSender, leadBadge, withText, type WithParty } from "@/lib/cases";
import { toApiQuery } from "@/lib/filters";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { FilePanel } from "./FilePanel";
import { TRACK_ERRORS } from "./TrackingSummary";
import s from "./files.module.css";
import { caseFiltersSet, NoCaseMatches } from "@/components/filters/NoCaseMatches";

export type HeldScope = "me" | "office" | "owned";

const EMPTY: Record<HeldScope, string> = {
  me: T.files.emptyMine,
  office: T.files.emptyOffices,
  owned: T.files.emptyDepartment,
};

const CAPTION: Record<HeldScope, string> = {
  me: T.files.captionMine,
  office: T.files.captionOffices,
  owned: T.files.captionDepartment,
};

/** "With …" text with the name as the title (decision 13). */
export function WithCell({ party, meId }: { party: WithParty | null; meId?: string | null }) {
  if (!party) return <span className="muted">—</span>;
  const w = withText(party, meId);
  return <span title={w.title}>{w.text}</span>;
}

export function LeadCell({ badge }: { badge: ReturnType<typeof leadBadge> }) {
  return <Lead>{badge ? <Badge tone={badge.tone}>{badge.label}</Badge> : null}</Lead>;
}

/** The number over "petitioner vs respondent", with an optional small label under the number. */
export function CaseCell({
  c,
  visible = true,
  mark,
}: {
  c: HeldItem["case"];
  visible?: boolean;
  mark?: string | null;
}) {
  return (
    <div className={s.caseCell}>
      <CaseLink value={c} visible={visible} />
      {mark ? <span className={s.mark}>{mark}</span> : null}
      {c.petitioner_summary || c.respondent_summary ? (
        <span className="muted">
          {c.petitioner_summary ?? "—"} {T.vs} {c.respondent_summary ?? "—"}
        </span>
      ) : null}
    </div>
  );
}

export function DueCell({ date, overdue }: { date: string | null | undefined; overdue: boolean }) {
  if (!date) return <span className="muted">—</span>;
  return <span className={overdue ? s.danger : undefined}>{formatDate(date)}</span>;
}

/** The departments the login tracks (`custody.track` in a department membership): Pending action holds no other. */
export function trackedDepartments(me: Me | undefined): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [];
  for (const m of me?.memberships ?? []) {
    const code = m.department_code;
    if (m.is_active === false || !code || !(m.functions ?? []).includes("custody.track")) continue;
    if (!out.some((o) => o.value === code)) out.push({ value: code, label: code });
  }
  return out;
}

/**
 * `tab="with-me"`: With Me. `tab="pending"`: the tracker's Department list; `department` narrows it to that department
 * (sent as `owner`), and its overdue key is `action=overdue` (the Department tab's chip), sent as `overdue=true`.
 */
export function Held({ tab, params, department }: { tab: "with-me" | "pending"; params: Params; department?: string }) {
  const setFilters = useFilters(params);
  const me = useMe();
  const meId = me.data?.user.id ?? null;
  const [open, setOpen] = useState<HeldItem | null>(null);
  const scope: HeldScope = tab === "pending" ? "owned" : params.held === "offices" ? "office" : "me";
  const offset = offsetOf(params);
  const overdue = scope === "owned" ? params.action === "overdue" || params.overdue === "true" : params.overdue === "true";
  const holderDepartment = scope === "owned" ? params.holder_department || undefined : undefined;
  const departments = useDepartments(scope === "owned");
  const listKey = scope === "owned" ? "held_owned" : "held";
  const query = {
    scope,
    overdue: overdue || undefined,
    holder_department: holderDepartment,
    ...toApiQuery(params, listKey),
    ...(scope === "owned" && department ? { owner: department } : {}),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: ["files", "held", query],
    queryFn: () => api<HeldList>("/custody/held", { query }),
    placeholderData: keepPreviousData,
  });
  const own: OwnControl[] =
    scope === "owned"
      ? [
          {
            key: "holder_department",
            kind: "select" as const,
            label: T.files.holderDepartment,
            placeholder: T.files.allDepartments,
            options: (departments.data?.departments ?? []).map((d) => ({ value: d.code, label: `${d.code} — ${d.name}` })),
            more: true,
          },
        ]
      : [
          // design case-inbox-simplify, decision 2: With Me (the default) or With My Offices; no "All"
          {
            key: "held",
            kind: "segmented",
            label: T.cases.show,
            options: [
              { value: "", label: T.cases.showMe },
              { value: "offices", label: T.cases.showOffices },
            ],
            first: true,
          },
          { key: "overdue", kind: "check", label: T.files.overdueOnly },
        ];
  const who = (r: HeldItem): WithParty | null => (scope === "owned" ? cardHolder(r.card) : cardSender(r.card));
  const whoHeader = scope === "owned" ? T.cases.with : T.cases.from;
  const columns: Column<HeldItem>[] = [
    {
      key: "lead",
      header: <span className="visually-hidden">{T.cases.leadCol}</span>,
      label: T.cases.leadCol,
      width: "var(--lead-w)",
      cell: (r) => <LeadCell badge={leadBadge(r, tab)} />,
    },
    { key: "case", header: T.files.case, primary: true, cell: (r) => <CaseCell c={r.case} /> },
    // design case-inbox-simplify, decision 2: a disposed case with me reads "Disposed" here
    ...(scope === "owned"
      ? []
      : [{ key: "next", header: T.inbox.nextHearingCol, cell: (r: HeldItem) => <HearingDate next={r.case.next_hearing} status={r.case.status} /> }]),
    { key: "action", header: T.files.action, cell: (r) => r.card?.pending_action_label ?? "—" },
    { key: "due", header: T.files.due, cell: (r) => <DueCell date={r.card?.due_date} overdue={!!r.card?.overdue} /> },
    { key: "who", header: whoHeader, cell: (r) => <WithCell party={who(r)} meId={meId} /> },
    { key: "open", header: <span className="visually-hidden">{T.files.details}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  const card = open?.card;
  return (
    <div className="stack">
      <FilterBar
        list={listKey}
        params={params}
        own={own}
        ownerOptions={scope === "owned" ? (department ? [{ value: department, label: department }] : trackedDepartments(me.data)) : undefined}
        total={list.data?.total}
        noun="files"
      />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} messages={TRACK_ERRORS} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <DataTable
            caption={CAPTION[scope]}
            columns={columns}
            rows={list.data.items}
            rowKey={(r) => r.case.id}
            onRowClick={setOpen}
            rowLabel={(r) => T.files.openFile(r.case.case_no_text || r.case.ref_no)}
            empty={
              caseFiltersSet(params, listKey, own.filter((c) => c.kind !== "segmented").map((c) => c.key)) ? (
                <NoCaseMatches params={params} list={listKey} />
              ) : (
                <EmptyState>{EMPTY[scope]}</EmptyState>
              )
            }
          />
          {list.data.items.length > 0 ? (
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
          ) : null}
        </>
      ) : null}
      <FilePanel
        caseRef={open ? open.case : null}
        onClose={() => setOpen(null)}
        remark={card?.remark}
        facts={[
          [T.files.holder, open ? <WithCell party={cardHolder(open.card)} meId={meId} /> : null],
          [T.files.action, card?.pending_action_label ?? null],
          [T.files.since, formatDateTime(card?.since)],
          [
            T.files.due,
            card?.due_date ? (
              <span className={s.action}>
                {formatDate(card.due_date)}
                {card.overdue ? <Badge tone="danger">{T.files.overdueBy(card.overdue_days)}</Badge> : null}
              </span>
            ) : null,
          ],
          [T.files.from, open ? <WithCell party={cardSender(open.card)} /> : null],
        ]}
      />
    </div>
  );
}
