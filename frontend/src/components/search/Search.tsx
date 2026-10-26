"use client";

/**
 * Search (design portal-cases, decision 9; plan §5.2): one box as the API's `parse_query` (CNR, case number such as
 * `WP(C) 4326/2025`, `ref_no`, party or advocate words) with status, year, case type, department, listed from / to and
 * "only cases I can open". Without words the page lists the caller's visible cases (`GET /cases`): the work list of
 * officers, directorate users, standing counsel and State-wide readers. With words it calls `/cases/search`; a single
 * visible result matched by CNR or `ref_no` opens the case page. "Search the court" follows the local results, and the
 * "Order and document text" tab searches stored text. The one filter bar (design portal-filters): the box is its Words
 * field; the shared case filters with the owning department, Status in place of the old Active / Disposed / All
 * control, and "Only cases I can open" with words. Old links' `status=` and `office=` are read as `case_status` and
 * `owner`. "Only cases I can open" is ticked by default (design ownership-refinements, decision 8): the page sends
 * `visible_only=true` unless the address says `visible_only=false` (unticked); the API's own default stays `false`.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { FilterBar } from "@/components/filters/FilterBar";
import { EmptyState, ErrorBanner, Loading, PageHeader, Pagination, Tabs } from "@/components/ui";
import { useFilters } from "@/components/inbox/common";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { CaseSearchList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { checkIsOn, legacyParams, MIN_WORDS, toApiQuery, type SharedField } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, queryString, type Params } from "@/lib/params";
import { casePath } from "@/lib/refs";

import { CaseResults } from "./CaseResults";
import { CourtSearch } from "./CourtSearch";
import { TextSearch } from "./TextSearch";

/** The local search's fields (`GET /cases/search?field=`); `auto` is the default and is not sent. */
const SEARCH_FIELDS: readonly string[] = ["cnr", "number", "party", "advocate", "text"];

/** Layout B's More Filters on Search (design portal-ui-polish-2, decision 23): Case Type, Year and Department stay on
 * the right zone. */
const SEARCH_MORE: readonly SharedField[] = ["listed", "next", "case_status", "court_no", "bench"];

export function Search({ params }: { params: Params }) {
  const me = useMe();
  const tab = params.tab === "text" && can(me.data, "documents.view") ? "text" : "cases";
  return (
    <div className="stack">
      <PageHeader title={T.search.title} />
      {can(me.data, "documents.view") ? (
        <Tabs
          label={T.search.tabs}
          items={[
            { href: "/search" + queryString({ q: params.q }), label: T.search.cases, active: tab === "cases" },
            { href: "/search" + queryString({ tab: "text", q: params.q }), label: T.search.text, active: tab === "text" },
          ]}
        />
      ) : null}
      {tab === "text" ? <TextSearch params={params} /> : <CaseSearch params={params} />}
    </div>
  );
}

function CaseSearch({ params }: { params: Params }) {
  const me = useMe();
  const router = useRouter();
  const setFilters = useFilters(params);
  const q = (legacyParams(params, "search").q ?? "").trim();
  const words = q.length >= MIN_WORDS;
  const offset = offsetOf(params);
  const shared = toApiQuery(params, "search");
  delete shared.q; // the words go to /cases/search only (at least 3 characters)
  // the API's `field` when a link names one (`advocate` also opens the court search on "Advocate name")
  const field = params.field && SEARCH_FIELDS.includes(params.field) ? params.field : undefined;
  const query = words
    ? { ...shared, q, field, visible_only: checkIsOn(params.visible_only, true) ? true : undefined, limit: PAGE, offset }
    : { ...shared, limit: PAGE, offset };
  const path = words ? "/cases/search" : "/cases";
  const list = useQuery({
    queryKey: ["cases", path, query],
    queryFn: () => api<CaseSearchList>(path, { query }),
  });
  const single =
    words && offset === 0 && list.data?.total === 1 && list.data.items[0]?.visible &&
    (list.data.items[0].match === "cnr" || list.data.items[0].match === "ref_no")
      ? list.data.items[0]
      : null;
  useEffect(() => {
    if (single) router.replace(casePath(single.case.ref_no));
  }, [single, router]);

  const courtSearch = can(me.data, "cases.search_court");
  const found = (list.data?.items.length ?? 0) > 0;
  return (
    <section className="stack" aria-label={T.search.cases}>
      {/* design portal-ui-polish-2, decision 23: Layout B with Search For as the hero; Case Type, Year and Department
          on the right; the rest of the shared fields under More Filters; the total and the chips in the strip */}
      <FilterBar
        list="search"
        layout="card"
        hero="q"
        more={SEARCH_MORE}
        params={params}
        total={list.data?.total}
        wordsLabel={T.search.searchFor}
        wordsHint={T.search.searchForHint}
        own={
          words
            ? [
                {
                  key: "visible_only",
                  kind: "check",
                  label: T.search.visibleOnly,
                  defaultOn: true,
                  offLabel: T.search.alsoNotVisible,
                },
              ]
            : []
        }
      />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending || single ? <Loading /> : null}
      {list.data && !single ? (
        <>
          <h2>
            {words ? T.search.results : T.search.myCases}
            <span className="muted"> · {T.search.total(formatNumber(list.data.total), !!list.data.total_capped)}</span>
          </h2>
          {found ? (
            <>
              <CaseResults items={list.data.items} caption={words ? T.search.results : T.search.myCases} />
              <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
            </>
          ) : (
            <EmptyState>{T.search.none}</EmptyState>
          )}
        </>
      ) : null}
      {courtSearch && list.data && !single ? (
        <CourtSearch key={`${q}|${field ?? ""}`} initialQuery={q} initialField={field} prominent={!found && words} />
      ) : null}
    </section>
  );
}

/** `/cases` (the breadcrumb above a case page): the search page. */
export function CasesIndex() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/search");
  }, [router]);
  return <Loading />;
}
