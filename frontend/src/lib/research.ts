/**
 * The research index in the portal (design research-index-portal), pure helpers only; nothing here calls the API:
 * - when the filters and the research notice show (decision 3) and the notice's sentence (decision 4);
 * - the filters: read from and written to the address for one tab (decision 8), the body `POST /assistant/ask` takes
 *   (decision 9: omitted when none is set), the checks the server makes (decision 7), the chips (decisions 6 and 9) and
 *   the typed act's key by row 250's `_act_key` rule (decision 10);
 * - the removal note split off the answer and put into words (decision 16), the withheld reason (decision 17);
 * - the passage view's runs (decision 14).
 */
import type { AssistantChecks, AssistantFilters, AssistantFiltersBody, AssistantScope, AssistantStatus } from "./api/types";
import { formatDate } from "./format";
import { T } from "./messages";
import { titleCase } from "./titleCase";

const A = T.assistant;
const F = T.assistant.filters;

export const FORMS = ["judgment", "final", "interim"] as const;
export const OUTCOMES = ["allowed", "partly_allowed", "dismissed", "disposed_of", "withdrawn", "closed"] as const;
export const CITE_MAX = 80;
/** The address keys of the filters (decision 8), beside `tab`. */
export const FILTER_PARAMS = ["forms", "substantive", "outcomes", "against_state", "cites", "act", "from", "to"] as const;

export type DateMode = "" | "date" | "range";

export interface ResearchFilters {
  forms: string[];
  substantive: boolean;
  outcomes: string[];
  againstState: boolean;
  cites: string;
  /** the act key the server matches (decision 10) */
  act: string;
  dateMode: DateMode;
  from: string;
  to: string;
}

export const NO_FILTERS: ResearchFilters = {
  forms: [],
  substantive: false,
  outcomes: [],
  againstState: false,
  cites: "",
  act: "",
  dateMode: "",
  from: "",
  to: "",
};

// ------------------------------------------------------------------------------------------------ when they show

/** Decision 3: filters and the research notice only when the index serves the question: ollama mode, the research
 * state not `off`, on My Cases or All Court Orders (`building`, `ready` and `unavailable` alike, as the server). */
export function filtersServed(status: AssistantStatus | undefined, scope: AssistantScope): boolean {
  if (!status || status.mode !== "ollama") return false;
  if (scope !== "my_cases" && scope !== "research") return false;
  return !!status.research && status.research.state !== "off";
}

export interface ResearchNotice {
  /** `hint`: a hint line; `warning`: a warning notice */
  tone: "hint" | "warning";
  text: string;
}

/** A coverage as a whole percent, or "under 1%". */
export function coveragePercent(coverage: number): string {
  const pct = Math.floor(coverage * 100);
  return pct < 1 ? A.research.underOne : A.research.percent(pct);
}

/** Decision 4: the one sentence under the readiness notice, chosen by the state; none for `ready`. */
export function researchNotice(status: AssistantStatus | undefined, scope: AssistantScope): ResearchNotice | null {
  if (!filtersServed(status, scope)) return null;
  const r = status!.research!;
  if (r.state === "unavailable") return { tone: "warning", text: A.research.unavailable };
  if (r.state === "building") {
    if (r.coverage === null || r.coverage === undefined) return { tone: "hint", text: A.research.buildingUnknown };
    return { tone: "hint", text: A.research.building(coveragePercent(r.coverage)) };
  }
  return null;
}

// ------------------------------------------------------------------------------------------------ the address

type Params = URLSearchParams | Record<string, string | string[] | undefined>;

function param(params: Params, key: string): string {
  if (params instanceof URLSearchParams) return params.get(key) ?? "";
  const v = params[key];
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

/** A real calendar day `YYYY-MM-DD`. */
export function isDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

function listOf(raw: string, allowed: readonly string[]): string[] {
  const seen = new Set(raw.split(",").map((x) => x.trim()));
  return allowed.filter((v) => seen.has(v));
}

/** Decision 8: the filters of the address; unknown values (an outcome not in the list, a bad date) are dropped. */
export function readFilters(params: Params): ResearchFilters {
  const from = isDay(param(params, "from")) ? param(params, "from") : "";
  const to = isDay(param(params, "to")) ? param(params, "to") : "";
  return {
    forms: listOf(param(params, "forms"), FORMS),
    substantive: param(params, "substantive") === "1",
    outcomes: listOf(param(params, "outcomes"), OUTCOMES),
    againstState: param(params, "against_state") === "1",
    cites: param(params, "cites").slice(0, 200),
    act: param(params, "act").slice(0, 200),
    dateMode: from && to && from === to ? "date" : from || to ? "range" : "",
    from,
    to,
  };
}

/** The dates the filters send: one day for A Date, the range's set ends for Between Dates. */
function dates(f: ResearchFilters): { from: string; to: string } {
  if (f.dateMode === "date") return isDay(f.from) ? { from: f.from, to: f.from } : { from: "", to: "" };
  if (f.dateMode === "range") return { from: isDay(f.from) ? f.from : "", to: isDay(f.to) ? f.to : "" };
  return { from: "", to: "" };
}

/** Decision 8: the address's filter keys for these filters (only the set ones). */
export function writeFilters(f: ResearchFilters): Record<string, string> {
  const out: Record<string, string> = {};
  if (f.forms.length) out.forms = FORMS.filter((v) => f.forms.includes(v)).join(",");
  if (f.substantive) out.substantive = "1";
  if (f.outcomes.length) out.outcomes = OUTCOMES.filter((v) => f.outcomes.includes(v)).join(",");
  if (f.againstState) out.against_state = "1";
  if (f.cites.trim()) out.cites = f.cites.trim();
  if (f.act.trim()) out.act = f.act.trim();
  const d = dates(f);
  if (d.from) out.from = d.from;
  if (d.to) out.to = d.to;
  return out;
}

/** The page address of a tab with its filters. */
export function filtersHref(tabKey: string, f: ResearchFilters): string {
  const q = new URLSearchParams({ tab: tabKey, ...writeFilters(f) });
  return `/assistant?${q.toString()}`;
}

/** Whether the address names any filter (decision 8's notice when the panel is hidden). */
export function addressHasFilters(params: Params): boolean {
  return FILTER_PARAMS.some((k) => param(params, k) !== "");
}

// ------------------------------------------------------------------------------------------------ the body

/** Citations are compared after collapsing spaces (row 250). */
export function collapse(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

/** Decision 9: exactly the filters in view, with the keys `from` and `to`; undefined when none is set (never `{}`). */
export function filtersBody(f: ResearchFilters): AssistantFiltersBody | undefined {
  const body: AssistantFiltersBody = {};
  if (f.forms.length) body.forms = FORMS.filter((v) => f.forms.includes(v));
  if (f.substantive) body.substantive_only = true;
  if (f.outcomes.length) body.outcomes = OUTCOMES.filter((v) => f.outcomes.includes(v));
  if (f.againstState) body.against_state = true;
  const cites = collapse(f.cites);
  if (cites) body.cites = cites;
  const act = f.act.trim();
  if (act) body.act = act;
  const d = dates(f);
  if (d.from) body.from = d.from;
  if (d.to) body.to = d.to;
  return Object.keys(body).length ? body : undefined;
}

/** The number of fields set (the button's "Search Filters (n)"). */
export function filtersCount(f: ResearchFilters): number {
  const d = dates(f);
  return [f.forms.length > 0, f.substantive, f.outcomes.length > 0, f.againstState, !!collapse(f.cites), !!f.act.trim(), !!(d.from || d.to)].filter(Boolean)
    .length;
}

export interface FilterErrors {
  from?: string;
  to?: string;
  cites?: string;
}

/** Decision 7: the checks the server makes, made before sending; Ask stays disabled while one fails. */
export function checkFilters(f: ResearchFilters): FilterErrors {
  const out: FilterErrors = {};
  if (f.dateMode === "range" && isDay(f.from) && isDay(f.to) && f.from > f.to) out.to = F.fromAfterTo;
  if (collapse(f.cites).length > CITE_MAX) out.cites = F.tooLong;
  return out;
}

export function hasErrors(e: FilterErrors): boolean {
  return Object.values(e).some(Boolean);
}

/** Row 250's `_act_key`: lower case, dots removed, every other run of non-letters and non-digits a space, a leading
 * "the" dropped (a typed act that was not picked is sent this way, decision 10). */
export function actKey(text: string): string {
  const key = text
    .toLowerCase()
    .replace(/\./g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
  return key.replace(/^the\s+/, "");
}

// ------------------------------------------------------------------------------------------------ the chips

export interface FilterChip {
  /** what the chip's remove button drops: `forms:judgment`, `outcomes:dismissed`, `substantive`, `against_state`,
   * `cites`, `act` or `date` */
  keys: string[];
  label: string;
}

/** The act's words on a chip: its label as picked, else the key in Title Case (decision 9). */
export function actWords(key: string, labels?: ReadonlyMap<string, string>): string {
  return labels?.get(key) ?? titleCase(key);
}

/** The chips of a set of filters, in the panel's field order (decisions 6 and 9). */
export function filterChips(f: ResearchFilters, actLabels?: ReadonlyMap<string, string>): FilterChip[] {
  const out: FilterChip[] = [];
  for (const v of FORMS) if (f.forms.includes(v)) out.push({ keys: [`forms:${v}`], label: F.forms[v]! });
  if (f.substantive) out.push({ keys: ["substantive"], label: F.chipSubstantive });
  for (const v of OUTCOMES) if (f.outcomes.includes(v)) out.push({ keys: [`outcomes:${v}`], label: F.outcomes[v]! });
  if (f.againstState) out.push({ keys: ["against_state"], label: F.chipAgainstState });
  const cites = collapse(f.cites);
  if (cites) out.push({ keys: ["cites"], label: F.chipCites(cites) });
  if (f.act.trim()) out.push({ keys: ["act"], label: F.chipAct(actWords(f.act.trim(), actLabels)) });
  const d = dates(f);
  if (d.from && d.to && d.from === d.to) out.push({ keys: ["date"], label: F.chipOn(formatDate(d.from)) });
  else if (d.from && d.to) out.push({ keys: ["date"], label: F.chipBetween(F.chipFrom(formatDate(d.from)), formatDate(d.to)) });
  else if (d.from) out.push({ keys: ["date"], label: F.chipFrom(formatDate(d.from)) });
  else if (d.to) out.push({ keys: ["date"], label: F.chipTo(formatDate(d.to)) });
  return out;
}

/** The filters without what a chip names. */
export function removeChip(f: ResearchFilters, keys: string[]): ResearchFilters {
  let next = { ...f };
  for (const k of keys) {
    const [field, value] = k.split(":");
    if (field === "forms") next = { ...next, forms: next.forms.filter((x) => x !== value) };
    else if (field === "outcomes") next = { ...next, outcomes: next.outcomes.filter((x) => x !== value) };
    else if (field === "substantive") next = { ...next, substantive: false };
    else if (field === "against_state") next = { ...next, againstState: false };
    else if (field === "cites") next = { ...next, cites: "" };
    else if (field === "act") next = { ...next, act: "" };
    else if (field === "date") next = { ...next, dateMode: "", from: "", to: "" };
  }
  return next;
}

/** A question's stored filters (`AssistantMessageOut.filters`) as the panel's shape, for its chips. */
export function storedFilters(stored: AssistantFilters | null | undefined): ResearchFilters | null {
  if (!stored) return null;
  const from = stored.from ?? "";
  const to = stored.to ?? "";
  const f: ResearchFilters = {
    forms: (stored.forms ?? []).filter((v) => (FORMS as readonly string[]).includes(v)),
    substantive: !!stored.substantive_only,
    outcomes: (stored.outcomes ?? []).filter((v) => (OUTCOMES as readonly string[]).includes(v)),
    againstState: !!stored.against_state,
    cites: stored.cites ?? "",
    act: stored.act ?? "",
    dateMode: from && to && from === to ? "date" : from || to ? "range" : "",
    from,
    to,
  };
  return filtersCount(f) > 0 ? f : null;
}

// ------------------------------------------------------------------------------------------------ the check notes

/** The server's removal line (`answer_check_rules.REMOVED_NOTE`), the answer text's last line exactly. */
const REMOVED_LINE =
  /\n?(\[Removed by ASLMS: (\d+) sentences? whose quotes, dates, numbers, case numbers, names or outcomes were not found in the records they cite\.\])$/;

export interface RemovedNote {
  /** the answer text without the line (the `[S#]` markers run over this only) */
  body: string;
  /** the server's line as written */
  line: string;
  count: number;
  /** the reasons in words, or null when the counts are missing (the block then shows the line) */
  reasons: string[] | null;
}

function removedSum(checks: AssistantChecks | null | undefined): number {
  return Object.values(checks?.removed ?? {}).reduce((a, b) => a + (Number(b) || 0), 0);
}

/** Decision 16: the counts in words, e.g. ["Not found in the records they cite: 1 date, 1 name.", "1 stated a fact
 * without a source."]. */
export function removedReasons(removed: Record<string, number>): string[] {
  const parts: string[] = [];
  for (const key of ["quote", "date", "number", "case_no", "name", "outcome"]) {
    const n = Number(removed[key] ?? 0);
    if (n > 0) parts.push(`${n} ${n === 1 ? A.removedReasons[key] : A.removedPlurals[key]}`);
  }
  const out: string[] = [];
  if (parts.length) out.push(A.removedNotFound(parts.join(", ")));
  const uncited = Number(removed.uncited ?? 0);
  if (uncited > 0) out.push(A.removedUncited(uncited));
  return out;
}

/** Decision 16: the removal line split off an answer's text, when its last line is exactly the server's form. */
export function splitRemoved(content: string | null | undefined, checks: AssistantChecks | null | undefined): RemovedNote | null {
  if (!content) return null;
  const m = REMOVED_LINE.exec(content);
  if (!m) return null;
  const body = content.slice(0, m.index);
  const counted = removedSum(checks) > 0;
  return {
    body,
    line: m[1]!,
    count: Number(m[2]),
    reasons: counted ? removedReasons(checks!.removed as Record<string, number>) : null,
  };
}

/** Decision 17: why a withheld answer was held back, or null. */
export function withheldLine(outcome: string | null | undefined, checks: AssistantChecks | null | undefined): string | null {
  if (outcome !== "no_match" || !checks?.withheld) return null;
  return A.withheld[checks.withheld] ?? null;
}

// ------------------------------------------------------------------------------------------------ the passage

export interface Highlight {
  start: number;
  end: number;
  kind: "passage" | "quote";
  exact: boolean;
}

export interface PassageRun {
  text: string;
  passage: boolean;
  quote: boolean;
}

/** Decision 14: the page text cut into runs at every highlight's ends, offsets clipped to the text; a quote run inside a
 * passage run carries both. */
export function passageRuns(text: string, highlights: readonly Highlight[]): PassageRun[] {
  const len = text.length;
  const marks = highlights
    .map((h) => ({ ...h, start: Math.max(0, Math.min(len, h.start)), end: Math.max(0, Math.min(len, h.end)) }))
    .filter((h) => h.end > h.start);
  const cuts = new Set<number>([0, len]);
  for (const h of marks) {
    cuts.add(h.start);
    cuts.add(h.end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const out: PassageRun[] = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i]!;
    const b = points[i + 1]!;
    if (b <= a) continue;
    const over = marks.filter((h) => h.start <= a && h.end >= b);
    const run = { text: text.slice(a, b), passage: over.some((h) => h.kind === "passage"), quote: over.some((h) => h.kind === "quote") };
    const last = out[out.length - 1];
    if (last && last.passage === run.passage && last.quote === run.quote) last.text += run.text;
    else out.push(run);
  }
  return out;
}
