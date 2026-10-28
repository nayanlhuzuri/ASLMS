"use client";

/**
 * Keywords and name patterns (design portal-mapping, decision 6; simplified by portal-ui-polish-2, decisions 39-41;
 * plan §4.1: "department names and designations appearing in the party names"), both under `admin.keywords`, in one
 * list. One toolbar line (Search Words, the All / Keywords / Name Patterns choice, Include Deactivated), one add row
 * (Word or Pattern, Kind: Keyword, Exact, Starts With or Pattern, routed to `/admin/keywords` or `/admin/name-patterns`
 * as before, Office from the Office Picker, Search the Court, Add), and a menu per row (Deactivate or Reactivate). A
 * wording change is a deactivation and a new rule; adding a rule that exists deactivated reactivates it (the API's
 * behaviour), and the screen says so when it knew the row. No weight is shown or sent: the Scoring tab is the only
 * place for weights. "Search the Court" (design department-discovery, decision 13a): the add row follows the text
 * until changed and is off for a regular expression; each row has its toggle (`PATCH {discover}`). The list is held
 * whole and searched and sorted in the browser (design list-search, decision 14): every word in the text or the
 * office, headers Word or Pattern, Kind, Office and Status, the office order by default.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  CheckField,
  DataTable,
  EmptyState,
  ErrorBanner,
  ListCount,
  ListSort,
  Loading,
  NoMatches,
  Notice,
  OfficePicker,
  OrderLine,
  ScrollBox,
  SegmentedSwitch,
  SelectField,
  sortByColumn,
  sortOptionsOf,
  TextField,
  type Column,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { MAPPING_KEY } from "@/lib/api/hooks";
import type { Keyword, KeywordList, NamePattern, NamePatternList } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { isDiscoverable } from "@/lib/discovery";
import { matchesWords, searchShown } from "@/lib/listSearch";
import { given } from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";
import { useListState } from "@/lib/useListState";

import { conflictAware, OfficeCell, RuleMenu, RuleToolbar, SwitchLine } from "./common";
import s from "./mapping.module.css";

const KEYWORDS_KEY = [...MAPPING_KEY, "keywords"] as const;
const PATTERNS_KEY = [...MAPPING_KEY, "name-patterns"] as const;
const ADD_KINDS = ["keyword", "exact", "prefix", "regex"] as const;
const SHOW = ["all", "keywords", "patterns"] as const;
const WORD_SORTS = ["text", "kind", "office", "status"] as const;

type Row =
  | { type: "keyword"; key: string; text: string; row: Keyword }
  | { type: "pattern"; key: string; text: string; row: NamePattern };

/** A row's toggle of Search the Court and its last search (`PATCH {discover}`). */
function DiscoverCell({ path, row, label, onDone }: { path: string; row: Keyword | NamePattern; label: string; onDone: () => void }) {
  const action = useAction();
  const regex = "kind" in row && row.kind === "regex";
  async function toggle(next: boolean) {
    const out = await action.run(() => api(path, { method: "PATCH", body: { discover: next } }));
    if (out.ok) onDone();
  }
  const last = row.discovery?.last_searched_at ? formatDateTime(row.discovery.last_searched_at) : null;
  return (
    <div className="stack">
      <CheckField
        label={T.discovery.searchCourt}
        aria-label={T.discovery.searchCourtFor(label)}
        checked={row.discover}
        disabled={regex || action.busy}
        onChange={(e) => void toggle(e.target.checked)}
      />
      {row.discover ? <span className="muted">{T.discovery.ruleLine(last, row.discovery?.cases_found ?? 0)}</span> : null}
      <ErrorBanner error={given(action.error)} />
    </div>
  );
}

export function KeywordsAndPatterns() {
  const queryClient = useQueryClient();
  const state = useListState({ mode: "local", search: "browser", sortKeys: WORD_SORTS });
  const [inactive, setInactive] = useState(false);
  const [show, setShow] = useState<(typeof SHOW)[number]>("all");
  const keywords = useQuery({
    queryKey: [...KEYWORDS_KEY, { inactive }],
    queryFn: () => api<KeywordList>("/admin/keywords", { query: { include_inactive: inactive || undefined } }),
  });
  const patterns = useQuery({
    queryKey: [...PATTERNS_KEY, { inactive }],
    queryFn: () => api<NamePatternList>("/admin/name-patterns", { query: { include_inactive: inactive || undefined } }),
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: KEYWORDS_KEY }),
      queryClient.invalidateQueries({ queryKey: PATTERNS_KEY }),
    ]);
  const [notice, setNotice] = useState<string | null>(null);

  const all: Row[] = [
    ...(show !== "patterns"
      ? (keywords.data?.items ?? []).map((r): Row => ({ type: "keyword", key: `kw-${r.id}`, text: r.keyword, row: r }))
      : []),
    ...(show !== "keywords"
      ? (patterns.data?.items ?? []).map((r): Row => ({ type: "pattern", key: `np-${r.id}`, text: r.pattern, row: r }))
      : []),
  ];
  const kindText = (r: Row) => (r.type === "keyword" ? T.mapping.kindShort.keyword : (T.mapping.kindShort[r.row.kind] ?? r.row.kind));
  const searching = state.applied !== "";
  const pending = keywords.isPending || patterns.isPending;
  const known = new Set([...(keywords.data?.items ?? []), ...(patterns.data?.items ?? [])].map((r) => r.id));
  const columns: Column<Row>[] = [
    {
      key: "text",
      header: T.mapping.wordLabel,
      primary: true,
      sort: { type: "text", value: (r) => r.text },
      cell: (r) => (r.type === "pattern" ? <span className="mono">{r.text}</span> : r.text),
    },
    { key: "kind", header: T.mapping.kind, sort: { type: "text", value: kindText }, cell: kindText },
    {
      key: "office",
      header: T.mapping.office,
      sort: { type: "text", value: (r) => r.row.office.name },
      cell: (r) => <OfficeCell office={r.row.office} />,
    },
    {
      key: "discover",
      header: T.discovery.searchCourt,
      cell: (r) => (
        <DiscoverCell
          path={r.type === "keyword" ? `/admin/keywords/${r.row.id}` : `/admin/name-patterns/${r.row.id}`}
          row={r.row}
          label={r.text}
          onDone={() => void refresh()}
        />
      ),
    },
    {
      key: "status",
      header: T.mapping.status,
      width: "var(--lead-w)",
      sort: { type: "text", value: (r) => (r.row.is_active ? T.active : T.inactive) },
      cell: (r) => (r.row.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge>{T.inactive}</Badge>),
    },
    {
      key: "actions",
      header: <span className="visually-hidden">{T.mapping.actions}</span>,
      label: T.mapping.actions,
      width: "var(--s7)",
      align: "right",
      cell: (r) => (
        <RuleMenu<Keyword | NamePattern>
          path={r.type === "keyword" ? `/admin/keywords/${r.row.id}` : `/admin/name-patterns/${r.row.id}`}
          active={r.row.is_active}
          label={r.text}
          confirmText={T.mapping.ruleConfirm}
          onDone={() => {
            setNotice(T.mapping.rescoreStarted);
            void refresh();
          }}
          onConflict={() => void refresh()}
        />
      ),
    },
  ];
  const options = sortOptionsOf(columns);
  const rows = sortByColumn(
    all.filter((r) => matchesWords(state.applied, r.text, kindText(r), r.row.office.name, r.row.office.code)),
    columns,
    state.sort,
  );

  return (
    <section className="stack" aria-label={T.mapping.keywordsAndPatterns}>
      <h3>{T.mapping.keywordsAndPatterns}</h3>
      <RuleToolbar
        searchLabel={T.mapping.searchWordsLabel}
        placeholder={T.mapping.searchWordsPlaceholder}
        q={state.q}
        onQ={state.setQ}
        showSearch={searchShown(all.length, state.q)}
        inactive={inactive}
        onInactive={setInactive}
        sort={state.stacked ? <ListSort options={options} sort={state.sort} onSort={state.setSort} defaultLabel={T.mapping.officeOrder} /> : null}
        order={<OrderLine options={options} sort={state.sort} defaultLabel={T.mapping.officeOrder} onReset={state.resetSort} />}
        count={pending ? null : <ListCount shown={rows.length} total={all.length} noun={T.mapping.rulesNoun} nounOne={T.mapping.ruleNoun} searching={searching} />}
      >
        <SegmentedSwitch
          label={T.mapping.showLabel}
          options={SHOW.map((k) => ({ value: k, label: T.mapping.showChoices[k]! }))}
          value={show}
          onChange={(v) => setShow(v as (typeof SHOW)[number])}
        />
      </RuleToolbar>
      <AddWord
        known={known}
        onSaved={(line) => {
          setNotice(line);
          void refresh();
        }}
        onConflict={() => void refresh()}
      />
      {notice ? <Notice>{notice}</Notice> : null}
      {pending ? <Loading /> : null}
      <ErrorBanner error={given(keywords.error ?? patterns.error)} onRetry={() => void refresh()} />
      {!pending && !keywords.error && !patterns.error ? (
        rows.length === 0 ? (
          searching ? (
            <NoMatches q={state.applied} onClear={state.clear} />
          ) : (
            <EmptyState>{T.mapping.empty}</EmptyState>
          )
        ) : (
          <ScrollBox label={T.mapping.wordsCaption}>
            <DataTable
              caption={T.mapping.wordsCaption}
              rows={rows}
              rowKey={(r) => r.key}
              sort={state.sort}
              onSort={state.setSort}
              onStackedChange={state.setStacked}
              columns={columns}
            />
          </ScrollBox>
        )
      ) : null}
    </section>
  );
}

/**
 * The add row (decision 41): Word or Pattern, Kind, Office, Search the Court and Add. A keyword posts to
 * `/admin/keywords`; Exact, Starts With and Pattern post to `/admin/name-patterns` with their kind. `discover` is sent
 * only when the switch was changed (the API defaults it from the text) and never for a regular expression.
 */
function AddWord({ known, onSaved, onConflict }: { known: Set<string>; onSaved: (line: string) => void; onConflict: () => void }) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState<(typeof ADD_KINDS)[number]>("keyword");
  const [office, setOffice] = useState<string | null>(null);
  const [discover, setDiscover] = useState<boolean | null>(null);
  const action = useAction();
  const regex = kind === "regex";
  const patternKind = kind === "keyword" ? undefined : kind;
  const discoverOn = regex ? false : (discover ?? isDiscoverable(text, patternKind));

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!office) return;
    const discoverPart = discover === null || regex ? {} : { discover };
    const out = await action.run(() =>
      conflictAware<Keyword | NamePattern>(
        () =>
          kind === "keyword"
            ? api<Keyword>("/admin/keywords", { method: "POST", body: { keyword: text.trim(), office_code: office, ...discoverPart } })
            : api<NamePattern>("/admin/name-patterns", {
                method: "POST",
                body: { pattern: text.trim(), kind, office_code: office, ...discoverPart },
              }),
        onConflict,
      ),
    );
    if (out.ok) {
      const line = T.mapping.rescoreStarted;
      onSaved(known.has(out.value.id) ? `${T.mapping.reactivated} ${line}` : line);
      setText("");
      setOffice(null);
      setDiscover(null);
    }
  }

  return (
    <>
      <form className={s.addRow} onSubmit={add} aria-label={T.mapping.add}>
        <TextField
          label={T.mapping.wordLabel}
          required
          maxLength={300}
          title={kind === "keyword" ? T.mapping.keywordHint : undefined}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className={s.narrow}>
          <SelectField
            label={T.mapping.kind}
            options={ADD_KINDS.map((k) => ({ value: k, label: T.mapping.addKinds[k]! }))}
            value={kind}
            onChange={(e) => setKind(e.target.value as (typeof ADD_KINDS)[number])}
          />
        </div>
        <OfficePicker label={T.mapping.office} purpose="keywords" required value={office} onChange={setOffice} />
        <SwitchLine
          label={T.discovery.searchCourt}
          title={T.discovery.searchCourtHint}
          checked={discoverOn}
          disabled={regex}
          onChange={setDiscover}
        />
        <Button type="submit" variant="secondary" busy={action.busy} disabled={!office || !text.trim()}>
          {T.mapping.add}
        </Button>
      </form>
      <ErrorBanner error={given(action.error)} />
    </>
  );
}
