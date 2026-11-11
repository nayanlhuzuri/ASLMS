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
 * template: case and parties, action needed, From (Cases with me) or With (Pending action), and the chevron; cards on
 * phones; the row opens the side panel with the full remark.
 *
 * Design portal-screen-fixes-work, decisions 1 to 5: Filter Layout B (Words the hero; Show, Overdue Only, Next Hearing
 * and Case Type on the right; the rest under More Filters) with "Search" and the count at the head of the strip ("n of
 * m cases" on With Me, m being `files` of `/inbox/mine/counts`); the inbox's one plain case cell with "New" and the
 * closure marks under the number; no lead column; one Action Needed cell with the server's Due line.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar, type OwnControl } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import inboxStyles from "@/components/inbox/inbox.module.css";
import { ActionDueCell, briefDue, CaseCell, Chevron, closureMark, CountLine, custodyAction, DueLine } from "@/components/inbox/rows";
import { Chip, ChipGroup, DataTable, EmptyState, ErrorBanner, HearingDate, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useDepartments, useMe, useOfficeNames } from "@/lib/api/hooks";
import type { HeldItem, HeldList, Me } from "@/lib/api/types";
import { cardHolder, cardSender, isNewSince, withText, type WithParty } from "@/lib/cases";
import { toApiQuery, type SharedField } from "@/lib/filters";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";
import { serverLabel } from "@/lib/displayLabels";
import { nameOptions } from "@/lib/officeNames";

import { FilePanel } from "./FilePanel";
import { TRACK_ERRORS } from "./TrackingSummary";
import { caseFiltersSet, NoCaseMatches } from "@/components/filters/NoCaseMatches";

/**
 * With Me's and Sent by Me's More Filters in Layout B (design portal-screen-fixes-work, decision 1): Next Hearing and
 * Case Type stay on the right.
 */
export const CUSTODY_MORE: readonly SharedField[] = ["listed", "year", "case_status", "court_no", "bench", "owner", "next_differs"];

export type HeldScope = "me" | "office" | "owned";

const EMPTY: Record<HeldScope, string> = {
  me: T.files.emptyMine,
  office: T.files.emptyOffices,
  owned: T.files.emptyDepartment,
};

const EMPTY_TITLE: Record<HeldScope, string> = {
  me: T.files.emptyMineTitle,
  office: T.files.emptyOfficesTitle,
  owned: T.files.emptyDepartmentTitle,
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
export function Held({
  tab,
  params,
  department,
  unfiltered,
}: {
  tab: "with-me" | "pending";
  params: Params;
  department?: string;
  /** With Me's unfiltered figure (`files` of `/inbox/mine/counts`), for "n of m cases"; With My Offices and the
   * tracker's list have none. */
  unfiltered?: number | null;
}) {
  const setFilters = useFilters(params);
  const me = useMe();
  const names = useOfficeNames().data;
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
            options: nameOptions(departments.data?.departments ?? []),
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
          { key: "overdue", kind: "check", label: T.files.overdueOnly, first: true },
        ];
  const who = (r: HeldItem): WithParty | null => (scope === "owned" ? cardHolder(r.card) : cardSender(r.card, names));
  const whoHeader = scope === "owned" ? T.cases.with : T.cases.from;
  const columns: Column<HeldItem>[] = [
    {
      key: "case",
      header: T.files.case,
      primary: true,
      cell: (r) => (
        <CaseCell
          c={r.case}
          marks={[
            scope === "me" && isNewSince(r.card?.since) ? { label: T.cases.lead.new, tone: "info" } : null,
            closureMark(r.case),
          ]}
        />
      ),
    },
    // design case-inbox-simplify, decision 2: a disposed case with me reads "Disposed" here; the closure is a mark of the
    // case (design portal-screen-fixes-work, decision 4)
    ...(scope === "owned"
      ? []
      : [{ key: "next", header: T.inbox.nextHearingCol, cell: (r: HeldItem) => <HearingDate next={r.case.next_hearing} status={r.case.status} /> }]),
    { key: "action", header: T.files.action, cell: (r) => <ActionDueCell action={custodyAction(r.card)} due={briefDue(r.card)} /> },
    { key: "who", header: whoHeader, cell: (r) => <WithCell party={who(r)} meId={meId} /> },
    { key: "open", header: <span className="visually-hidden">{T.files.details}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  const filterKeys = own.filter((c) => c.kind !== "segmented").map((c) => c.key);
  // design case-inbox-simplify-followups, decision 2: the tracker's Overdue chip counts as a filter
  const filtered = caseFiltersSet(params, listKey, filterKeys) || (scope === "owned" && overdue);
  const card = open?.card;
  // design close-case, decision 15: the quick chip sets the shared filter `case_status=disposed`
  const readyOn = params.case_status === "disposed";
  return (
    <div className="stack">
      {scope === "owned" ? null : (
        <div className={inboxStyles.switchRow}>
          <ChipGroup label={T.inbox.quick}>
            <Chip on={readyOn} onClick={() => setFilters({ case_status: readyOn ? undefined : "disposed" })}>
              {T.inbox.readyToClose}
            </Chip>
          </ChipGroup>
        </div>
      )}
      <FilterBar
        list={listKey}
        layout="card"
        hero="q"
        more={CUSTODY_MORE}
        params={params}
        own={own}
        ownerOptions={scope === "owned" ? (department ? [{ value: department, label: department }] : trackedDepartments(me.data)) : undefined}
        wordsLabel={T.filters.wordsShort}
        wordsHint={T.filters.wordsHint}
        countLine={
          list.data ? <CountLine total={list.data.total} of={scope === "me" ? (unfiltered ?? null) : null} filtered={filtered} /> : null
        }
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
              filtered ? (
                <NoCaseMatches params={params} list={listKey} />
              ) : (
                <EmptyState title={EMPTY_TITLE[scope]}>{EMPTY[scope]}</EmptyState>
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
          [T.files.action, custodyAction(card) ?? serverLabel(card?.pending_action_label) ?? null],
          [T.files.since, formatDateTime(card?.since)],
          [T.files.due, card ? <DueLine due={briefDue(card)} /> : null],
          [T.files.from, open ? <WithCell party={cardSender(open.card, names)} /> : null],
        ]}
      />
    </div>
  );
}
