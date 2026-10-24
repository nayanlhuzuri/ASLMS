"use client";

/**
 * The Cause list screen (design portal-causelist, decisions 1-11; plan §3.1 Table 4, §4.2, §5.4): pick any date and a
 * bench, see the day's list as published in court order, each entry with its recommendation or owner and Claim. The
 * URL keeps the place (`date`, `bench_id` or `list_id`, `list_type`, `court_no`, `q`, `only`, `offset`), so a
 * bookmarked or shared list reopens as it was; without a date the screen opens on the API's `default_date`. Every
 * row and every fact on it comes from the server, which applies the visibility and claim rules. On the Work list
 * template (design portal-ui-redesign, decision 26): the day bar and the bench choice on top, the show-only choices as
 * chips, the entries with court and item in the fixed leading column, cards on phones and details in a side panel.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { useFilters } from "@/components/inbox/common";
import { ClaimDialog } from "@/components/inbox/dialogs";
import {
  Badge,
  Button,
  Chip,
  ChipGroup,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  PageHeader,
  Pagination,
  SelectField,
  TextField,
} from "@/components/ui";
import {
  CAUSELISTS_KEY,
  useCauselistDates,
  useCauselistDay,
  useCauselistEntries,
  useDepartments,
  useMe,
} from "@/lib/api/hooks";
import type { CauselistBench, CauselistCounts } from "@/lib/api/types";
import { can } from "@/lib/can";
import {
  benchParams,
  benchValueOf,
  chosenBench,
  ENTRY_PAGE,
  LIST_TYPES,
  ONLY_VALUES,
  toApiQuery,
  validDate,
} from "@/lib/causelist";
import { formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";

import { BenchSelect } from "./BenchSelect";
import { DayBar } from "./DayBar";
import { EntryTable } from "./EntryTable";
import { ListStrip, listFileUrl } from "./ListStrip";
import s from "./causelist.module.css";

const COUNTED: Record<string, keyof CauselistCounts | null> = {
  recommended: "recommended",
  mine: "mine",
  claimable: "claimable",
  unclaimed: "unclaimed",
  claimed: "claimed",
  visible: null,
};

function courtsOf(benches: CauselistBench[]): string[] {
  const out: string[] = [];
  for (const b of benches) for (const c of b.court_nos) if (!out.includes(c)) out.push(c);
  return out;
}

function listTypesOf(benches: CauselistBench[]): string[] {
  const have = new Set(benches.flatMap((b) => b.lists.map((l) => l.list_type)));
  return LIST_TYPES.filter((t) => have.has(t));
}

export function CauseList({ params }: { params: Params }) {
  const me = useMe();
  const queryClient = useQueryClient();
  const setFilters = useFilters(params);
  const urlDate = validDate(params.date);
  const dates = useCauselistDates(undefined, undefined, !urlDate);
  const date = urlDate ?? dates.data?.default_date;
  const day = useCauselistDay(date);
  const query = toApiQuery(params);
  const entries = useCauselistEntries(date, query);
  const departments = useDepartments();
  const [claiming, setClaiming] = useState<string | null>(null);
  const [words, setWords] = useState(params.q ?? "");
  const defaultDate = dates.data?.default_date;

  useEffect(() => {
    if (!urlDate && defaultDate) setFilters({ date: defaultDate });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- written once, when the default date arrives
  }, [urlDate, defaultDate]);

  const names: Record<string, string> = {};
  for (const d of departments.data?.departments ?? []) names[d.code] = d.name;
  const benches = day.data?.benches ?? [];
  const bench = chosenBench(benches, params);
  const scope = bench ? [bench] : benches;
  const courts = courtsOf(scope);
  const types = listTypesOf(scope);
  const counts = entries.data?.counts;
  const only = query.only as string | undefined;
  const held = day.data?.state === "held";
  // an earlier version opened from a corrected list's link (design court-data-freshness, decision 17)
  const earlier = entries.data?.list?.superseded ? entries.data.list : null;
  const earlierBench = entries.data?.items[0]?.bench_id;

  function onDate(next: string) {
    setFilters({ date: next, bench_id: undefined, list_id: undefined, list_type: undefined, court_no: undefined });
  }

  function onWords(e: FormEvent) {
    e.preventDefault();
    setFilters({ q: words.trim() || undefined });
  }

  return (
    <div className="stack">
      <PageHeader title={T.causelist.title} subtitle={T.causelist.intro} />
      <ErrorBanner error={dates.error} onRetry={() => dates.refetch()} />
      {!date ? (
        dates.isPending ? (
          <Loading />
        ) : null
      ) : (
        <>
          <DayBar date={date} day={day.data} canFetch={can(me.data, "admin.napix_refetch")} onDate={onDate} />
          {day.isPending ? <Loading /> : null}
          <ErrorBanner error={day.error} onRetry={() => day.refetch()} />
          {benches.length > 0 ? (
            <div className={s.bar}>
              <BenchSelect
                benches={benches}
                value={benchValueOf(params)}
                onChange={(v) => setFilters({ ...benchParams(v), list_type: undefined, court_no: undefined })}
              />
            </div>
          ) : null}
          {bench ? (
            <ListStrip
              bench={bench}
              canView={can(me.data, "documents.view")}
              canDownload={can(me.data, "documents.download")}
              onEarlier={(id) => setFilters({ list_id: id, bench_id: undefined, offset: undefined })}
            />
          ) : null}
          {earlier ? (
            <Notice>
              <span className="row">
                <Badge tone="warning">{T.causelist.earlierBadge}</Badge>
                <span>{T.causelist.earlierText(formatDateTime(earlier.superseded_at))}</span>
                {earlier.has_pdf && can(me.data, "documents.view") ? (
                  <a href={listFileUrl(earlier.id, "inline")} target="_blank" rel="noopener noreferrer">
                    {T.causelist.view}
                  </a>
                ) : null}
                {earlier.has_pdf && can(me.data, "documents.download") ? (
                  <a href={listFileUrl(earlier.id, "attachment")} download>
                    {T.causelist.download}
                  </a>
                ) : null}
                <Button
                  variant="link"
                  onClick={() =>
                    setFilters({
                      list_id: undefined,
                      bench_id: earlierBench !== null && earlierBench !== undefined ? String(earlierBench) : undefined,
                      offset: undefined,
                    })
                  }
                >
                  {T.causelist.currentVersion}
                </Button>
              </span>
            </Notice>
          ) : null}
          {held ? (
            <section className="stack" aria-label={T.causelist.filters}>
              <form className={s.bar} onSubmit={onWords} aria-label={T.causelist.filters}>
                {types.length > 1 ? (
                  <SelectField
                    label={T.causelist.listType}
                    value={query.list_type ? String(query.list_type) : ""}
                    options={[
                      { value: "", label: T.causelist.anyListType },
                      ...types.map((t) => ({ value: t, label: T.causelist.listTypes[t] ?? t })),
                    ]}
                    onChange={(e) => setFilters({ list_type: e.target.value || undefined })}
                  />
                ) : null}
                {courts.length > 1 ? (
                  <SelectField
                    label={T.causelist.court}
                    value={query.court_no ? String(query.court_no) : ""}
                    options={[{ value: "", label: T.causelist.allCourts }, ...courts.map((c) => ({ value: c, label: c }))]}
                    onChange={(e) => setFilters({ court_no: e.target.value || undefined })}
                  />
                ) : null}
                <TextField
                  label={T.causelist.words}
                  hint={T.causelist.wordsHint}
                  value={words}
                  onChange={(e) => setWords(e.target.value)}
                />
                <Button type="submit" variant="secondary">
                  {T.causelist.search}
                </Button>
                {params.q ? (
                  <Button
                    variant="link"
                    onClick={() => {
                      setWords("");
                      setFilters({ q: undefined });
                    }}
                  >
                    {T.causelist.clear}
                  </Button>
                ) : null}
              </form>
              <ChipGroup label={T.causelist.show}>
                <Chip on={!only} onClick={() => setFilters({ only: undefined })}>
                  {T.causelist.onlyAll}
                  {counts ? ` (${formatNumber(counts.entries)})` : ""}
                </Chip>
                {ONLY_VALUES.map((v) => {
                  const key = COUNTED[v];
                  return (
                    <Chip key={v} on={only === v} onClick={() => setFilters({ only: only === v ? undefined : v })}>
                      {T.causelist.only[v]}
                      {counts && key ? ` (${formatNumber(counts[key])})` : ""}
                    </Chip>
                  );
                })}
              </ChipGroup>
              {counts ? (
                <p className="muted" aria-live="polite">
                  {T.causelist.counts(counts)}
                  {entries.data && (query.q || only) ? ` · ${T.causelist.shown(formatNumber(entries.data.total))}` : ""}
                </p>
              ) : null}
            </section>
          ) : null}
          {held && entries.isPending ? <Loading /> : null}
          {held ? <ErrorBanner error={entries.error} onRetry={() => entries.refetch()} /> : null}
          {held && entries.data ? (
            entries.data.items.length === 0 ? (
              <EmptyState>{T.causelist.noEntries}</EmptyState>
            ) : (
              <>
                <EntryTable items={entries.data.items} names={names} onClaim={setClaiming} />
                <Pagination
                  offset={Number(query.offset ?? 0)}
                  limit={ENTRY_PAGE}
                  total={entries.data.total}
                  onChange={(o) => setFilters({ offset: o ? String(o) : undefined })}
                />
              </>
            )
          ) : null}
          {day.data && !held && benches.length === 0 ? <EmptyState>{T.causelist.nothingHeld}</EmptyState> : null}
        </>
      )}
      {claiming ? (
        <ClaimDialog
          open
          caseRef={claiming}
          onClose={() => setClaiming(null)}
          onDone={() => void queryClient.invalidateQueries({ queryKey: CAUSELISTS_KEY })}
        />
      ) : null}
    </div>
  );
}
