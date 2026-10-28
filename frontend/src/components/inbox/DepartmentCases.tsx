"use client";

/**
 * Department cases (design portal-ui-redesign, decision 5; API A3): the department's claimed cases for the readers
 * the server reads whole (`whole_department` on `/inbox/counts`: `cases.claim` or `cases.allot` in the membership, or a
 * State-wide reader). It replaces the old Claimed tab. Active and Disposed are the Status switch (default Active). The
 * full filter bar of the mock-up: Search, Responsible Unit, Dealing Officer (with "Not Assigned Yet", sent as `unallotted=true`), Stage, Next
 * hearing (Any date / This week / Next 30 days / Choose dates…); "More filters": Case type, Year, Court, File is with,
 * Action; removable chips, "Clear all" and "n of m cases". Rows: the case, unit · officer, stage, next hearing and who
 * holds the file; a row opens the case page. Allot stays on the case page (its ownership actions).
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { FilterBar, type OwnControl } from "@/components/filters/FilterBar";
import { DataTable, EmptyState, ErrorBanner, HearingDate, Loading, Pagination, SegmentedSwitch, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, useDepartmentPeople } from "@/lib/api/hooks";
import type { InboxCounts, Ownership, OwnershipList } from "@/lib/api/types";
import { FIELD_KEYS, LIST_FILTERS, toApiQuery, type SharedField } from "@/lib/filters";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";
import { casePath } from "@/lib/refs";

import { useFilters } from "./common";
import { isFiltered, useStageOptions } from "./MyCases";
import { CaseCell, Chevron, CountLine, HolderCell, StageCell } from "./rows";

/** Layout B's More Filters on Department cases (design portal-ui-polish-2, decision 23); Case Type is on the right. */
const DEPARTMENT_MORE: readonly SharedField[] = ["year", "court_no"];

/** `officer=none` in the URL is "Not Assigned Yet" (no dealing officer; sent as `unallotted=true`). */
export const NOT_ALLOTTED = "none";

const DEPARTMENT_KEYS = [
  ...LIST_FILTERS.department.fields.flatMap((f) => FIELD_KEYS[f]),
  "unit",
  "officer",
  "stage",
  "holder",
  "action",
];

/** The `/inbox/claimed` query of the page's own controls. */
export function departmentQuery(params: Params): Record<string, string | undefined> {
  const officer = params.officer || undefined;
  return {
    unit: params.unit ? params.unit.toUpperCase() : undefined,
    officer_user_id: officer && officer !== NOT_ALLOTTED ? officer : undefined,
    unallotted: officer === NOT_ALLOTTED ? "true" : undefined,
    stage: params.stage || undefined,
    holder: params.holder || undefined,
    action: params.action || undefined,
  };
}

function AllotmentCell({ row }: { row: Ownership }) {
  if (!row.unit && !row.officer) return <span className="muted">{T.inbox.notAssigned}</span>;
  return (
    <span>
      {row.unit ? <span className="mono">{row.unit.code}</span> : null}
      {row.unit && row.officer ? " · " : null}
      {row.officer ? row.officer.full_name : null}
    </span>
  );
}

export function DepartmentCases({ params, department, block }: { params: Params; department: string; block: InboxCounts }) {
  const router = useRouter();
  const setFilters = useFilters(params);
  const people = useDepartmentPeople(department);
  const stages = useStageOptions();
  const offset = offsetOf(params);
  const caseState = params.case_state === "disposed" ? "disposed" : "active";
  const query = {
    office: department,
    case_state: caseState,
    ...departmentQuery(params),
    ...toApiQuery(params, "department"),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "claimed", query],
    queryFn: () => api<OwnershipList>("/inbox/claimed", { query }),
  });
  const officers = new Map<string, string>();
  for (const p of people.data?.items ?? []) if (!officers.has(p.user_id)) officers.set(p.user_id, p.full_name);
  const units = people.data?.units ?? [];
  const own: OwnControl[] = [
    units.length > 0
      ? {
          key: "unit",
          kind: "select",
          label: T.inbox.unitSelect,
          options: units.map((u) => ({ value: u.code, label: `${u.code} — ${u.name}` })),
          placeholder: T.inbox.anyUnit,
          first: true,
        }
      : { key: "unit", kind: "text", label: T.inbox.unitSelect, first: true },
    {
      key: "officer",
      kind: "select",
      label: T.inbox.officer,
      options: [{ value: NOT_ALLOTTED, label: T.inbox.notAssignedYet }, ...[...officers.entries()].map(([value, label]) => ({ value, label }))],
      placeholder: T.inbox.anyOfficer,
      first: true,
    },
    { key: "stage", kind: "select", label: T.inbox.stage, options: stages, placeholder: T.inbox.anyStage, first: true },
    {
      key: "holder",
      kind: "select",
      label: T.inbox.holder,
      options: ["department", "elsewhere"].map((v) => ({ value: v, label: T.inbox.holders[v]! })),
      placeholder: T.inbox.holders[""],
      more: true,
    },
    {
      key: "action",
      kind: "select",
      label: T.inbox.action,
      options: ["overdue", "due_week"].map((v) => ({ value: v, label: T.inbox.actionOptions[v]! })),
      placeholder: T.inbox.actionOptions[""],
      more: true,
    },
  ];
  const columns: Column<Ownership>[] = [
    { key: "case", header: T.inbox.case, primary: true, cell: (r) => <CaseCell c={r.case} /> },
    { key: "allot", header: T.inbox.unitOfficer, cell: (r) => <AllotmentCell row={r} /> },
    { key: "stage", header: T.inbox.stage, cell: (r) => <StageCell stage={r.stage} /> },
    { key: "next", header: T.inbox.nextHearingCol, cell: (r) => <HearingDate date={r.case.next_hearing_date} status={r.case.status} /> },
    { key: "holder", header: T.inbox.fileWith, cell: (r) => <HolderCell custody={r.custody} /> },
    { key: "open", header: <span className="visually-hidden">{T.inbox.actions}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  const unfiltered = caseState === "disposed" ? block.claimed_disposed : block.claimed_active;
  return (
    <section className="stack" aria-label={T.tabs.inbox.department}>
      <SegmentedSwitch
        label={T.inbox.status}
        options={(["active", "disposed"] as const).map((v) => ({ value: v, label: T.inbox.caseStates[v]! }))}
        value={caseState}
        onChange={(v) => setFilters({ case_state: v === "active" ? undefined : v })}
      />
      {/* design portal-ui-polish-2, decision 23: Layout B with Words as the hero; Unit, Officer, Stage, Next Hearing and
          Case Type on the right; Year, Court, File Is With and Action under More Filters */}
      <FilterBar
        list="department"
        layout="card"
        hero="q"
        more={DEPARTMENT_MORE}
        params={params}
        own={own}
        wordsLabel={T.filters.wordsShort}
        wordsHint={T.filters.wordsHint}
        countLine={
          list.data ? <CountLine total={list.data.total} of={unfiltered} filtered={isFiltered(params, DEPARTMENT_KEYS)} /> : null
        }
      />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <DataTable
            caption={T.tabs.inbox.department}
            columns={columns}
            rows={list.data.items}
            rowKey={(r) => r.id}
            onRowClick={(r) => router.push(casePath(r.case.ref_no))}
            rowLabel={(r) => T.inbox.openCase(r.case.case_no_text || r.case.ref_no)}
            empty={<EmptyState title={T.inbox.nothingWaiting}>{T.inbox.emptyViews.department}</EmptyState>}
          />
          <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
        </>
      ) : null}
    </section>
  );
}
