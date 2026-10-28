"use client";

/**
 * Court search (design department-discovery, decision 13b; owner's decisions of 14 Oct 2026), a Department mapping tab
 * under `admin.keywords`: the department's names searched at the High Court (its keywords and name patterns ticked
 * "Search the court") with the years searched, the last search and the cases found, and per name the found cases with
 * their owner, our recommendation and Claim (the shared `ClaimDialog`). A user may ask for older years of a name: they
 * pick the name and the years and press Search; the searches are queued for the worker and found cases appear here as
 * they arrive. No call counts or allowance are shown, and no "searched before" question: the user may search a name
 * and year as often as they like (owner, 14 Oct 2026). Summaries only; the API decides every list and action. Both
 * lists search and sort on the server (design list-search, decision 15): Names Searched by the name and the department
 * codes, sorted by Name, Last Searched or Cases Found; a name's cases by the case search (CNR, case number or party
 * words) beside Show, sorted by Last Found, Case Number or Year.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { ClaimDialog } from "@/components/inbox/dialogs";
import { PartiesLine } from "@/components/inbox/common";
import {
  Badge,
  Button,
  CaseLink,
  EmptyState,
  ErrorBanner,
  ListCount,
  ListSearch,
  ListSort,
  ListToolbar,
  Loading,
  NoMatches,
  Notice,
  OrderLine,
  Pagination,
  ScoreBadge,
  SelectField,
  DataTable,
  sortOptionsOf,
  TextField,
  type Column,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, MAPPING_KEY } from "@/lib/api/hooks";
import type { DiscoveryCase, DiscoveryCaseList, DiscoverySearch, DiscoveryTerm, DiscoveryTermList } from "@/lib/api/types";
import { isDiscoverable, normaliseTerm, parseYears } from "@/lib/discovery";
import { formatDateTime, formatNumber } from "@/lib/format";
import { CASE_MIN_CHARS, searchShown } from "@/lib/listSearch";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";
import { useListState } from "@/lib/useListState";

export const DISCOVERY_KEY = [...MAPPING_KEY, "discovery"] as const;
const LIMIT = 50;
const ONLY = ["all", "pool", "recommended", "owned"] as const;
const TERM_SORTS = ["name", "last_searched", "cases_found"] as const;
const CASE_SORTS = ["last_found", "case_no", "year"] as const;

function termsQuery(q: string, sort: string | undefined, dir: string | undefined) {
  return {
    queryKey: [...DISCOVERY_KEY, "terms", { q, sort: sort ?? null, dir: dir ?? null }],
    queryFn: () =>
      api<DiscoveryTermList>("/admin/discovery/terms", { query: { status: "all", limit: 200, q: q || undefined, sort, dir } }),
  };
}

export function CourtSearch() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<DiscoveryTerm | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const state = useListState({ mode: "local", search: "server", sortKeys: TERM_SORTS });
  // every name for the Name field's suggestions; the list below follows its own search and sort
  const allTerms = useQuery(termsQuery("", undefined, undefined));
  const terms = useQuery(termsQuery(state.applied, state.sort?.key, state.sort?.dir));
  const refresh = () => queryClient.invalidateQueries({ queryKey: DISCOVERY_KEY });
  const searching = state.applied !== "";
  const unfiltered = terms.data ? (terms.data.total_all ?? terms.data.total) : allTerms.data?.total;
  const columns: Column<DiscoveryTerm>[] = [
    {
      key: "term",
      header: T.discovery.term,
      primary: true,
      sort: { key: "name", type: "text" },
      cell: (t) => (
        <>
          <span className="mono">{t.term}</span>
          {t.active ? null : (
            <>
              {" "}
              <Badge>{T.discovery.inactive}</Badge>
            </>
          )}
        </>
      ),
    },
    {
      key: "rules",
      header: T.discovery.rules,
      cell: (t) => t.rules.map((r) => `${T.mapping.kindShort[r.kind] ?? T.mapping.keyword} · ${r.office_code}`).join("; "),
    },
    { key: "done", header: T.discovery.yearsDone, align: "right", cell: (t) => formatNumber(t.years.done) },
    { key: "waiting", header: T.discovery.yearsWaiting, align: "right", cell: (t) => formatNumber(t.years.waiting) },
    { key: "failed", header: T.discovery.yearsFailed, align: "right", cell: (t) => formatNumber(t.years.failed) },
    {
      key: "last",
      header: T.discovery.lastSearched,
      sort: { key: "last_searched", type: "date" },
      cell: (t) => (t.last_searched_at ? formatDateTime(t.last_searched_at) : T.discovery.notYetSearched),
    },
    {
      key: "found",
      header: T.discovery.casesFound,
      align: "right",
      sort: { key: "cases_found", type: "number" },
      cell: (t) => formatNumber(t.cases_found),
    },
    { key: "new", header: T.discovery.newThisWeek, align: "right", cell: (t) => formatNumber(t.found_last_7_days) },
    {
      key: "actions",
      header: T.mapping.actions,
      cell: (t) => (
        <Button variant="link" aria-label={T.discovery.showCasesFor(t.term)} aria-pressed={selected?.id === t.id} onClick={() => setSelected(t)}>
          {T.discovery.showCases}
        </Button>
      ),
    },
  ];
  const options = sortOptionsOf(columns);
  return (
    <section className="stack" aria-label={T.discovery.tab}>
      <p className="muted">{T.discovery.intro}</p>
      <AskYears
        terms={allTerms.data?.items ?? []}
        onQueued={(out) => {
          setNotice(T.discovery.searching);
          const term = allTerms.data?.items.find((t) => t.id === out.term_id) ?? null;
          if (term) setSelected(term);
          void refresh();
        }}
      />
      {notice ? <Notice>{notice}</Notice> : null}
      <h3>{T.discovery.terms}</h3>
      {unfiltered !== undefined && unfiltered > 0 ? (
        <ListToolbar
          search={
            searchShown(unfiltered, state.q) ? (
              <ListSearch
                label={T.discovery.searchNamesLabel}
                placeholder={T.discovery.searchNamesPlaceholder}
                value={state.q}
                onChange={state.setQ}
                onEnter={state.apply}
                minChars={2}
                busy={terms.isFetching && searching}
              />
            ) : null
          }
          sort={state.stacked ? <ListSort options={options} sort={state.sort} onSort={state.setSort} defaultLabel={T.discovery.namesDefault} /> : null}
          order={<OrderLine options={options} sort={state.sort} defaultLabel={T.discovery.namesDefault} onReset={state.resetSort} />}
          count={<ListCount shown={terms.data?.total} total={terms.data?.total_all} noun={T.mapping.namesNoun} nounOne={T.mapping.nameNoun} searching={searching} />}
        />
      ) : null}
      {terms.isPending ? <Loading /> : null}
      <ErrorBanner error={terms.error} onRetry={() => terms.refetch()} />
      {terms.data ? (
        terms.data.items.length === 0 ? (
          searching ? (
            <NoMatches q={state.applied} onClear={state.clear} />
          ) : (
            <EmptyState>{T.discovery.noTerms}</EmptyState>
          )
        ) : (
          <DataTable
            caption={T.discovery.terms}
            rows={terms.data.items}
            rowKey={(t) => t.id}
            columns={columns}
            sort={state.sort}
            onSort={state.setSort}
            defaultSort={{ key: "name", dir: "asc" }}
            onStackedChange={state.setStacked}
          />
        )
      ) : null}
      {selected ? <TermCases key={selected.id} term={selected} /> : null}
    </section>
  );
}

/** The name and the years to search; every search is queued, with no warning (owner, 14 Oct 2026). */
function AskYears({ terms, onQueued }: { terms: DiscoveryTerm[]; onQueued: (out: DiscoverySearch) => void }) {
  const listId = useId();
  const [name, setName] = useState("");
  const [years, setYears] = useState("");
  const [problem, setProblem] = useState<{ name?: string; years?: string }>({});
  const action = useAction();
  const thisYear = new Date().getFullYear();

  async function send(body: { name: string; years: number[] }) {
    const out = await action.run(() => api<DiscoverySearch>("/admin/discovery/search", { method: "POST", body }));
    if (out.ok) {
      setYears("");
      onQueued(out.value);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const parsed = parseYears(years, thisYear);
    const next: { name?: string; years?: string } = {};
    if (!isDiscoverable(name)) next.name = T.discovery.badName;
    if (!parsed) next.years = T.discovery.badYears;
    setProblem(next);
    if (next.name || next.years || !parsed) return;
    await send({ name: normaliseTerm(name), years: parsed });
  }

  return (
    <section className="stack" aria-label={T.discovery.askTitle}>
      <h3>{T.discovery.askTitle}</h3>
      <form className="row" onSubmit={submit} aria-label={T.discovery.askTitle}>
        <TextField
          label={T.discovery.name}
          hint={T.discovery.nameHint}
          required
          maxLength={200}
          list={listId}
          value={name}
          error={problem.name}
          onChange={(e) => setName(e.target.value)}
        />
        <datalist id={listId}>
          {terms
            .filter((t) => t.active)
            .map((t) => (
              <option key={t.id} value={t.term} />
            ))}
        </datalist>
        <TextField
          label={T.discovery.years}
          hint={T.discovery.yearsHint}
          required
          value={years}
          error={problem.years}
          onChange={(e) => setYears(e.target.value)}
        />
        <Button type="submit" busy={action.busy}>
          {T.discovery.search}
        </Button>
      </form>
      <ErrorBanner error={action.error} />
    </section>
  );
}

/** The cases a name found, with Claim through the shared dialog. */
function TermCases({ term }: { term: DiscoveryTerm }) {
  const queryClient = useQueryClient();
  const [only, setOnly] = useState<(typeof ONLY)[number]>("all");
  const [offset, setOffset] = useState(0);
  const [claiming, setClaiming] = useState<string | null>(null);
  const state = useListState({ mode: "local", search: "server", sortKeys: CASE_SORTS, minChars: CASE_MIN_CHARS });
  const q = state.applied;
  const sort = state.sort;
  const list = useQuery({
    queryKey: [...DISCOVERY_KEY, "cases", term.id, only, offset, q, sort?.key ?? null, sort?.dir ?? null],
    queryFn: () =>
      api<DiscoveryCaseList>(`/admin/discovery/terms/${term.id}/cases`, {
        query: { only, limit: LIMIT, offset, q: q || undefined, sort: sort?.key, dir: sort?.dir },
      }),
  });
  // a new search or a new sort goes back to the first page
  const [seenQuery, setSeenQuery] = useState(`${q}|${sort?.key}|${sort?.dir}`);
  if (seenQuery !== `${q}|${sort?.key}|${sort?.dir}`) {
    setSeenQuery(`${q}|${sort?.key}|${sort?.dir}`);
    setOffset(0);
  }
  const searching = q !== "";
  const columns: Column<DiscoveryCase>[] = [
    {
      key: "case",
      header: T.inbox.case,
      label: T.discovery.caseNumber,
      primary: true,
      sort: { key: "case_no", type: "caseNo" },
      cell: (item) => (
        <>
          <PartiesLine c={item.case} />
          <CaseLink value={item.case} />
        </>
      ),
    },
    { key: "year", header: T.discovery.foundYear, align: "right", sort: { key: "year", type: "number" }, cell: (item) => item.reg_year },
    {
      key: "found",
      header: T.discovery.found,
      sort: { key: "last_found", type: "date" },
      cell: (item) => formatDateTime(item.last_found_at),
    },
    { key: "owner", header: T.discovery.owner, cell: (item) => item.owner_office_code ?? "—" },
    {
      key: "recommendation",
      header: T.discovery.recommendation,
      cell: (item) =>
        item.recommendation ? (
          <>
            <ScoreBadge score={item.recommendation.score} band={item.recommendation.band} /> {item.recommendation.office_code}
          </>
        ) : (
          "—"
        ),
    },
    {
      key: "actions",
      header: T.mapping.actions,
      cell: (item) =>
        item.claimable ? (
          <Button variant="secondary" onClick={() => setClaiming(item.case.ref_no)}>
            {T.own.claim}
          </Button>
        ) : null,
    },
  ];
  const options = sortOptionsOf(columns);
  return (
    <section className="stack" aria-label={T.discovery.casesOf(term.term)}>
      <h3>{T.discovery.casesOf(term.term)}</h3>
      <ListToolbar
        search={
          <ListSearch
            label={T.discovery.searchCasesLabel}
            placeholder={T.discovery.searchCasesPlaceholder}
            value={state.q}
            onChange={state.setQ}
            onEnter={state.apply}
            minChars={CASE_MIN_CHARS}
            busy={list.isFetching && searching}
          />
        }
        sort={state.stacked ? <ListSort options={options} sort={sort} onSort={state.setSort} defaultLabel={T.discovery.casesDefault} /> : null}
        order={<OrderLine options={options} sort={sort} defaultLabel={T.discovery.casesDefault} onReset={state.resetSort} />}
        count={<ListCount shown={list.data?.total} total={list.data?.total_all} noun={T.mapping.casesNoun} nounOne={T.mapping.caseNoun} searching={searching} />}
      >
        <SelectField
          label={T.discovery.only}
          hideLabel
          value={only}
          options={ONLY.map((value) => ({ value, label: T.discovery.onlyOptions[value] ?? value }))}
          onChange={(e) => {
            setOnly(e.target.value as (typeof ONLY)[number]);
            setOffset(0);
          }}
        />
      </ListToolbar>
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          searching ? (
            <NoMatches q={q} onClear={state.clear} />
          ) : (
            <EmptyState>{T.discovery.noCases}</EmptyState>
          )
        ) : (
          <>
            <DataTable
              caption={T.discovery.casesOf(term.term)}
              rows={list.data.items}
              rowKey={(item) => item.case.id}
              columns={columns}
              sort={sort}
              onSort={state.setSort}
              defaultSort={{ key: "last_found", dir: "desc" }}
              onStackedChange={state.setStacked}
            />
            <Pagination offset={offset} limit={LIMIT} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
      {claiming ? (
        <ClaimDialog
          open
          caseRef={claiming}
          onClose={() => setClaiming(null)}
          onDone={() => {
            void queryClient.invalidateQueries({ queryKey: DISCOVERY_KEY });
            void queryClient.invalidateQueries({ queryKey: INBOX_KEY });
          }}
        />
      ) : null}
    </section>
  );
}
