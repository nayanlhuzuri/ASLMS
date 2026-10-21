"use client";

/**
 * Court search (design department-discovery, decision 13b; owner's decisions of 14 Oct 2026), a Department mapping tab
 * under `admin.keywords`: the department's names searched at the High Court (its keywords and name patterns ticked
 * "Search the court") with the years searched, the last search and the cases found, and per name the found cases with
 * their owner, our recommendation and Claim (the shared `ClaimDialog`). A user may ask for older years of a name: they
 * pick the name and the years and press Search; the searches are queued for the worker and found cases appear here as
 * they arrive. No call counts or allowance are shown, and no "searched before" question: the user may search a name
 * and year as often as they like (owner, 14 Oct 2026). Summaries only; the API decides every list and action.
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
  Loading,
  Notice,
  Pagination,
  ScoreBadge,
  SelectField,
  DataTable,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, MAPPING_KEY } from "@/lib/api/hooks";
import type { DiscoveryCaseList, DiscoverySearch, DiscoveryTerm, DiscoveryTermList } from "@/lib/api/types";
import { isDiscoverable, normaliseTerm, parseYears } from "@/lib/discovery";
import { formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

export const DISCOVERY_KEY = [...MAPPING_KEY, "discovery"] as const;
const LIMIT = 50;
const ONLY = ["all", "pool", "recommended", "owned"] as const;

export function CourtSearch() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<DiscoveryTerm | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const terms = useQuery({
    queryKey: [...DISCOVERY_KEY, "terms"],
    queryFn: () => api<DiscoveryTermList>("/admin/discovery/terms", { query: { status: "all", limit: 200 } }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: DISCOVERY_KEY });
  return (
    <section className="stack" aria-label={T.discovery.tab}>
      <p className="muted">{T.discovery.intro}</p>
      <AskYears
        terms={terms.data?.items ?? []}
        onQueued={(out) => {
          setNotice(T.discovery.searching);
          const term = terms.data?.items.find((t) => t.id === out.term_id) ?? null;
          if (term) setSelected(term);
          void refresh();
        }}
      />
      {notice ? <Notice>{notice}</Notice> : null}
      <h3>{T.discovery.terms}</h3>
      {terms.isPending ? <Loading /> : null}
      <ErrorBanner error={terms.error} onRetry={() => terms.refetch()} />
      {terms.data ? (
        terms.data.items.length === 0 ? (
          <EmptyState>{T.discovery.noTerms}</EmptyState>
        ) : (
          <DataTable
            caption={T.discovery.terms}
            rows={terms.data.items}
            rowKey={(t) => t.id}
            columns={[
              {
                key: "term",
                header: T.discovery.term,
                primary: true,
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
                cell: (t) => (t.last_searched_at ? formatDateTime(t.last_searched_at) : T.discovery.notYetSearched),
              },
              { key: "found", header: T.discovery.casesFound, align: "right", cell: (t) => formatNumber(t.cases_found) },
              { key: "new", header: T.discovery.newThisWeek, align: "right", cell: (t) => formatNumber(t.found_last_7_days) },
              {
                key: "actions",
                header: T.mapping.actions,
                cell: (t) => (
                  <Button
                    variant="link"
                    aria-label={T.discovery.showCasesFor(t.term)}
                    aria-pressed={selected?.id === t.id}
                    onClick={() => setSelected(t)}
                  >
                    {T.discovery.showCases}
                  </Button>
                ),
              },
            ]}
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
  const list = useQuery({
    queryKey: [...DISCOVERY_KEY, "cases", term.id, only, offset],
    queryFn: () =>
      api<DiscoveryCaseList>(`/admin/discovery/terms/${term.id}/cases`, { query: { only, limit: LIMIT, offset } }),
  });
  return (
    <section className="stack" aria-label={T.discovery.casesOf(term.term)}>
      <h3>{T.discovery.casesOf(term.term)}</h3>
      <SelectField
        label={T.discovery.only}
        value={only}
        options={ONLY.map((value) => ({ value, label: T.discovery.onlyOptions[value] ?? value }))}
        onChange={(e) => {
          setOnly(e.target.value as (typeof ONLY)[number]);
          setOffset(0);
        }}
      />
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.discovery.noCases}</EmptyState>
        ) : (
          <>
            <DataTable
              caption={T.discovery.casesOf(term.term)}
              rows={list.data.items}
              rowKey={(item) => item.case.id}
              columns={[
                {
                  key: "case",
                  header: T.inbox.case,
                  primary: true,
                  cell: (item) => (
                    <>
                      <PartiesLine c={item.case} />
                      <CaseLink value={item.case} />
                    </>
                  ),
                },
                { key: "year", header: T.discovery.foundYear, align: "right", cell: (item) => item.reg_year },
                { key: "found", header: T.discovery.found, cell: (item) => formatDateTime(item.last_found_at) },
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
              ]}
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
