"use client";

/**
 * The Recommended tab (design portal-cases, decision 5; Annexure B "Case inbox"): the department's active
 * recommendations in the API's order (strong first, score, next hearing), each with the score badge from the API's
 * `band`, the parties, the case number, the latest listing, one chip per signal, "Suggested by" and "Owned by", and
 * Claim / Dismiss / Suggest department by the function of the selected department's membership. Every action acts for
 * the selected department (Suggest sends it as `from_office_code`, design portal-cases-followups, decision 6). The one
 * filter bar (design portal-filters): the shared case filters plus match strength; `listed=today|d7|d30` links keep
 * their meaning.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar } from "@/components/filters/FilterBar";
import {
  Button,
  CaseLink,
  EmptyState,
  ErrorBanner,
  Loading,
  Pagination,
  ScoreBadge,
  SignalChips,
  Table,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, useMe } from "@/lib/api/hooks";
import type { RecommendationList } from "@/lib/api/types";
import { canIn } from "@/lib/can";
import { toApiQuery } from "@/lib/filters";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";
import type { Signal } from "@/lib/signals";

import { ListingLine, PartiesLine, useFilters } from "./common";
import { OwnershipDialogs, type DialogKind } from "./dialogs";

export function Recommended({ params, department }: { params: Params; department: string }) {
  const me = useMe();
  const setFilters = useFilters(params);
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const offset = offsetOf(params);
  const query = {
    office: department,
    band: params.band || undefined,
    ...toApiQuery(params, "recommended"),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "recommended", query],
    queryFn: () => api<RecommendationList>("/inbox/recommended", { query }),
  });
  const canClaim = canIn(me.data, department, "cases.claim");
  const canDismiss = canIn(me.data, department, "cases.dismiss");
  const canSuggest = canIn(me.data, department, "cases.suggest_elsewhere");
  return (
    <section className="stack" aria-label={T.inbox.title}>
      <FilterBar
        list="recommended"
        params={params}
        own={[
          {
            key: "band",
            kind: "select",
            label: T.inbox.strength,
            options: Object.entries(T.inbox.strengths)
              .filter(([value]) => value)
              .map(([value, label]) => ({ value, label })),
            placeholder: T.inbox.strengths[""],
          },
        ]}
        total={list.data?.total}
      />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.inbox.empty}</EmptyState>
        ) : (
          <>
            <Table caption={T.inbox.title}>
              <thead>
                <tr>
                  <th scope="col">{T.inbox.score}</th>
                  <th scope="col">{T.inbox.case}</th>
                  <th scope="col">{T.inbox.actions}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((r) => {
                  const ref = r.case.ref_no;
                  return (
                    <tr key={r.id}>
                      <td>
                        <ScoreBadge score={r.score} band={r.band} />
                      </td>
                      <td>
                        <PartiesLine c={r.case} />
                        <CaseLink value={r.case} />
                        <ListingLine c={r.case} />
                        <SignalChips signals={r.signals as Signal[]} />
                        {r.origin === "suggestion" && r.suggested_by_office_code ? (
                          <div className="muted">{T.inbox.suggestedBy(r.suggested_by_office_code, r.reason)}</div>
                        ) : null}
                        {r.current_owner_code ? <div className="muted">{T.inbox.ownedBy(r.current_owner_code)}</div> : null}
                      </td>
                      <td>
                        <div className="row">
                          {canClaim ? (
                            <Button
                              onClick={() => setDialog({ kind: "claim", caseRef: ref, currentOwner: r.current_owner_code })}
                            >
                              {T.own.claim}
                            </Button>
                          ) : null}
                          {canDismiss ? (
                            <Button variant="secondary" onClick={() => setDialog({ kind: "dismiss", caseRef: ref })}>
                              {T.own.dismiss}
                            </Button>
                          ) : null}
                          {canSuggest ? (
                            <Button
                              variant="secondary"
                              onClick={() =>
                                setDialog({
                                  kind: "suggest",
                                  caseRef: ref,
                                  from: department,
                                  exclude: [r.current_owner_code],
                                })
                              }
                            >
                              {T.own.suggest}
                            </Button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
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
