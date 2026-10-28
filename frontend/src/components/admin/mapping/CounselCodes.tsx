"use client";

/**
 * Counsel codes (design portal-mapping, decision 5; simplified by portal-ui-polish-2, decisions 39-42; plan §4.1:
 * "each code is mapped to its department in the administration module"). One toolbar line (Search Codes with the
 * list's `q`, Include Deactivated, the order line and "12 of 340 codes"), one add row (Code, Office from the Office
 * Picker, Add Code), the list in its own scroll box with headers that sort in the browser (Code, Office, Status,
 * Updated; design list-search, decision 13) and a menu per row (Change Office, Deactivate or Reactivate), and
 * "Recommended From Cause Lists" below it: every code seen in cause lists with no mapping, paged inside its box, with
 * its own search and sort (design list-search, decisions 9-12 and 39), each with its own picker and Map. Nothing is
 * mapped automatically: Map is a person's decision. A code mapped to the root office is generic (recognised,
 * recommends no department); the forms send `is_generic_state` exactly when the root office is chosen. Notes and
 * weights are never sent (decision 39). A code that partly matches mappings in the caller's scope says so ("Partly
 * matches SC, EDU (EDU)"), and with exactly one such mapping its picker starts on that office; Map still sends nothing
 * until pressed (design partial-code-match, decision 16). A save starts the rescore at once (design list-search,
 * decision 41).
 */
import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorBanner,
  ListCount,
  ListSearch,
  ListSort,
  ListToolbar,
  Loading,
  NoMatches,
  Notice,
  OfficePicker,
  OrderLine,
  ScrollBox,
  sortByColumn,
  sortOptionsOf,
  TextField,
  type Column,
  type SortOption,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { MAPPING_KEY, useOfficeChoices } from "@/lib/api/hooks";
import type { CounselCode, CounselCodeList, OfficeChoice, UnmappedCode, UnmappedCodePage } from "@/lib/api/types";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { searchShown } from "@/lib/listSearch";
import { given } from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";
import { useListState } from "@/lib/useListState";

import { conflictAware, isRootChoice, OfficeCell, RuleMenu, RuleToolbar, SearchLink } from "./common";
import s from "./mapping.module.css";

const CODES_KEY = [...MAPPING_KEY, "codes"] as const;
export const UNMAPPED_KEY = [...MAPPING_KEY, "unmapped"] as const;
export const UNMAPPED_PAGE = 100;
const CODE_SORTS = ["code", "office", "status", "updated"] as const;
const UNMAPPED_SORTS = ["entries", "code", "last_seen"] as const;

/** The mapped code leaves every loaded page of the panel; `total` and `matched` drop by one when it was there. */
export function dropMapped(old: InfiniteData<UnmappedCodePage> | undefined, code: string): InfiniteData<UnmappedCodePage> | undefined {
  if (!old) return old;
  const present = old.pages.some((p) => p.items.some((u) => u.code === code));
  if (!present) return old;
  return {
    ...old,
    pages: old.pages.map((p) => ({
      ...p,
      items: p.items.filter((u) => u.code !== code),
      total: Math.max(0, p.total - 1),
      matched: Math.max(0, p.matched - 1),
    })),
  };
}

export function CounselCodes() {
  const queryClient = useQueryClient();
  const [inactive, setInactive] = useState(false);
  const state = useListState({ mode: "local", search: "server", sortKeys: CODE_SORTS });
  const query = state.applied;
  const list = useQuery({
    queryKey: [...CODES_KEY, { q: query, inactive }],
    queryFn: () =>
      api<CounselCodeList>("/admin/counsel-codes", {
        query: { q: query || undefined, include_inactive: inactive || undefined },
      }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: CODES_KEY });
  const [notice, setNotice] = useState<string | null>(null);
  // a generic code (on the root office) is managed only by a login whose scope holds the root office
  const choices = useOfficeChoices("counsel_codes");
  const editableGeneric = (choices.data?.items ?? []).some((o) => isRootChoice(o));

  function saved(row: CounselCode) {
    setNotice(T.mapping.rescoreStarted);
    // the mapped code leaves the recommended panel without scanning the cause lists again
    queryClient.setQueriesData<InfiniteData<UnmappedCodePage>>({ queryKey: UNMAPPED_KEY }, (old) => dropMapped(old, row.code));
    void refresh();
  }

  const columns: Column<CounselCode>[] = [
    {
      key: "code",
      header: T.mapping.code,
      primary: true,
      sort: { type: "text", value: (row) => row.code },
      cell: (row) => <span className="mono">{row.code}</span>,
    },
    {
      key: "office",
      header: T.mapping.office,
      sort: { type: "text", value: (row) => row.office.name },
      cell: (row) => <OfficeCell office={row.office} />,
    },
    { key: "generic", header: T.mapping.generic, cell: (row) => (row.is_generic_state ? T.yes : "—") },
    {
      key: "status",
      header: T.mapping.status,
      width: "var(--lead-w)",
      sort: { type: "text", value: (row) => (row.is_active ? T.active : T.inactive) },
      cell: (row) => (row.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge>{T.inactive}</Badge>),
    },
    {
      key: "updated",
      header: T.mapping.updated,
      sort: { type: "date", value: (row) => row.updated_at },
      cell: (row) => formatDateTime(row.updated_at),
    },
    {
      key: "actions",
      header: <span className="visually-hidden">{T.mapping.actions}</span>,
      label: T.mapping.actions,
      width: "var(--s7)",
      align: "right",
      cell: (row) =>
        row.is_generic_state && !editableGeneric ? null : (
          <RuleMenu<CounselCode>
            path={`/admin/counsel-codes/${row.id}`}
            active={row.is_active}
            label={row.code}
            confirmText={T.mapping.ruleConfirm}
            onDone={(r) => saved(r)}
            onConflict={() => void refresh()}
            office={{
              purpose: "counsel_codes",
              current: row.office.code,
              // a generic code stays generic (the root office); any other code moves among departments
              kinds: row.is_generic_state ? ["state"] : undefined,
              body: (_choice, code) => ({ office_code: code }),
            }}
          />
        ),
    },
  ];
  const options = sortOptionsOf(columns);
  const items = list.data?.items ?? [];
  const rows = sortByColumn(items, columns, state.sort);
  const unfiltered = list.data ? (list.data.total_all ?? list.data.total) : undefined;
  const searching = !!query;

  return (
    <section className="stack" aria-label={T.mapping.codes}>
      <h3>{T.mapping.codes}</h3>
      <div className={s.codesLayout}>
        <div className={s.codesMain}>
          <RuleToolbar
            searchLabel={T.mapping.searchCodesLabel}
            placeholder={T.mapping.searchCodesPlaceholder}
            q={state.q}
            onQ={state.setQ}
            onEnter={state.apply}
            minChars={2}
            busy={list.isFetching && searching}
            showSearch={searchShown(unfiltered, state.q)}
            inactive={inactive}
            onInactive={setInactive}
            sort={
              state.stacked ? <ListSort options={options} sort={state.sort} onSort={state.setSort} defaultLabel={T.mapping.codesDefault} /> : null
            }
            order={<OrderLine options={options} sort={state.sort} defaultLabel={T.mapping.codesDefault} onReset={state.resetSort} />}
            count={<ListCount shown={list.data?.total} total={list.data?.total_all} noun={T.mapping.codesNoun} nounOne={T.mapping.codeNoun} searching={searching} />}
          />
          <AddCode onSaved={saved} onConflict={() => void refresh()} />
          {notice ? <Notice>{notice}</Notice> : null}
          {list.isPending ? <Loading /> : null}
          <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
          {list.data ? (
            items.length === 0 ? (
              searching ? (
                <NoMatches q={query} onClear={state.clear} />
              ) : (
                <EmptyState>{T.mapping.empty}</EmptyState>
              )
            ) : (
              <ScrollBox label={T.mapping.codes}>
                <DataTable
                  caption={T.mapping.codes}
                  rows={rows}
                  rowKey={(row) => row.id}
                  columns={columns}
                  sort={state.sort}
                  onSort={state.setSort}
                  defaultSort={{ key: "code", dir: "asc" }}
                  onStackedChange={state.setStacked}
                />
              </ScrollBox>
            )
          ) : null}
        </div>
        <RecommendedCodes
          onMapped={saved}
          onConflict={() => {
            void refresh();
            void queryClient.invalidateQueries({ queryKey: UNMAPPED_KEY });
          }}
        />
      </div>
    </section>
  );
}

/** The add row (decision 41): Code, Office (picker), Add Code; secondary, so the page keeps no primary of its own. */
function AddCode({ onSaved, onConflict }: { onSaved: (row: CounselCode) => void; onConflict: () => void }) {
  const [code, setCode] = useState("");
  const [office, setOffice] = useState<string | null>(null);
  const [chosen, setChosen] = useState<OfficeChoice | undefined>(undefined);
  const action = useAction();
  const generic = isRootChoice(chosen);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!office) return;
    const out = await action.run(() =>
      conflictAware(
        () =>
          api<CounselCode>("/admin/counsel-codes", {
            method: "POST",
            body: { code: code.trim(), office_code: office, is_generic_state: generic },
          }),
        onConflict,
      ),
    );
    if (out.ok) {
      setCode("");
      setOffice(null);
      setChosen(undefined);
      onSaved(out.value);
    }
  }

  return (
    <>
      <form className={s.addRow} onSubmit={add} aria-label={T.mapping.addCode}>
        <div className={s.narrow}>
          <TextField label={T.mapping.code} required maxLength={60} title={T.mapping.codeHint} value={code} onChange={(e) => setCode(e.target.value)} />
        </div>
        <OfficePicker
          label={T.mapping.office}
          purpose="counsel_codes"
          required
          value={office}
          onChange={setOffice}
          onChoose={setChosen}
          hint={generic ? T.mapping.genericLine : undefined}
        />
        <Button type="submit" variant="secondary" busy={action.busy} disabled={!office || !code.trim()}>
          {T.mapping.addCode}
        </Button>
      </form>
      <ErrorBanner error={given(action.error)} />
    </>
  );
}

const RECOMMENDED_OPTIONS: SortOption[] = [
  {
    key: "entries",
    label: T.mapping.entries,
    type: "number",
    firstDir: "desc",
    labels: [T.list.dirLabels.fewestFirst, T.list.dirLabels.mostFirst],
  },
  { key: "code", label: T.mapping.code, type: "text" },
  { key: "last_seen", label: T.mapping.lastSeen, type: "date", firstDir: "desc" },
];

/**
 * "Recommended From Cause Lists" (decision 42; every code by design list-search, decisions 9-12 and 39): every code
 * seen in cause lists or case details with no mapping (`GET /admin/counsel-codes/unmapped/page`), 100 at a time inside
 * its own scroll box: the next page loads when the end of the list comes within 200 px of the box's bottom, or by
 * "Show 100 More". The toolbar searches the code (server `q`, 300 ms) and sorts by Entries, Code or Last Seen; the
 * count reads "1,066 codes not mapped", or "12 of 1,066 codes" while searching. Each code keeps its entries, when it
 * was last seen, an example case, and its own picker with Map, which posts the mapping directly; the code then leaves
 * every loaded page.
 */
export function RecommendedCodes({ onMapped, onConflict }: { onMapped: (row: CounselCode) => void; onConflict: () => void }) {
  const state = useListState({ mode: "local", search: "server", sortKeys: UNMAPPED_SORTS });
  const query = state.applied;
  const list = useInfiniteQuery({
    queryKey: [...UNMAPPED_KEY, { q: query, sort: state.sort?.key ?? null, dir: state.sort?.dir ?? null }],
    queryFn: ({ pageParam }) =>
      api<UnmappedCodePage>("/admin/counsel-codes/unmapped/page", {
        query: {
          q: query || undefined,
          sort: state.sort?.key,
          dir: state.sort?.dir,
          limit: UNMAPPED_PAGE,
          cursor: pageParam,
        },
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 10 * 60_000,
    retry: false,
  });
  // pages are joined by code, so a code is never listed twice if entries change between pages
  const items: UnmappedCode[] = [];
  const seen = new Set<string>();
  for (const page of list.data?.pages ?? []) {
    for (const u of page.items) {
      if (seen.has(u.code)) continue;
      seen.add(u.code);
      items.push(u);
    }
  }
  const first = list.data?.pages[0];
  const searching = !!query;
  const of = first ? (searching ? first.matched : first.total) : 0;
  const box = useRef<HTMLDivElement | null>(null);
  const end = useRef<HTMLDivElement | null>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list;

  useEffect(() => {
    const root = box.current;
    const target = end.current;
    if (!root || !target || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && hasNextPage && !isFetchingNextPage) void fetchNextPage();
      },
      { root, rootMargin: "0px 0px 200px 0px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, items.length]);

  return (
    <aside className={s.recommended} aria-label={T.mapping.recommendedTitle}>
      <Card title={T.mapping.recommendedTitle}>
        <div className="stack">
          <Notice>{T.mapping.recommendedNotice}</Notice>
          <ListToolbar
            search={
              searchShown(first?.total, state.q) ? (
                <ListSearch
                  label={T.mapping.searchRecommendedLabel}
                  placeholder={T.mapping.searchRecommendedPlaceholder}
                  value={state.q}
                  onChange={state.setQ}
                  onEnter={state.apply}
                  minChars={2}
                  busy={list.isFetching && !isFetchingNextPage && searching}
                />
              ) : null
            }
            sort={<ListSort options={RECOMMENDED_OPTIONS} sort={state.sort} onSort={state.setSort} defaultLabel={T.mapping.recommendedDefault} />}
            order={<OrderLine options={RECOMMENDED_OPTIONS} sort={state.sort} defaultLabel={T.mapping.recommendedDefault} onReset={state.resetSort} />}
            count={
              first ? (
                <ListCount shown={searching ? first.matched : first.total} total={first.total} noun={T.mapping.codesNoun} nounOne={T.mapping.codeNoun} allNoun={T.mapping.codesNotMapped} allNounOne={T.mapping.codeNotMapped} searching={searching} />
              ) : null
            }
          />
          {list.isPending ? <Loading /> : null}
          <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
          {first ? (
            items.length === 0 ? (
              searching ? (
                <NoMatches q={query} onClear={state.clear} />
              ) : (
                <EmptyState>{T.mapping.noUnmapped}</EmptyState>
              )
            ) : (
              <>
                <ScrollBox label={T.mapping.recommendedTitle} ref={box}>
                  <ul className={s.recList}>
                    {items.map((u) => (
                      <RecommendedCode key={u.code} item={u} onMapped={onMapped} onConflict={onConflict} />
                    ))}
                  </ul>
                  <div ref={end} className={s.recEnd} aria-hidden="true" />
                </ScrollBox>
                <div className={s.recMore}>
                  <span className="muted" aria-live="polite">
                    {hasNextPage ? T.list.showing(formatNumber(items.length), formatNumber(of)) : T.list.showingAll(formatNumber(of))}
                  </span>
                  {hasNextPage ? (
                    <Button variant="secondary" busy={isFetchingNextPage} onClick={() => void fetchNextPage()}>
                      {T.list.showMoreButton(UNMAPPED_PAGE)}
                    </Button>
                  ) : null}
                </div>
              </>
            )
          ) : null}
        </div>
      </Card>
    </aside>
  );
}

function RecommendedCode({ item, onMapped, onConflict }: { item: UnmappedCode; onMapped: (row: CounselCode) => void; onConflict: () => void }) {
  const partial = item.partial_matches ?? [];
  const [office, setOffice] = useState<string | null>(partial.length === 1 ? partial[0]!.office_code : null);
  const [chosen, setChosen] = useState<OfficeChoice | undefined>(undefined);
  const action = useAction();

  async function map(e: FormEvent) {
    e.preventDefault();
    if (!office) return;
    const out = await action.run(() =>
      conflictAware(
        () =>
          api<CounselCode>("/admin/counsel-codes", {
            method: "POST",
            body: { code: item.code, office_code: office, is_generic_state: isRootChoice(chosen) },
          }),
        onConflict,
      ),
    );
    if (out.ok) onMapped(out.value);
  }

  return (
    <li>
      <div className={s.recTop}>
        <span className="mono">{item.code}</span>
        <span className="muted">{T.mapping.entriesLine(formatNumber(item.entries), formatDate(item.last_listed))}</span>
      </div>
      {partial.length > 0 ? <span className="muted">{T.mapping.partlyMatches(partial)}</span> : null}
      {item.example_case_ref ? <SearchLink ref_no={item.example_case_ref} /> : null}
      <form className={s.recMap} onSubmit={map} aria-label={T.mapping.mapCode(item.code)}>
        <OfficePicker label={T.mapping.officeFor(item.code)} hideLabel purpose="counsel_codes" value={office} onChange={setOffice} onChoose={setChosen} />
        <Button type="submit" variant="secondary" busy={action.busy} disabled={!office} aria-label={T.mapping.mapCode(item.code)}>
          {T.mapping.map}
        </Button>
      </form>
      <ErrorBanner error={given(action.error)} />
    </li>
  );
}
