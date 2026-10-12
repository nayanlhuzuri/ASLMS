"use client";

/**
 * Search (design portal-cases, decision 9; plan §5.2): one box as the API's `parse_query` (CNR, case number such as
 * `WP(C) 4326/2025`, `ref_no`, party or advocate words) with status, year, case type, department, listed from / to and
 * "only cases I can open". Without words the page lists the caller's visible cases (`GET /cases`): the work list of
 * officers, directorate users, standing counsel and State-wide readers. With words it calls `/cases/search`; a single
 * visible result matched by CNR or `ref_no` opens the case page. "Search the court" follows the local results, and the
 * "Order and document text" tab searches stored text.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, CheckField, EmptyState, ErrorBanner, Loading, Pagination, SelectField, Tabs, TextField } from "@/components/ui";
import { useFilters } from "@/components/inbox/common";
import { api } from "@/lib/api/client";
import { useCaseTypes, useMe } from "@/lib/api/hooks";
import type { CaseSearchList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, queryString, type Params } from "@/lib/params";
import { casePath } from "@/lib/refs";

import { CaseResults } from "./CaseResults";
import { CourtSearch } from "./CourtSearch";
import { TextSearch } from "./TextSearch";

const MIN_QUERY = 3;
const FORM_KEYS = ["q", "year", "office", "listed_from", "listed_to", "next_from", "next_to"] as const;

export function Search({ params }: { params: Params }) {
  const me = useMe();
  const tab = params.tab === "text" && can(me.data, "documents.view") ? "text" : "cases";
  return (
    <div className="stack">
      <h1>{T.search.title}</h1>
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
  const types = useCaseTypes();
  const [form, setForm] = useState<Record<string, string>>(() =>
    Object.fromEntries(FORM_KEYS.map((k) => [k, params[k] ?? ""])),
  );
  const q = (params.q ?? "").trim();
  const words = q.length >= MIN_QUERY;
  const offset = offsetOf(params);
  const common = {
    status: params.status || undefined,
    year: params.year || undefined,
    case_type: params.case_type || undefined,
    office: params.office || undefined,
    listed_from: params.listed_from || undefined,
    listed_to: params.listed_to || undefined,
    limit: PAGE,
    offset,
  };
  const query = words
    ? { ...common, q, visible_only: params.visible_only === "true" ? true : undefined }
    : {
        ...common,
        case_state: params.case_state || undefined,
        next_from: params.next_from || undefined,
        next_to: params.next_to || undefined,
      };
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

  const set = (key: string) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const courtSearch = can(me.data, "cases.search_court");
  const found = (list.data?.items.length ?? 0) > 0;
  return (
    <section className="stack" aria-label={T.search.cases}>
      <form
        className="stack"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(Object.fromEntries(FORM_KEYS.map((k) => [k, form[k]?.trim() || undefined])));
        }}
      >
        <div className="row">
          <TextField label={T.search.box} value={form.q ?? ""} onChange={set("q")} style={{ minWidth: 320 }} />
          <Button type="submit">{T.search.go}</Button>
        </div>
        <div className="row">
          <SelectField
            label={T.search.status}
            options={Object.entries(T.inbox.statuses).map(([value, label]) => ({ value, label }))}
            value={params.status ?? ""}
            onChange={(e) => setFilters({ status: e.target.value || undefined })}
          />
          <TextField label={T.search.year} type="number" value={form.year ?? ""} onChange={set("year")} />
          <SelectField
            label={T.search.caseType}
            options={(types.data ?? [])
              .filter((t) => t.short_name)
              .map((t) => ({ value: t.short_name!, label: `${t.short_name}${t.full_name ? ` — ${t.full_name}` : ""}` }))}
            placeholder={T.search.anyType}
            value={params.case_type ?? ""}
            onChange={(e) => setFilters({ case_type: e.target.value || undefined })}
          />
          <TextField label={T.search.department} value={form.office ?? ""} onChange={set("office")} />
          <TextField label={T.search.listedFrom} type="date" value={form.listed_from ?? ""} onChange={set("listed_from")} />
          <TextField label={T.search.listedTo} type="date" value={form.listed_to ?? ""} onChange={set("listed_to")} />
        </div>
        {words ? (
          <CheckField
            label={T.search.visibleOnly}
            checked={params.visible_only === "true"}
            onChange={(e) => setFilters({ visible_only: e.target.checked ? "true" : undefined })}
          />
        ) : (
          <div className="row">
            <SelectField
              label={T.search.caseState}
              options={Object.entries(T.search.caseStates).map(([value, label]) => ({ value, label }))}
              value={params.case_state ?? "all"}
              onChange={(e) => setFilters({ case_state: e.target.value === "all" ? undefined : e.target.value })}
            />
            <TextField label={T.search.nextFrom} type="date" value={form.next_from ?? ""} onChange={set("next_from")} />
            <TextField label={T.search.nextTo} type="date" value={form.next_to ?? ""} onChange={set("next_to")} />
          </div>
        )}
      </form>
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
      {courtSearch && list.data && !single ? <CourtSearch key={q} initialQuery={q} prominent={!found && words} /> : null}
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
