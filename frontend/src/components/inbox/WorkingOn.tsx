"use client";

/**
 * Working on (design case-inbox-merge, decisions 8 and 9): the cases allotted to me and the cases with me, one tab of
 * the Case inbox. "Show" picks the list:
 * - All (no `held`): `GET /inbox/mine?view=working`, my own due date first, then the next hearing (the API's order);
 * - With me (`held=me`) and With my offices (`held=offices`): `GET /custody/held?scope=me|office`, the old Cases with
 *   me list (`Held tab="with-me"`).
 *
 * "Overdue only" is the URL key `overdue=true` in every mode; under All it goes to the API as `action=overdue` (on my
 * own file). Work list template: the lead badge in the 96 px `Lead`, case and parties (the number links to the case
 * page), next hearing, action needed, due by and From, filled only when the case is with me, and the chevron. A row
 * opens "Case details"; the remark is read when the panel opens from the case's custody card, so the server's remark
 * rule applies and the list never carries remarks. Nothing here acts.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilePanel } from "@/components/files/FilePanel";
import { CaseCell, DueCell, Held, LeadCell, WithCell } from "@/components/files/Held";
import { FilterBar, type OwnControl } from "@/components/filters/FilterBar";
import { Badge, Chip, ChipGroup, DataTable, EmptyState, ErrorBanner, HearingDate, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, useJourney, useMe } from "@/lib/api/hooks";
import type { CustodyBrief, MyCase, MyCaseCounts, MyCaseList } from "@/lib/api/types";
import { leadBadge, withText, type WithParty } from "@/lib/cases";
import { FIELD_KEYS, LIST_FILTERS, toApiQuery } from "@/lib/filters";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { useFilters } from "./common";
import s from "./inbox.module.css";
import { isFiltered, useStageOptions } from "./MyCases";
import { Chevron, CountLine } from "./rows";

/** The Show control (decision 8): the first of the filter bar's own controls. */
export function showControl(): OwnControl {
  return {
    key: "held",
    kind: "segmented",
    label: T.cases.show,
    options: [
      { value: "", label: T.cases.showAll },
      { value: "me", label: T.cases.showMe },
      { value: "offices", label: T.cases.showOffices },
    ],
    first: true,
  };
}

/** An incoming `action=overdue` (a round-2 bookmark) reads as `overdue=true`. */
export function workingParams(params: Params): Params {
  if (params.action !== "overdue") return params;
  const { action: _drop, ...rest } = params;
  void _drop;
  return { ...rest, overdue: "true" };
}

const WORKING_KEYS = [...LIST_FILTERS.mine.fields.flatMap((f) => FIELD_KEYS[f]), "stage", "overdue"];

/** The brief of a case with me, else null: Action needed, Due by and From are mine only. */
function mine(r: MyCase): CustodyBrief | null {
  return r.custody?.with_me ? r.custody : null;
}

function briefSender(b: CustodyBrief | null | undefined): WithParty | null {
  const by = b?.sent_by;
  if (!by || (!by.name && !by.designation && !by.office_code)) return null;
  return { designation: by.designation, office: by.office_code, name: by.name };
}

function briefHolder(b: CustodyBrief | null | undefined, meId: string | null): WithParty | null {
  if (!b) return null;
  return {
    designation: b.holder_user?.designation ?? null,
    office: b.holder_office?.name ?? b.holder_office?.code ?? null,
    name: b.holder_user?.full_name ?? null,
    userId: b.with_me ? meId : null,
  };
}

export function WorkingOn({ params, counts }: { params: Params; counts: MyCaseCounts | undefined }) {
  const p = workingParams(params);
  if (p.held === "me" || p.held === "offices") return <Held tab="with-me" params={p} />;
  return <WorkingAll params={p} counts={counts} />;
}

function WorkingAll({ params, counts }: { params: Params; counts: MyCaseCounts | undefined }) {
  const setFilters = useFilters(params);
  const stages = useStageOptions();
  const me = useMe();
  const meId = me.data?.user.id ?? null;
  const [open, setOpen] = useState<MyCase | null>(null);
  const offset = offsetOf(params);
  const overdueOn = params.overdue === "true";
  const query = {
    view: "working",
    stage: params.stage || undefined,
    action: overdueOn ? "overdue" : undefined,
    ...toApiQuery(params, "mine"),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "mine", query],
    queryFn: () => api<MyCaseList>("/inbox/mine", { query }),
    placeholderData: keepPreviousData,
  });
  const own: OwnControl[] = [
    showControl(),
    { key: "stage", kind: "select", label: T.inbox.stage, options: stages, placeholder: T.inbox.anyStage },
    { key: "overdue", kind: "check", label: T.files.overdueOnly },
  ];
  const weekOn = params.next === "n7" && !params.next_from && !params.next_to;
  const columns: Column<MyCase>[] = [
    {
      key: "lead",
      header: <span className="visually-hidden">{T.cases.leadCol}</span>,
      label: T.cases.leadCol,
      width: "var(--lead-w)",
      cell: (r) => <LeadCell badge={leadBadge(r, "working")} />,
    },
    { key: "case", header: T.files.case, primary: true, cell: (r) => <CaseCell c={r.case} /> },
    { key: "next", header: T.inbox.nextHearingCol, cell: (r) => <HearingDate date={r.case.next_hearing_date} status={r.case.status} /> },
    {
      key: "action",
      header: T.files.action,
      cell: (r) => {
        const b = mine(r);
        return b && b.pending_action !== "none" ? b.pending_action_label : <span className="muted">—</span>;
      },
    },
    { key: "due", header: T.files.due, cell: (r) => <DueCell date={mine(r)?.due_date} overdue={!!mine(r)?.overdue} /> },
    { key: "from", header: T.cases.from, cell: (r) => <WithCell party={briefSender(mine(r))} /> },
    { key: "open", header: <span className="visually-hidden">{T.files.details}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  return (
    <section className="stack" aria-label={T.tabs.inbox.working}>
      <ChipGroup label={T.inbox.quick}>
        <Chip on={weekOn} onClick={() => setFilters({ next: weekOn ? undefined : "n7", next_from: undefined, next_to: undefined })}>
          {T.inbox.hearingWeek}
        </Chip>
        <Chip on={overdueOn} onClick={() => setFilters({ overdue: overdueOn ? undefined : "true" })}>
          {T.inbox.actionOverdue}
        </Chip>
      </ChipGroup>
      <FilterBar list="mine" params={params} own={own} />
      <div className={s.toolbar}>
        <CountLine total={list.data?.total} of={counts?.working} filtered={isFiltered(params, WORKING_KEYS)} />
      </div>
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <DataTable
            caption={T.tabs.inbox.working}
            columns={columns}
            rows={list.data.items}
            rowKey={(r) => r.case.id}
            onRowClick={setOpen}
            rowLabel={(r) => T.files.openFile(r.case.case_no_text || r.case.ref_no)}
            empty={<EmptyState title={T.inbox.nothingWaiting}>{T.inbox.emptyViews.working}</EmptyState>}
          />
          {list.data.items.length > 0 ? (
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
          ) : null}
        </>
      ) : null}
      <WorkingPanel row={open} meId={meId} onClose={() => setOpen(null)} />
    </section>
  );
}

/**
 * Decision 9: the row's facts from its brief (With says where the case is when it is not with me); the remark from
 * the case's custody card, read once on opening and only for a case with a custody row.
 */
function WorkingPanel({ row, meId, onClose }: { row: MyCase | null; meId: string | null; onClose: () => void }) {
  const brief = row?.custody ?? null;
  const journey = useJourney(row?.case.ref_no ?? "", 1, 0, !!row && !!brief);
  const holder = briefHolder(brief, meId);
  return (
    <FilePanel
      caseRef={row ? row.case : null}
      onClose={onClose}
      remark={brief ? journey.data?.card?.remark : null}
      facts={[
        [T.files.holder, holder ? <span title={withText(holder, meId).title}>{withText(holder, meId).text}</span> : null],
        [T.files.action, brief && brief.pending_action !== "none" ? brief.pending_action_label : null],
        [T.files.since, brief ? formatDateTime(brief.since) : null],
        [
          T.files.due,
          brief?.due_date ? (
            <span className={s.action}>
              {formatDate(brief.due_date)}
              {brief.overdue ? <Badge tone="danger">{T.files.overdueBy(brief.overdue_days)}</Badge> : null}
            </span>
          ) : null,
        ],
        [T.files.from, brief ? <WithCell party={briefSender(brief)} /> : null],
      ]}
    />
  );
}
