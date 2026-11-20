"use client";

/**
 * Insights (design state-insights, section J, decisions 31 and 32; plan §5.1 and §5.10): the cross-filtering analysis
 * page first under Oversight. Every filter lives in the URL (`router.replace`, so Back and Forward work and a link can be
 * shared; another viewer sees their own scope's numbers, because the server applies the scope and visibility to every
 * count). One overview request per change, 300 ms after the last change, with the earlier request cancelled; the case
 * list is its own request, so paging does not count the charts again. The charts and the accountability section load
 * Recharts through `next/dynamic` with `ssr: false`, so no other route carries it. The page writes nothing.
 *
 * Top to bottom: the view (when there is more than one), the status switch, the two toggles, the date bar, the chips
 * with Clear All, the headline figures, the charts, the accountability section and the case list with its exports.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { FilterChips } from "@/components/filters/FilterChips";
import { Button, CheckField, EmptyState, ErrorBanner, Loading, PageHeader, SegmentedField, SelectField, TextField } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { InsightsOverview, InsightsScopes } from "@/lib/api/types";
import { formatNumber, istDay } from "@/lib/format";
import {
  chipRemoved,
  clearedAll,
  DATE_OF,
  datesOutOfOrder,
  datesSet,
  filterQuery,
  HEADLINE_ORDER,
  headlineClicked,
  headlineSelected,
  includeIaOf,
  insightsHref,
  insightsParams,
  OVERVIEW_DEBOUNCE_MS,
  QUICK_DATES,
  quickDated,
  stateOnlyOf,
  STATUSES,
  statusOf,
  viewSet,
  type HeadlineKey,
} from "@/lib/insights";
import { INSIGHTS_ERRORS, T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { useDebounced } from "@/lib/useDebounced";

import { CaseList } from "./CaseList";
import s from "./insights.module.css";

/** The charts and the accountability section, with Recharts, loaded only here and only in the browser. */
const InsightsCharts = dynamic(() => import("./InsightsCharts").then((m) => m.InsightsCharts), {
  ssr: false,
  loading: () => <Loading lines={6} />,
});

export const SCOPES_KEY = ["insights", "scopes"] as const;

/** The view choices: the whole State (when open) and each department of the switch, as one select's values. */
export function viewOptions(scopes: InsightsScopes | undefined): { value: string; label: string }[] {
  if (!scopes) return [];
  return [
    ...(scopes.state ? [{ value: "state", label: T.insights.wholeState }] : []),
    ...scopes.departments.map((d) => ({ value: `department:${d.code}`, label: d.name })),
  ];
}

/** The view now shown: the URL's, else the server's default. */
export function currentView(params: Params, scopes: InsightsScopes | undefined): string {
  if (params.scope === "state") return "state";
  const dept = params.department ?? scopes?.default.department ?? undefined;
  if (params.scope === "department") return dept ? `department:${dept}` : "";
  if (scopes?.default.scope === "state") return "state";
  return scopes?.default.department ? `department:${scopes.default.department}` : "";
}

export function InsightsPage({ params: fromUrl }: { params: Params }) {
  const router = useRouter();
  const urlKey = queryString(insightsParams(fromUrl));
  const [params, setParams] = useState<Params>(() => insightsParams(fromUrl));
  const [seenUrl, setSeenUrl] = useState(urlKey);
  if (seenUrl !== urlKey) {
    // Back, Forward or a link: the address changed under the page (React's derived-state pattern)
    setSeenUrl(urlKey);
    setParams(insightsParams(fromUrl));
  }

  function go(next: Params) {
    const clean = insightsParams(next);
    setParams(clean);
    router.replace(insightsHref(clean), { scroll: false });
  }

  const scopes = useQuery({
    queryKey: SCOPES_KEY,
    queryFn: ({ signal }) => api<InsightsScopes>("/insights/scopes", { signal }),
    staleTime: 5 * 60_000,
  });
  const filters = queryString(filterQuery(params));
  const settled = useDebounced(filters, OVERVIEW_DEBOUNCE_MS);
  const overview = useQuery({
    queryKey: ["insights", "overview", settled],
    // the earlier request is cancelled: React Query aborts a fetch whose signal was read once nothing waits for it
    queryFn: ({ signal }) => api<InsightsOverview>(`/insights${settled}`, { signal }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const data = overview.data;
  const views = viewOptions(scopes.data);
  const view = currentView(params, scopes.data);

  function chooseView(value: string) {
    if (value === "state") go(viewSet(viewSet(params, "department", null), "scope", "state"));
    else if (value.startsWith("department:")) go(viewSet(viewSet(params, "scope", "department"), "department", value.slice(11)));
  }

  const status = statusOf(params);
  return (
    <div className={s.page}>
      <PageHeader title={T.insights.title} subtitle={T.insights.subtitle} />
      <section className={s.section} aria-label={T.insights.controls}>
        <div className={s.controls}>
          {views.length > 1 ? (
            <div className={s.view}>
              <SelectField label={T.insights.viewLabel} options={views} value={view} onChange={(e) => chooseView(e.target.value)} />
            </div>
          ) : null}
          <SegmentedField
            label={T.insights.statusLabel}
            options={STATUSES.map((k) => ({ value: k, label: T.insights.statuses[k]! }))}
            value={status}
            onChange={(v) => go(viewSet(params, "status", v === "pending" ? null : v))}
          />
          {/* in a field row the checks sit on the control line (design portal-ui-polish-2, decision 26) */}
          <CheckField
            inline
            label={T.insights.stateOnlyLabel}
            title={T.insights.stateOnlyHint}
            checked={stateOnlyOf(params)}
            onChange={(e) => go(viewSet(params, "state_only", e.target.checked ? null : "false"))}
          />
          <CheckField
            inline
            label={T.insights.includeIaLabel}
            title={T.insights.includeIaHint}
            checked={includeIaOf(params)}
            onChange={(e) => go(viewSet(params, "include_ia", e.target.checked ? "true" : null))}
          />
        </div>
        <DateBar key={`${params.date_of ?? ""}|${params.from ?? ""}|${params.to ?? ""}`} params={params} onApply={go} />
        <FilterChips
          chips={(data?.chips ?? []).map((c) => ({ keys: [c.param], label: c.label }))}
          onRemove={(keys) => go(keys.reduce((p, k) => chipRemoved(p, k), params))}
          onClearAll={() => go(clearedAll(params))}
        />
      </section>
      {overview.error ? (
        <ErrorBanner error={overview.error} messages={INSIGHTS_ERRORS} onRetry={() => void overview.refetch()} retrySize="md" />
      ) : null}
      {overview.isPending && !overview.error ? <Loading lines={4} /> : null}
      {data ? (
        <>
          <Notes data={data} />
          <Headline data={data} params={params} onChange={go} />
          {data.headline.cases === 0 ? (
            <EmptyState title={T.insights.emptyNote} />
          ) : (
            <InsightsCharts data={data} params={params} onChange={go} />
          )}
          <CaseList params={params} settledFilters={settled} onChange={go} />
        </>
      ) : null}
    </div>
  );
}

/** The coverage words, the interlocutory applications counted inside their main case, and the cases still waiting. */
function Notes({ data }: { data: InsightsOverview }) {
  const h = data.headline;
  return (
    <div className={s.notes} role="status" aria-live="polite">
      <p>{data.coverage.line}</p>
      {h.applications_inside > 0 || h.applications_main_not_held > 0 ? (
        <p>{T.insights.applicationsNote(h.applications_inside, h.applications_main_not_held)}</p>
      ) : null}
      {data.coverage.facts_waiting > 0 ? <p>{T.insights.waitingNote(data.coverage.facts_waiting)}</p> : null}
    </div>
  );
}

/** Decision 22: the headline figures, counted with every filter; a click sets its filter, a second click removes it. */
function Headline({ data, params, onChange }: { data: InsightsOverview; params: Params; onChange: (p: Params) => void }) {
  return (
    <section className={s.section} aria-label={T.insights.headline.heading}>
      <p className="visually-hidden">{T.insights.headline.filterHint}</p>
      <ul className={s.headline}>
        {HEADLINE_ORDER.map((key: HeadlineKey) => {
          const next = headlineClicked(params, key);
          const pressed = next ? headlineSelected(params, key) : undefined;
          const label = T.insights.headline.labels[key]!;
          return (
            <li key={key}>
              <button
                type="button"
                className={s.figure}
                aria-pressed={pressed}
                disabled={!next}
                data-figure={key}
                onClick={() => next && onChange(next)}
              >
                <span className={s.figureLabel}>
                  {pressed ? "✓ " : ""}
                  {label}
                </span>
                <span className={s.figureValue}>{formatNumber(data.headline[key])}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The date bar (decision 24): Date Of, From and To applied together, and the quick choices that fill them. */
function DateBar({ params, onApply }: { params: Params; onApply: (p: Params) => void }) {
  const [dateOf, setDateOf] = useState(params.date_of ?? "registration");
  const [from, setFrom] = useState(params.from ?? "");
  const [to, setTo] = useState(params.to ?? "");
  const wrong = datesOutOfOrder(from, to);
  function apply(e: FormEvent) {
    e.preventDefault();
    if (!wrong) onApply(datesSet(params, dateOf, from, to));
  }
  const today = istDay();
  return (
    <form onSubmit={apply} aria-label={T.insights.dates.legend}>
      <fieldset className={s.dates}>
        <legend>{T.insights.dates.legend}</legend>
        <div className={s.dateFields}>
          <SelectField
            label={T.insights.dates.dateOfLabel}
            options={DATE_OF.map((k) => ({ value: k, label: T.insights.dates.dateOf[k]! }))}
            value={dateOf}
            onChange={(e) => setDateOf(e.target.value)}
          />
          <TextField label={T.insights.dates.fromLabel} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <TextField
            label={T.insights.dates.toLabel}
            type="date"
            value={to}
            error={wrong ? T.insights.dates.outOfOrderError : undefined}
            onChange={(e) => setTo(e.target.value)}
          />
          <Button type="submit" variant="secondary" disabled={wrong}>
            {T.insights.dates.applyButton}
          </Button>
        </div>
        <div className={s.quick} role="group" aria-label={T.insights.dates.quickLabel}>
          {QUICK_DATES.map((q) => (
            <Button key={q} type="button" variant="ghost" onClick={() => onApply(quickDated(params, q, today))}>
              {T.insights.dates.quick[q]}
            </Button>
          ))}
        </div>
      </fieldset>
    </form>
  );
}
