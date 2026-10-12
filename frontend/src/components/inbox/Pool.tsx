"use client";

/**
 * The Unclaimed pool (design portal-cases, decision 6): cases that have never had a primary owner, with words, listed
 * from / to, status, case type, year, minimum score and "State is a party"; each row shows the best score and the
 * department it was for, the departments that dismissed it and the next hearing. Claim needs `cases.claim` in the
 * selected department; Suggest department (`cases.suggest_elsewhere`) is how the central operator follows up an
 * unclaimed case (plan §4.2); a pool case has no active recommendation to suggest from, so no originating department is
 * sent (design portal-cases-followups, decision 6). The pool's `total` is shown above the list.
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
  SelectField,
  Table,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, useMe } from "@/lib/api/hooks";
import type { PoolList } from "@/lib/api/types";
import { can, canIn } from "@/lib/can";
import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { ListingLine, PartiesLine, useFilters } from "./common";
import { OwnershipDialogs, type DialogKind } from "./dialogs";

const TEXT_FILTERS = ["q", "listed_from", "listed_to", "case_type", "year", "min_score"] as const;

export function Pool({ params, department }: { params: Params; department: string | null }) {
  const me = useMe();
  const setFilters = useFilters(params);
  const [form, setForm] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FILTERS.map((k) => [k, params[k] ?? ""])),
  );
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const offset = offsetOf(params);
  const query = {
    q: params.q || undefined,
    listed_from: params.listed_from || undefined,
    listed_to: params.listed_to || undefined,
    status: params.status || undefined,
    case_type: params.case_type || undefined,
    year: params.year || undefined,
    min_score: params.min_score || undefined,
    state_party: params.state_party || undefined,
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "pool", query],
    queryFn: () => api<PoolList>("/inbox/pool", { query }),
  });
  const canClaim = canIn(me.data, department, "cases.claim");
  const canSuggest = can(me.data, "cases.suggest_elsewhere");
  const field = (key: (typeof TEXT_FILTERS)[number], label: string, type = "text") => (
    <TextField
      label={label}
      type={type}
      value={form[key] ?? ""}
      onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
    />
  );
  return (
    <section className="stack" aria-label={T.inbox.poolTotal("")}>
      <form
        className="row"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(Object.fromEntries(TEXT_FILTERS.map((k) => [k, form[k]?.trim() || undefined])));
        }}
      >
        {field("q", T.inbox.words)}
        {field("listed_from", T.inbox.listedFrom, "date")}
        {field("listed_to", T.inbox.listedTo, "date")}
        <SelectField
          label={T.inbox.status}
          options={Object.entries(T.inbox.statuses).map(([value, label]) => ({ value, label }))}
          value={params.status ?? ""}
          onChange={(e) => setFilters({ status: e.target.value || undefined })}
        />
        {field("case_type", T.inbox.caseType)}
        {field("year", T.inbox.year, "number")}
        {field("min_score", T.inbox.minScore, "number")}
        <SelectField
          label={T.inbox.stateParty}
          options={Object.entries(T.inbox.stateParties).map(([value, label]) => ({ value, label }))}
          value={params.state_party ?? ""}
          onChange={(e) => setFilters({ state_party: e.target.value || undefined })}
        />
        <Button type="submit" variant="secondary">
          {T.inbox.apply}
        </Button>
      </form>
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <p className="muted">{T.inbox.poolTotal(formatNumber(list.data.total))}</p>
          {list.data.items.length === 0 ? (
            <EmptyState>{T.inbox.empty}</EmptyState>
          ) : (
            <>
              <Table caption={T.inbox.poolTotal(formatNumber(list.data.total))}>
                <thead>
                  <tr>
                    <th scope="col">{T.inbox.case}</th>
                    <th scope="col">{T.inbox.score}</th>
                    <th scope="col">{T.inbox.actions}</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((p) => (
                    <tr key={p.case.id}>
                      <td>
                        <PartiesLine c={p.case} />
                        <CaseLink value={p.case} />
                        <ListingLine c={p.case} />
                      </td>
                      <td>
                        <div>
                          {p.best_score !== null ? T.inbox.best(p.best_score.toFixed(3), p.best_office_code) : T.inbox.noScore}
                        </div>
                        {p.dismissed_by.length > 0 ? (
                          <div className="muted">{T.inbox.dismissedBy(p.dismissed_by.join(", "))}</div>
                        ) : null}
                      </td>
                      <td>
                        <div className="row">
                          {canClaim ? (
                            <Button onClick={() => setDialog({ kind: "claim", caseRef: p.case.ref_no })}>{T.own.claim}</Button>
                          ) : null}
                          {canSuggest ? (
                            <Button
                              variant="secondary"
                              onClick={() => setDialog({ kind: "suggest", caseRef: p.case.ref_no, exclude: [department] })}
                            >
                              {T.own.suggest}
                            </Button>
                          ) : null}
                        </div>
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
          )}
        </>
      ) : null}
      <OwnershipDialogs open={dialog} onClose={() => setDialog(null)} department={department} />
    </section>
  );
}
