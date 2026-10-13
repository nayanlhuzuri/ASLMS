"use client";

/**
 * The Claimed tab (design portal-cases, decision 6): Active / Disposed, role, unit, officer and words; each row shows
 * the unit and officer it is allotted to and an "Allot" action with `cases.allot` in the selected department. The one
 * filter bar (design portal-filters): the shared case filters (no next hearing on Disposed; the status is the Active /
 * Disposed split) plus role, unit and officer.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar, type OwnControl } from "@/components/filters/FilterBar";
import {
  Badge,
  Button,
  CaseLink,
  EmptyState,
  ErrorBanner,
  Loading,
  Pagination,
  Table,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, useDepartmentPeople, useMe } from "@/lib/api/hooks";
import type { OwnershipList } from "@/lib/api/types";
import { canIn } from "@/lib/can";
import { toApiQuery } from "@/lib/filters";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { ListingLine, PartiesLine, useFilters } from "./common";
import { OwnershipDialogs, type DialogKind } from "./dialogs";

const STATES = ["active", "disposed"] as const;

export function Claimed({ params, department }: { params: Params; department: string }) {
  const me = useMe();
  const setFilters = useFilters(params);
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const canAllot = canIn(me.data, department, "cases.allot");
  const people = useDepartmentPeople(department, canAllot);
  const offset = offsetOf(params);
  const caseState = params.case_state === "disposed" ? "disposed" : "active";
  const listKey = caseState === "disposed" ? "claimed_disposed" : "claimed_active";
  const query = {
    office: department,
    case_state: caseState,
    role: params.role || undefined,
    unit: params.unit ? params.unit.toUpperCase() : undefined,
    officer_user_id: params.officer || undefined,
    ...toApiQuery(params, listKey),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "claimed", query],
    queryFn: () => api<OwnershipList>("/inbox/claimed", { query }),
  });
  const officers = new Map((people.data?.items ?? []).map((p) => [p.user_id, p.full_name]));
  const own: OwnControl[] = [
    {
      key: "role",
      kind: "select",
      label: T.inbox.role,
      options: Object.entries(T.inbox.roles)
        .filter(([value]) => value)
        .map(([value, label]) => ({ value, label })),
      placeholder: T.inbox.roles[""],
    },
    { key: "unit", kind: "text", label: T.inbox.unit, more: true },
    ...(canAllot
      ? [
          {
            key: "officer",
            kind: "select" as const,
            label: T.own.officer,
            options: [...officers.entries()].map(([value, label]) => ({ value, label })),
            placeholder: T.inbox.roles[""],
            more: true,
          },
        ]
      : []),
  ];
  return (
    <section className="stack" aria-label={T.inbox.caseState}>
      <div className="row" role="group" aria-label={T.inbox.caseState}>
        {STATES.map((st) => (
          <Button
            key={st}
            variant={st === caseState ? "primary" : "secondary"}
            aria-pressed={st === caseState}
            onClick={() => setFilters({ case_state: st === "active" ? undefined : st })}
          >
            {T.inbox.caseStates[st]}
          </Button>
        ))}
      </div>
      <FilterBar list={listKey} params={params} own={own} total={list.data?.total} />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.inbox.empty}</EmptyState>
        ) : (
          <>
            <Table caption={T.inbox.caseStates[caseState]}>
              <thead>
                <tr>
                  <th scope="col">{T.inbox.case}</th>
                  <th scope="col">{T.inbox.role}</th>
                  <th scope="col">{T.inbox.allottedTo}</th>
                  <th scope="col">{T.inbox.actions}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((o) => (
                  <tr key={o.id}>
                    <td>
                      <PartiesLine c={o.case} />
                      <CaseLink value={o.case} />
                      <ListingLine c={o.case} />
                    </td>
                    <td>
                      <Badge tone={o.role === "primary" ? "success" : undefined}>{T.inbox.roles[o.role] ?? o.role}</Badge>
                    </td>
                    <td>
                      {o.unit || o.officer ? (
                        <>
                          {o.unit ? <div className="mono">{o.unit.code}</div> : null}
                          {o.officer ? <div>{o.officer.full_name}</div> : null}
                        </>
                      ) : (
                        <span className="muted">{T.inbox.notAllotted}</span>
                      )}
                    </td>
                    <td>
                      {canAllot ? (
                        <Button
                          variant="secondary"
                          onClick={() =>
                            setDialog({
                              kind: "allot",
                              caseRef: o.case.ref_no,
                              department,
                              current: { unit: o.unit, officer: o.officer },
                            })
                          }
                        >
                          {T.own.allot}
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              offset={offset}
              limit={PAGE}
              total={list.data.total}
              onChange={(o) => setFilters({ offset: String(o) })}
            />
          </>
        )
      ) : null}
      <OwnershipDialogs open={dialog} onClose={() => setDialog(null)} department={department} />
    </section>
  );
}
