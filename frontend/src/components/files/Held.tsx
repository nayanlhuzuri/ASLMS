"use client";

/**
 * The held-files lists of "Files" (design portal-files-alerts, decision 12; custody-workflow decision 24):
 * With me (`scope=me`), My offices (`scope=office`) and Department files (`scope=owned`, with the tracking summary
 * and the holder-department filter). The API's order (due date, then since), paged by 50 in the query string. No
 * action buttons: sending and recalling happen on the case page, where the card's flags are current.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useFilters } from "@/components/inbox/common";
import { Badge, CaseLink, CheckField, EmptyState, ErrorBanner, Loading, Pagination, SelectField, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useDepartments } from "@/lib/api/hooks";
import type { HeldItem, HeldList } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import s from "./files.module.css";
import { Remark } from "./Remark";
import { TRACK_ERRORS, TrackingSummary } from "./TrackingSummary";

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
      {card.holder_user ? (
        <div>{[card.holder_user.full_name, card.holder_user.designation].filter(Boolean).join(", ")}</div>
      ) : null}
    </>
  );
}

function DueCell({ item }: { item: HeldItem }) {
  const card = item.card;
  if (!card?.due_date) return <span className="muted">—</span>;
  return (
    <>
      <div>{formatDate(card.due_date)}</div>
      {card.overdue ? <Badge tone="danger">{T.files.overdueBy(card.overdue_days)}</Badge> : null}
    </>
  );
}

export function Held({ scope, params }: { scope: HeldScope; params: Params }) {
  const setFilters = useFilters(params);
  const offset = offsetOf(params);
  const overdue = params.overdue === "true";
  const holderDepartment = scope === "owned" ? params.holder_department || undefined : undefined;
  const departments = useDepartments(scope === "owned");
  const filters = { overdue: overdue || undefined, holder_department: holderDepartment };
  const list = useQuery({
    queryKey: ["files", scope, filters, offset],
    queryFn: () => api<HeldList>("/custody/held", { query: { scope, ...filters, limit: PAGE, offset } }),
    placeholderData: keepPreviousData,
  });
  const showHolder = scope !== "me";
  return (
    <div className="stack">
      {scope === "owned" ? <TrackingSummary /> : null}
      <div className={`row ${s.filters}`}>
        <CheckField
          label={T.files.overdueOnly}
          checked={overdue}
          onChange={(e) => setFilters({ overdue: e.target.checked ? "true" : undefined })}
        />
        {scope === "owned" ? (
          <SelectField
            label={T.files.holderDepartment}
            placeholder={T.files.allDepartments}
            options={(departments.data?.departments ?? []).map((d) => ({ value: d.code, label: `${d.code} — ${d.name}` }))}
            value={holderDepartment ?? ""}
            onChange={(e) => setFilters({ holder_department: e.target.value || undefined })}
          />
        ) : null}
      </div>
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} messages={TRACK_ERRORS} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{EMPTY[scope]}</EmptyState>
        ) : (
          <>
            <Table caption={CAPTION[scope]}>
              <thead>
                <tr>
                  <th scope="col">{T.files.case}</th>
                  {showHolder ? <th scope="col">{T.files.holder}</th> : null}
                  <th scope="col">{T.files.action}</th>
                  <th scope="col">{T.files.since}</th>
                  <th scope="col">{T.files.due}</th>
                  <th scope="col">{T.files.sentBy}</th>
                  <th scope="col">{T.files.remark}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((item) => (
                  <tr key={item.case.id}>
                    <td>
                      <CaseLink value={item.case} />
                    </td>
                    {showHolder ? (
                      <td>
                        <HolderCell item={item} />
                      </td>
                    ) : null}
                    <td>{item.card?.pending_action_label ?? "—"}</td>
                    <td>{formatDateTime(item.card?.since)}</td>
                    <td>
                      <DueCell item={item} />
                    </td>
                    <td>
                      <SentBy item={item} />
                    </td>
                    <td>
                      <Remark text={item.card?.remark} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
          </>
        )
      ) : null}
    </div>
  );
}
