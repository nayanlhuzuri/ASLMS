"use client";

/**
 * Names in Cause Titles (design state-insights, decisions 9 and 35): the fourth list on Department Mapping, under
 * `admin.keywords` like Keywords and Name Patterns, with the same toolbar, search and sort (design list-search). A name is
 * a department as the court prints it in cause titles; mapped, Insights counts the case in that department's "named"
 * band. It never assigns a case and is not a recommendation signal (that is row 260). Each row has a menu: Change Office,
 * Deactivate or Reactivate. "Unmapped Names" lists the phrases read from cause titles that no department matches, most
 * cases first, with an example case; Map puts the phrase in the add form, where a person chooses the office and adds
 * it. Every save is audited by the API and starts an Insights refresh.
 */
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  Card,
  type Column,
  DataTable,
  EmptyState,
  ErrorBanner,
  ListCount,
  ListSort,
  Loading,
  NoMatches,
  numCell,
  OfficePicker,
  OrderLine,
  ScrollBox,
  sortByColumn,
  sortOptionsOf,
  TextField,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { MAPPING_KEY } from "@/lib/api/hooks";
import type { TitleName, TitleNameList, UnmappedTitleName, UnmappedTitleNamePage } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { matchesWords, searchShown } from "@/lib/listSearch";
import { given } from "@/lib/mapping";
import { GROUPS_ERRORS, T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";
import { useListState } from "@/lib/useListState";

import { conflictAware, OfficeCell, RuleMenu, RuleToolbar } from "./common";
import s from "./mapping.module.css";

const N = T.titleNames;
export const TITLE_NAMES_KEY = [...MAPPING_KEY, "title-names"] as const;
const UNMAPPED_TITLES_KEY = [...MAPPING_KEY, "title-names-unmapped"] as const;
const SORTS = ["phrase", "office", "cases", "status"] as const;

export function TitleNames() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const state = useListState({ mode: "local", search: "browser", sortKeys: SORTS });
  const [inactive, setInactive] = useState(false);
  const [prefill, setPrefill] = useState<{ phrase: string; n: number } | null>(null);
  const active = useQuery({
    queryKey: [...TITLE_NAMES_KEY, "active"],
    queryFn: () => api<TitleNameList>("/admin/title-names", { query: { active: true } }),
  });
  // the API reads one state at a time; Include Deactivated adds the deactivated ones
  const deactivated = useQuery({
    queryKey: [...TITLE_NAMES_KEY, "inactive"],
    queryFn: () => api<TitleNameList>("/admin/title-names", { query: { active: false } }),
    enabled: inactive,
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: TITLE_NAMES_KEY }),
      queryClient.invalidateQueries({ queryKey: UNMAPPED_TITLES_KEY }),
    ]);
  const all: TitleName[] = [...(active.data?.items ?? []), ...(inactive ? (deactivated.data?.items ?? []) : [])];
  const pending = active.isPending;
  const error = active.error ?? (inactive ? deactivated.error : null);
  const searching = state.applied !== "";

  const columns: Column<TitleName>[] = [
    { key: "phrase", header: N.cols.phrase, primary: true, sort: { type: "text", value: (r) => r.phrase }, cell: (r) => r.phrase },
    {
      key: "office",
      header: N.cols.office,
      sort: { type: "text", value: (r) => r.office_name },
      cell: (r) => <OfficeCell office={{ code: r.office_code, name: r.office_name }} />,
    },
    {
      key: "cases",
      header: N.cols.cases,
      align: "right",
      sort: { type: "number", value: (r) => r.cases, firstDir: "desc" },
      cell: (r) => <span className={numCell}>{formatNumber(r.cases)}</span>,
    },
    {
      key: "status",
      header: N.cols.status,
      width: "var(--lead-w)",
      sort: { type: "text", value: (r) => (r.is_active ? T.active : T.inactive) },
      cell: (r) => (r.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge>{T.inactive}</Badge>),
    },
    {
      key: "actions",
      header: <span className="visually-hidden">{N.cols.actions}</span>,
      label: N.cols.actions,
      width: "var(--s7)",
      align: "right",
      cell: (r) => (
        <RuleMenu<TitleName>
          path={`/admin/title-names/${r.id}`}
          active={r.is_active}
          label={r.phrase}
          confirmText={N.confirm}
          office={{ purpose: "keywords", current: r.office_code, body: (_choice, code) => ({ office_code: code }) }}
          onDone={() => {
            toast(N.savedNote);
            void refresh();
          }}
          onConflict={() => void refresh()}
        />
      ),
    },
  ];
  const options = sortOptionsOf(columns);
  const rows = sortByColumn(
    all.filter((r) => matchesWords(state.applied, r.phrase, r.office_name, r.office_code)),
    columns,
    state.sort,
  );

  return (
    <div className="stack">
      <section className="stack" aria-label={N.heading}>
        <h3>{N.heading}</h3>
        <p className="muted">{N.intro}</p>
        <RuleToolbar
          searchLabel={N.searchLabel}
          placeholder={N.searchPlaceholder}
          q={state.q}
          onQ={state.setQ}
          showSearch={searchShown(all.length, state.q)}
          inactive={inactive}
          onInactive={setInactive}
          sort={state.stacked ? <ListSort options={options} sort={state.sort} onSort={state.setSort} defaultLabel={N.cols.phrase} /> : null}
          order={<OrderLine options={options} sort={state.sort} defaultLabel={N.cols.phrase} onReset={state.resetSort} />}
          count={pending ? null : <ListCount shown={rows.length} total={all.length} noun={T.mapping.namesNoun} nounOne={T.mapping.nameNoun} searching={searching} />}
        />
        <AddName
          key={prefill ? `${prefill.n}` : "blank"}
          initial={prefill?.phrase ?? ""}
          onSaved={() => {
            toast(N.savedNote);
            setPrefill(null);
            void refresh();
          }}
          onConflict={() => void refresh()}
        />
        {pending ? <Loading /> : null}
        <ErrorBanner error={given(error)} onRetry={() => void refresh()} />
        {!pending && !error ? (
          rows.length === 0 ? (
            searching ? (
              <NoMatches q={state.applied} onClear={state.clear} />
            ) : (
              <EmptyState>{N.emptyNote}</EmptyState>
            )
          ) : (
            <ScrollBox label={N.caption}>
              <DataTable
                caption={N.caption}
                rows={rows}
                rowKey={(r) => r.id}
                sort={state.sort}
                onSort={state.setSort}
                onStackedChange={state.setStacked}
                columns={columns}
              />
            </ScrollBox>
          )
        ) : null}
      </section>
      <UnmappedNames onMap={(phrase) => setPrefill((p) => ({ phrase, n: (p?.n ?? 0) + 1 }))} />
    </div>
  );
}

/** The add row: Name as Printed (normalised by the server), the office from the Office Picker, Add Name. */
function AddName({ initial, onSaved, onConflict }: { initial: string; onSaved: () => void; onConflict: () => void }) {
  const [phrase, setPhrase] = useState(initial);
  const [office, setOffice] = useState<string | null>(null);
  const action = useAction();
  const form = useRef<HTMLFormElement | null>(null);
  async function add(e: FormEvent) {
    e.preventDefault();
    if (!office) return;
    const out = await action.run(() =>
      conflictAware(
        () => api<TitleName>("/admin/title-names", { method: "POST", body: { phrase: phrase.trim(), office_code: office } }),
        onConflict,
      ),
    );
    if (out.ok) {
      setPhrase("");
      setOffice(null);
      onSaved();
    }
  }
  return (
    <>
      {initial ? (
        <p className="muted" role="status">
          {N.prefilledNote(initial)}
        </p>
      ) : null}
      <form ref={form} className={s.addRow} onSubmit={add} aria-label={N.addLabel}>
        <TextField
          label={N.phraseLabel}
          title={N.phraseHint}
          required
          maxLength={300}
          value={phrase}
          onChange={(e) => setPhrase(e.target.value)}
        />
        <OfficePicker label={N.officeLabel} purpose="keywords" required value={office} onChange={setOffice} />
        <Button type="submit" variant="secondary" busy={action.busy} disabled={!office || !phrase.trim()}>
          {N.addButton}
        </Button>
      </form>
      {/* the phrase rule and a taken phrase in the portal's words (GROUPS_ERRORS), not the server's raw message */}
      <ErrorBanner error={action.error} messages={GROUPS_ERRORS} />
    </>
  );
}

const UNMAPPED_PAGE = 100;

/** Unmapped Names (decision 35): the phrases no department matches, most cases first, 100 a page, each with Map. */
function UnmappedNames({ onMap }: { onMap: (phrase: string) => void }) {
  const list = useInfiniteQuery({
    queryKey: UNMAPPED_TITLES_KEY,
    queryFn: ({ pageParam }) => api<UnmappedTitleNamePage>("/admin/title-names/unmapped", { query: { page: pageParam } }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (pages.length * UNMAPPED_PAGE < last.total ? pages.length + 1 : undefined),
    staleTime: 10 * 60_000,
  });
  const items: UnmappedTitleName[] = [];
  const seen = new Set<string>();
  for (const page of list.data?.pages ?? []) {
    for (const u of page.items) {
      if (seen.has(u.phrase)) continue;
      seen.add(u.phrase);
      items.push(u);
    }
  }
  const total = list.data?.pages[0]?.total ?? 0;
  const columns: Column<UnmappedTitleName>[] = [
    { key: "phrase", header: N.unmappedCols.phrase, primary: true, cell: (u) => u.phrase },
    { key: "cases", header: N.unmappedCols.cases, align: "right", cell: (u) => <span className={numCell}>{formatNumber(u.cases)}</span> },
    {
      key: "example",
      header: N.unmappedCols.example,
      cell: (u) =>
        u.example_case_no ? (
          <Link href={`/search?q=${encodeURIComponent(u.example_case_no)}`} className="cno">
            {u.example_case_no}
          </Link>
        ) : null,
    },
    {
      key: "map",
      header: <span className="visually-hidden">{N.unmappedCols.map}</span>,
      label: N.unmappedCols.map,
      actions: true,
      align: "right",
      cell: (u) => (
        <Button variant="secondary" size="sm" aria-label={N.mapAria(u.phrase)} onClick={() => onMap(u.phrase)}>
          {N.mapButton}
        </Button>
      ),
    },
  ];
  return (
    <aside aria-label={N.unmappedHeading}>
      <Card title={N.unmappedHeading}>
        <div className="stack">
          <p className="muted">{N.unmappedIntro}</p>
          {list.data ? <p className="muted">{N.unmappedCount(total)}</p> : null}
          {list.isPending ? <Loading /> : null}
          <ErrorBanner error={given(list.error)} onRetry={() => void list.refetch()} />
          {list.data ? (
            items.length === 0 ? (
              <EmptyState compact>{N.noUnmappedNote}</EmptyState>
            ) : (
              <>
                <ScrollBox label={N.unmappedCaption}>
                  <DataTable caption={N.unmappedCaption} rows={items} rowKey={(u) => u.phrase} columns={columns} />
                </ScrollBox>
                <div className={s.recMore}>
                  <span className="muted" aria-live="polite">
                    {N.shownNote(items.length, total)}
                  </span>
                  {list.hasNextPage ? (
                    <Button variant="secondary" busy={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
                      {N.moreButton}
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
