"use client";

/**
 * "Next dates to confirm" (design portal-next-dates, decisions 1, 2, 4 and 16; plan §5.3, §5.7): the second tab of
 * Alerts. `GET /next-dates/review` paged by 50 in the API's order (the date to answer by, then the case),
 * with the one filter bar: the shared case fields with the owning department, and "Show" (`kind`). Every row the API
 * returns may be acted on; the API decides every call. The notice of an action and a stale answer show above the
 * list, because the row they came from leaves it.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import { DataTable, EmptyState, ErrorBanner, Loading, Notice, Pagination } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { NextDateReviewItem, NextDateReviewList } from "@/lib/api/types";
import { can, departmentsOf } from "@/lib/can";
import { hasCaseFilter, toApiQuery } from "@/lib/filters";
import { NEXT_DATE_ERRORS, T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { NEXT_DATES_KEY } from "./common";
import type { DialogOutcome } from "./Dialogs";
import { reviewColumns } from "./ReviewItem";

const KINDS = ["confirm", "enter"] as const;

/** The rows of review items as one table with headers (the list and the case page's panel). */
export function ReviewTable({
  items,
  caption,
  showCase,
  ...outcome
}: { items: NextDateReviewItem[]; caption: string; showCase: boolean } & DialogOutcome) {
  const me = useMe();
  const showDepartment = departmentsOf(me.data).length > 1;
  const canViewOrder = can(me.data, "documents.view");
  return (
    <DataTable
      caption={caption}
      rows={items}
      rowKey={(item) => `${item.kind}-${item.id}`}
      columns={reviewColumns({ showCase, showDepartment, canViewOrder, ...outcome })}
    />
  );
}

export function ReviewList({ params }: { params: Params }) {
  const setFilters = useFilters(params);
  const offset = offsetOf(params);
  const kind = (KINDS as readonly string[]).includes(params.kind ?? "") ? params.kind : undefined;
  const filters = { kind, ...toApiQuery(params, "next_dates") };
  const [notice, setNotice] = useState<string | null>(null);
  const [stale, setStale] = useState<unknown>(null);
  const list = useQuery({
    queryKey: [...NEXT_DATES_KEY, "review", filters, offset],
    queryFn: () => api<NextDateReviewList>("/next-dates/review", { query: { ...filters, limit: PAGE, offset } }),
    placeholderData: keepPreviousData,
  });
  const defaults = !kind && offset === 0 && !hasCaseFilter(params, "next_dates");
  const outcome: DialogOutcome = {
    onDone: (text) => {
      setStale(null);
      setNotice(text);
    },
    onStale: (err) => {
      setNotice(null);
      setStale(err);
    },
  };
  return (
    <div className="stack">
      <FilterBar
        list="next_dates"
        params={params}
        own={[
          {
            key: "kind",
            kind: "select",
            label: T.nd.show,
            options: KINDS.map((k) => ({ value: k, label: T.nd.kinds[k] ?? k })),
            placeholder: T.nd.kinds[""],
          },
        ]}
        total={list.data?.total}
        noun={T.nd.noun}
      />
      {notice ? <Notice>{notice}</Notice> : null}
      <ErrorBanner error={stale} messages={NEXT_DATE_ERRORS} />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} messages={NEXT_DATE_ERRORS} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{defaults ? T.nd.emptyDefault : T.nd.empty}</EmptyState>
        ) : (
          <>
            <ReviewTable items={list.data.items} caption={T.nd.list} showCase {...outcome} />
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
          </>
        )
      ) : null}
      <p className="muted">{T.nd.onlyYours}</p>
    </div>
  );
}
