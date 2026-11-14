/**
 * The Case Assistant's pure helpers (design assistant, decision 14): the excerpts' `[[ ]]` highlights, where a source
 * opens, the words of a source, the "Copy to note" text and the hourly allowance. Nothing here calls the API.
 * Design assistant-ollama (decisions 8, 10 and 14): the source kinds in words, the `[S#]` markers of a local-model
 * answer, the Court Record / Internal Records groups with the uncited sources apart, and the narrowest visibility of
 * the cited internal records for Copy to note.
 * Design assistant-ollama-work (decisions 1, 2, 9 and 10): the case tab is about its own case only; the Assistant page's
 * three tabs (My Work, My Cases, All Court Orders) in the address with their fallback; a My Work answer's columns and
 * values in words.
 */
import type { AssistantCitation, AssistantMessage, AssistantScope, AssistantStatus } from "./api/types";
import { INLINE_PDF } from "./documents";
import { formatDate } from "./format";
import { T } from "./messages";
import { labelFor, serverLabel } from "./displayLabels";

export interface Segment {
  text: string;
  hit: boolean;
}

/** An excerpt split at its `[[ ]]` markers (the server's `ts_headline` StartSel / StopSel), as plain text pieces. */
export function highlights(passage: string | null | undefined): Segment[] {
  const out: Segment[] = [];
  const text = passage ?? "";
  const re = /\[\[(.*?)\]\]/gs;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), hit: false });
    if (m[1]) out.push({ text: m[1], hit: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), hit: false });
  return out;
}

/** The excerpt without its markers (for a note). */
export function plainPassage(passage: string | null | undefined): string {
  return highlights(passage)
    .map((s) => s.text)
    .join("");
}

export interface SourceLink {
  /** `document`: the relay's file route, opened in a new tab; `court_order`: the court-record view in the portal;
   * `case_tab`: a tab of the case page (a note, the file movement, the case details). */
  kind: "document" | "court_order" | "case_tab";
  href: string;
  newTab: boolean;
}

/**
 * Where a source opens (decision 14): a court filing and a court order of a case the reader can open go to the
 * ordinary file route through the relay, with `#page=N` for a PDF shown in the browser; a court order of a case the
 * reader cannot open goes to `/assistant/orders/[orderId]?m=` (decision 11). None when the source is unavailable.
 */
export function sourceLink(c: AssistantCitation, messageId: string, inlinePdf: boolean = INLINE_PDF): SourceLink | null {
  if (!c.available || !c.open) return null;
  if (c.open.kind === "case_tab") return { kind: "case_tab", href: c.open.href, newTab: false };
  if (c.open.kind === "court_order") {
    if (!c.order_id) return null;
    return {
      kind: "court_order",
      href: `/assistant/orders/${encodeURIComponent(c.order_id)}?m=${encodeURIComponent(messageId)}`,
      newTab: false,
    };
  }
  let href = c.open.href;
  const inline = href.includes("disposition=inline");
  if (inline && !inlinePdf) href = href.replace("disposition=inline", "disposition=attachment");
  const page = inline && inlinePdf && c.page ? `#page=${c.page}` : "";
  return { kind: "document", href: `/api/backend${href}${page}`, newTab: true };
}

const A = T.assistant;
const KINDS: Record<string, string> = T.assistant.kinds;

function kindWord(kind: string): string {
  return labelFor(KINDS, kind);
}

/** A source's kind in Title Case words (design assistant-ollama, decision 14). */
export function kindLabel(c: AssistantCitation): string {
  if (c.source_kind === "department_document" && c.what === "note_attachment") return kindWord("note_attachment");
  return kindWord(c.source_kind);
}

/** Whether a source is the department's own record (decision 8). */
export function isInternal(c: AssistantCitation): boolean {
  return c.source_kind === "note" || c.source_kind === "file_movement" || c.source_kind === "department_document";
}

/** "Order of 12 Mar 2026, No. 5, page 2" / "Petition of 1 Feb 2026, page 1" (decision 13); a local model's other kinds
 * by their kind ("Case Details", "Note 4, Hearing Note", "File Movement", "Department Document of 1 Feb 2026"). */
export function sourceWords(c: AssistantCitation): string {
  if (c.source_kind === "case_details") return kindWord("case_details");
  if (c.source_kind === "file_movement") return kindWord("file_movement");
  if (c.source_kind === "note") {
    const parts = [c.note ? T.assistant.noteN(c.note.seq_no, c.note.kind_label) : kindWord("note")];
    if (c.doc_date) parts.push(formatDate(c.doc_date));
    return parts.join(", ");
  }
  if (c.source_kind === "department_document") {
    const what = c.doc_type_label ?? kindLabel(c);
    const parts = [c.doc_date ? `${what} of ${formatDate(c.doc_date)}` : what];
    if (c.page) parts.push(T.assistant.page(c.page));
    return parts.join(", ");
  }
  const what = c.source_kind === "court_order" ? T.assistant.order : (c.doc_type_label ?? T.assistant.order);
  const parts = [`${what} of ${formatDate(c.doc_date)}`];
  if (c.order_no) parts.push(T.assistant.no(c.order_no));
  if (c.page) parts.push(T.assistant.page(c.page));
  return parts.join(", ");
}

/** The case a source belongs to, when it is another case than `currentCaseId`. */
export function otherCaseName(c: AssistantCitation, currentCaseId?: string | null): string | null {
  if (currentCaseId && c.case.id === currentCaseId) return null;
  return c.case.case_no_text ?? c.case.cnr ?? null;
}

/** The text "Copy to note" puts into the note: the answer, then its references in words (decision 13); of a local
 * model's answer only the cited sources. Design assistant-polish, decision 17: an answer with labelled citations (a
 * local model's or a quick fact) names each cited source by its own label, so every `[S#]` marker in the note has its
 * line ("No longer available" for one the reader can no longer reach); an answer without labels keeps 1..n. */
export function noteText(m: AssistantMessage): string {
  const labelled = hasLabels(m);
  const refs = labelled
    ? m.citations
        .filter((c) => c.cited !== false && c.label)
        .map((c) => T.assistant.copyRef(c.label!, c.available ? refWords(c) : T.assistant.noLongerAvailable))
    : m.citations.filter((c) => c.available && c.cited !== false).map((c, i) => T.assistant.copyRef(i + 1, refWords(c)));
  // a note's text is stored and searched on the server: the dates' no-break spaces (design portal-ui-kit-fixes,
  // decision 5) go back to ordinary spaces
  return [m.content ?? "", refs.length ? `\n${T.assistant.copyIntro}` : "", ...refs]
    .filter((x) => x !== "")
    .join("\n")
    .replace(/ /g, " ");
}

function refWords(c: AssistantCitation): string {
  const where = c.case.case_no_text ? ` (${c.case.case_no_text})` : "";
  const passage = plainPassage(c.passage);
  return `${sourceWords(c)}${where}${passage ? `: “${passage}”` : ""}`;
}

/** Whether an answer's citations carry source labels (`S1`..): a local model's answer or a quick fact, whose `[S#]`
 * markers open their sources (design assistant-polish, decision 16). */
export function hasLabels(m: AssistantMessage): boolean {
  return m.citations.some((c) => !!c.label);
}

/** Whether an answer is a quick fact from the case record (design assistant-polish, decision 15): read from the
 * server's `engine.kind`, never decided here. */
export function isCaseRecord(m: AssistantMessage): boolean {
  return m.engine?.kind === "case_record";
}

/** A marker's accessible name (decision 16): "Source S1: Order of 18 Feb 2026, No. 7, page 2", "(Internal)" after an
 * internal kind, "No Longer Available" for a source the reader can no longer reach. */
export function markerName(c: AssistantCitation): string {
  const label = c.label ?? "";
  if (!c.available) return T.assistant.markerAria(label, T.assistant.markerGone);
  const internal = isInternal(c) ? ` (${T.assistant.internalBadge})` : "";
  return T.assistant.markerAria(label, `${sourceWords(c)}${internal}`);
}

/** The words of a source's open link in its dialog (decision 16), by where it opens. */
export function openWords(c: AssistantCitation, link: SourceLink): string {
  const o = T.assistant.openLabels;
  if (link.kind === "court_order") return o.court_record;
  if (c.source_kind === "court_order") return o.court_order;
  if (c.source_kind === "court_filing") return o.court_filing;
  if (c.source_kind === "case_details") return o.case_details;
  if (c.source_kind === "department_document") return o.department_document;
  if (c.source_kind === "note") return o.note;
  return o.case_page;
}

/** The questions left this hour (never below 0). */
export function questionsLeft(status: AssistantStatus | undefined): number | null {
  if (!status) return null;
  return Math.max(0, status.limits.questions_per_hour - status.limits.used_last_hour);
}

/** The scopes of a screen (design assistant-ollama-work, decisions 1 and 2): the case tab is about its own case only;
 * the page has My Work, My Cases and All Court Orders, each shown only when the server offers it. */
export function scopesFor(screen: "case" | "page"): AssistantScope[] {
  return screen === "case" ? ["case"] : ["my_work", "my_cases", "research"];
}

/** The Assistant page's tabs in the address (`/assistant?tab=`), in the owner's order (decision 2). */
export const PAGE_TABS: readonly { key: string; scope: AssistantScope }[] = [
  { key: "my-work", scope: "my_work" },
  { key: "my-cases", scope: "my_cases" },
  { key: "court-orders", scope: "research" },
];

/** The page's scopes the server offers (`GET /assistant/status` `scopes`), in tab order; none before it answers. */
export function pageScopes(status: AssistantStatus | undefined): AssistantScope[] {
  const offered = new Set(status?.scopes ?? []);
  return PAGE_TABS.filter((t) => offered.has(t.scope)).map((t) => t.scope);
}

/** The scope of `?tab=`: the named tab when offered, otherwise My Work when offered, otherwise My Cases. */
export function scopeForTab(tab: string | null | undefined, scopes: AssistantScope[]): AssistantScope | null {
  const wanted = PAGE_TABS.find((t) => t.key === tab)?.scope;
  if (wanted && scopes.includes(wanted)) return wanted;
  if (scopes.includes("my_work")) return "my_work";
  if (scopes.includes("my_cases")) return "my_cases";
  return scopes[0] ?? null;
}

/** The address of a page tab. */
export function tabHref(scope: AssistantScope): string {
  const key = PAGE_TABS.find((t) => t.scope === scope)?.key ?? "my-cases";
  return `/assistant?tab=${key}`;
}

/** A My Work answer: written by the server from the asker's own lists (decision 4), never a model's text. */
export function isWorkAnswer(m: AssistantMessage): boolean {
  return !!m.work;
}

/** The columns of a My Work answer after the case, by question (decision 10's allow-list, the case fields apart). */
export const WORK_COLUMNS: Record<string, readonly string[]> = {
  pending_actions: ["pending_action_label", "due_date", "overdue_days", "due_soon", "since", "sent_by"],
  cases_with_me: ["pending_action_label", "due_date", "overdue_days", "due_soon", "since", "sent_by"],
  sent_by_me: ["date", "action", "to", "pending_action_label", "due_date", "still_there"],
  my_hearings: ["date", "court_no", "item_no", "bench", "approximate"],
  listed_tomorrow: ["date", "court_no", "item_no", "bench", "approximate"],
  my_due_dates: ["date", "kind_label", "pending_action_label"],
  unread_alerts: ["date", "kind_label", "severity", "title"],
  new_orders: ["date", "kind_label", "severity", "title"],
  needs_attention: ["kind_label", "title", "date", "detail", "overdue_days"],
  claimed_by_me: ["claimed_on", "via", "department", "status"],
  department_claimed: ["claimed_on", "department", "role", "assigned_to", "status"],
  awaiting_claim: ["department", "band", "next_hearing", "last_listed_on"],
};

export function workColumns(question: string | null | undefined): readonly string[] {
  return (question && WORK_COLUMNS[question]) || [];
}

const WORK_DATES = new Set(["due_date", "since", "date", "claimed_on", "last_listed_on"]);
const WORK_FLAGS = new Set(["due_soon", "approximate", "still_there"]);
const WORK_SERVER_LABELS = new Set(["pending_action_label", "kind_label"]);

/** A My Work field in words (null when there is nothing to show, so a phone card draws no empty row). The department
 * is shown by the kit's office name, not here. */
export function workValue(field: string, value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (WORK_DATES.has(field)) return typeof value === "string" ? formatDate(value) : null;
  if (WORK_FLAGS.has(field)) return value ? A.yesWord : A.noWord;
  if (field === "overdue_days") return typeof value === "number" && value > 0 ? A.daysOverdue(value) : null;
  if (field === "severity") return labelFor(T.wf.severity, String(value));
  if (field === "status") return labelFor(T.filters.statuses, String(value));
  if (WORK_SERVER_LABELS.has(field)) return serverLabel(String(value));
  if (field === "sent_by" && typeof value === "object") {
    const v = value as { name?: string | null; designation?: string | null; office_name?: string | null };
    return [v.name, v.designation, v.office_name].filter(Boolean).join(", ") || null;
  }
  if (field === "assigned_to" && typeof value === "object") {
    const v = value as { unit?: string | null; officer?: string | null };
    return [v.unit, v.officer].filter(Boolean).join(" · ") || null;
  }
  if (field === "next_hearing" && typeof value === "object") {
    const v = value as { date?: string | null; kind?: string | null };
    if (!v.date) return null;
    return v.kind === "around" ? A.around(formatDate(v.date)) : formatDate(v.date);
  }
  return String(value);
}

/** The question an answer replies to. */
export function questionOf(messages: AssistantMessage[], answer: AssistantMessage): AssistantMessage | undefined {
  return messages.find((m) => m.id === answer.reply_to_id);
}

export interface MarkerSegment {
  text: string;
  /** the source label (`S2`) when this piece is a marker */
  label?: string;
}

/** A local-model answer split at its `[S#]` markers, so each marker can link to its source (decision 14). */
export function markers(content: string): MarkerSegment[] {
  const out: MarkerSegment[] = [];
  const re = /\[(S\d+)\]/g;
  let last = 0;
  for (let m = re.exec(content); m; m = re.exec(content)) {
    if (m.index > last) out.push({ text: content.slice(last, m.index) });
    out.push({ text: m[0], label: m[1] });
    last = m.index + m[0].length;
  }
  if (last < content.length) out.push({ text: content.slice(last) });
  return out;
}

/** The element id of a source of an answer, for its marker's link. */
export function sourceId(messageId: string, label: string | null | undefined, n: number): string {
  return `src-${messageId}-${label ?? n}`;
}

export interface SourceGroups<T> {
  court: T[];
  internal: T[];
  /** a local model's sources given but not cited */
  uncited: T[];
}

/** Decision 8: cited sources grouped Court Record and Internal Records; the uncited ones apart. */
export function groupSources<T extends { c: AssistantCitation }>(items: T[]): SourceGroups<T> {
  const cited = items.filter((x) => x.c.cited !== false);
  return {
    court: cited.filter((x) => !isInternal(x.c)),
    internal: cited.filter((x) => isInternal(x.c)),
    uncited: items.filter((x) => x.c.cited === false),
  };
}

const NARROW = ["private_to_office", "case_scope", "counsel_shared"] as const;

/** Decision 10: the narrowest visibility among the cited internal records (null when none is cited). */
export function narrowestVisibility(m: AssistantMessage): string | null {
  const seen = new Set(
    m.citations
      .filter((c) => c.available && c.cited !== false && isInternal(c) && c.visibility)
      .map((c) => c.visibility as string),
  );
  return NARROW.find((v) => seen.has(v)) ?? null;
}

/** Whether a stored conversation was switched on before a message (the "included from here" mark, decision 14). */
export function switchedBefore(includedAt: string | null | undefined, createdAt: string): boolean {
  return !!includedAt && new Date(createdAt).getTime() >= new Date(includedAt).getTime();
}
