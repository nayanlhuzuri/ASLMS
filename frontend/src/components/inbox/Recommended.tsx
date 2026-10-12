"use client";

/**
 * The Recommended tab (design portal-cases, decision 5; Annexure B "Case inbox"): the department's active
 * recommendations in the API's order (strong first, score, next hearing), each with the score badge from the API's
 * `band`, the parties, the case number, the latest listing, one chip per signal, "Suggested by" and "Owned by", and
 * Claim / Dismiss / Suggest department by the function of the selected department's membership.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  Button,
  CaseLink,
  EmptyState,
  ErrorBanner,
  Loading,
  Pagination,
  ScoreBadge,
  SelectField,
  SignalChips,
  Table,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, useMe } from "@/lib/api/hooks";
import type { RecommendationList } from "@/lib/api/types";
import { canIn } from "@/lib/can";
import { addDays, istDay } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";
import type { Signal } from "@/lib/signals";

import { ListingLine, PartiesLine, useFilters } from "./common";
import { OwnershipDialogs, type DialogKind } from "./dialogs";

/** The cause-list date choice as `listed_from` / `listed_to` (IST days). */
export function listedRange(choice: string | undefined, now: Date = new Date()): { listed_from?: string; listed_to?: string } {
  const today = istDay(now);
  if (choice === "today") return { listed_from: today, listed_to: today };
  if (choice === "d7") return { listed_from: addDays(today, -6), listed_to: today };
  if (choice === "d30") return { listed_from: addDays(today, -29), listed_to: today };
  return {};
}

export function Recommended({ params, department }: { params: Params; department: string }) {
  const me = useMe();
  const setFilters = useFilters(params);
  const [q, setQ] = useState(params.q ?? "");
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const offset = offsetOf(params);
  const query = {
    office: department,
    band: params.band || undefined,
    q: params.q || undefined,
    ...listedRange(params.listed),
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
      <form
        className="row"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters({ q: q.trim() || undefined });
        }}
      >
        <SelectField
          label={T.inbox.strength}
          options={Object.entries(T.inbox.strengths).map(([value, label]) => ({ value, label }))}
          value={params.band ?? ""}
          onChange={(e) => setFilters({ band: e.target.value || undefined })}
        />
        <SelectField
          label={T.inbox.listDate}
          options={["", "today", "d7", "d30"].map((value) => ({ value, label: T.inbox.listDates[value]! }))}
          value={params.listed ?? ""}
          onChange={(e) => setFilters({ listed: e.target.value || undefined })}
        />
        <TextField label={T.inbox.words} value={q} onChange={(e) => setQ(e.target.value)} />
        <Button type="submit" variant="secondary">
          {T.inbox.apply}
        </Button>
      </form>
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
                            <Button variant="secondary" onClick={() => setDialog({ kind: "suggest", caseRef: ref })}>
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
