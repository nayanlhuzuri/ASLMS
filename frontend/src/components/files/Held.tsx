"use client";

/**
 * The held-files lists of "Files" (design portal-files-alerts, decision 12; custody-workflow decision 24):
 * With me (`scope=me`), My offices (`scope=office`) and Department files (`scope=owned`, with the tracking summary
 * and the holder-department filter). The API's order (due date, then since), paged by 50 in the query string. No
 * action buttons: sending and recalling happen on the case page, where the card's flags are current. The one filter bar
 * (design portal-filters): the shared case filters with the owning department (on Department files only the
 * departments the login tracks), Overdue only and, on Department files, the holder department. On the Work list
 * template (design portal-ui-redesign, decision 26): the due date in the fixed leading column, cards on phones, and
 * the card details with the full remark in a side panel opened by the row.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar, type OwnControl } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import { Chevron } from "@/components/inbox/rows";
import { Badge, CaseLink, DataTable, DateChip, EmptyState, ErrorBanner, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useDepartments, useMe } from "@/lib/api/hooks";
import type { HeldItem, HeldList } from "@/lib/api/types";
import type { Me } from "@/lib/api/types";
import { toApiQuery } from "@/lib/filters";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { FilePanel } from "./FilePanel";
import { TRACK_ERRORS, TrackingSummary } from "./TrackingSummary";
import s from "./files.module.css";

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

function sentByText(item: HeldItem): string | null {
  const by = item.card?.sent_by;
  if (!by) return null;
  return [by.name, by.designation].filter(Boolean).join(", ") || by.office_code || null;
}

function SentBy({ item }: { item: HeldItem }) {
  const by = item.card?.sent_by;
  if (!by || (!by.name && !by.office_code)) return <span className="muted">—</span>;
  return (
    <>
      <div>{[by.name, by.designation].filter(Boolean).join(", ") || "—"}</div>
      {by.office_code ? <div className="mono muted">{by.office_code}</div> : null}
    </>
  );
}

function HolderCell({ item }: { item: HeldItem }) {
  const card = item.card;
  if (!card) return <span className="muted">—</span>;
  return (
    <>
      {card.holder_office ? (
        <div>
          <span className="mono">{card.holder_office.code}</span> {card.holder_office.name}
        </div>
      ) : null}
      {card.holder_user ? <div>{[card.holder_user.full_name, card.holder_user.designation].filter(Boolean).join(", ")}</div> : null}
    </>
  );
}

function ActionCell({ item }: { item: HeldItem }) {
  const card = item.card;
  if (!card) return <span className="muted">—</span>;
  return (
    <span className={s.action}>
      <span>{card.pending_action_label ?? "—"}</span>
      {card.overdue ? <Badge tone="danger">{T.files.overdueBy(card.overdue_days)}</Badge> : null}
    </span>
  );
}

function CaseCell({ item }: { item: HeldItem }) {
  const c = item.case;
  return (
    <div className={s.caseCell}>
      <CaseLink value={c} />
      {c.petitioner_summary || c.respondent_summary ? (
        <span className="muted">
          {c.petitioner_summary ?? "—"} {T.vs} {c.respondent_summary ?? "—"}
        </span>
      ) : null}
    </div>
  );
}

/** The departments the login tracks (`custody.track` in a department membership): Department files holds no other. */
export function trackedDepartments(me: Me | undefined): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [];
  for (const m of me?.memberships ?? []) {
    const code = m.department_code;
    if (m.is_active === false || !code || !(m.functions ?? []).includes("custody.track")) continue;
    if (!out.some((o) => o.value === code)) out.push({ value: code, label: code });
  }
  return out;
}

export function Held({ scope, params }: { scope: HeldScope; params: Params }) {
  const setFilters = useFilters(params);
  const me = useMe();
  const [open, setOpen] = useState<HeldItem | null>(null);
  const offset = offsetOf(params);
  const overdue = params.overdue === "true";
  const holderDepartment = scope === "owned" ? params.holder_department || undefined : undefined;
  const departments = useDepartments(scope === "owned");
  const listKey = scope === "owned" ? "held_owned" : "held";
  const query = {
    scope,
    overdue: overdue || undefined,
    holder_department: holderDepartment,
    ...toApiQuery(params, listKey),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: ["files", "held", query],
    queryFn: () => api<HeldList>("/custody/held", { query }),
    placeholderData: keepPreviousData,
  });
  const own: OwnControl[] = [
    { key: "overdue", kind: "check", label: T.files.overdueOnly },
    ...(scope === "owned"
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
      : []),
  ];
  const showHolder = scope !== "me";
  const columns: Column<HeldItem>[] = [
    {
      key: "due",
      header: T.files.due,
      width: "calc(var(--date-w) + var(--s6))",
      cell: (r) => <DateChip date={r.card?.due_date} hot={!!r.card?.overdue} />,
    },
    { key: "case", header: T.files.case, primary: true, cell: (r) => <CaseCell item={r} /> },
    ...(showHolder ? [{ key: "holder", header: T.files.holder, cell: (r: HeldItem) => <HolderCell item={r} /> }] : []),
    { key: "action", header: T.files.action, cell: (r) => <ActionCell item={r} /> },
    { key: "since", header: T.files.since, hideOnPhone: true, cell: (r) => formatDateTime(r.card?.since) },
    { key: "sent", header: T.files.sentBy, hideOnPhone: true, cell: (r) => <SentBy item={r} /> },
    { key: "open", header: <span className="visually-hidden">{T.files.details}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  const card = open?.card;
  return (
    <div className="stack">
      {scope === "owned" ? <TrackingSummary /> : null}
      <FilterBar
        list={listKey}
        params={params}
        own={own}
        ownerOptions={scope === "owned" ? trackedDepartments(me.data) : undefined}
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
            empty={<EmptyState>{EMPTY[scope]}</EmptyState>}
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
          [T.files.holder, open ? <HolderCell item={open} /> : null],
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
          [T.files.sentBy, open ? sentByText(open) : null],
        ]}
      />
    </div>
  );
}
