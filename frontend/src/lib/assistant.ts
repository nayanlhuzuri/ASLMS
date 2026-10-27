/**
 * The Case Assistant's pure helpers (design assistant, decision 14): the excerpts' `[[ ]]` highlights, where a source
 * opens, the words of a source, the "Copy to note" text and the hourly allowance. Nothing here calls the API.
 * Design assistant-ollama (decisions 8, 10 and 14): the source kinds in words, the `[S#]` markers of a local-model
 * answer, the Court Record / Internal Records groups with the uncited sources apart, and the narrowest visibility of
 * the cited internal records for Copy to note.
 */
import type { AssistantCitation, AssistantMessage, AssistantScope, AssistantStatus } from "./api/types";
import { INLINE_PDF } from "./documents";
import { formatDate } from "./format";
import { T } from "./messages";

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

const KINDS: Record<string, string> = T.assistant.kinds;

function kindWord(kind: string): string {
  return KINDS[kind] ?? kind;
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
 * model's answer only the cited sources. */
export function noteText(m: AssistantMessage): string {
  const refs = m.citations
    .filter((c) => c.available && c.cited !== false)
    .map((c, i) => {
      const where = c.case.case_no_text ? ` (${c.case.case_no_text})` : "";
      const passage = plainPassage(c.passage);
      return T.assistant.copyRef(i + 1, `${sourceWords(c)}${where}${passage ? `: “${passage}”` : ""}`);
    });
  return [m.content ?? "", refs.length ? `\n${T.assistant.copyIntro}` : "", ...refs].filter((x) => x !== "").join("\n");
}

/** The questions left this hour (never below 0). */
export function questionsLeft(status: AssistantStatus | undefined): number | null {
  if (!status) return null;
  return Math.max(0, status.limits.questions_per_hour - status.limits.used_last_hour);
}

/** The scopes of a screen: the case tab adds This case (owner, 23 Oct 2026). */
export function scopesFor(screen: "case" | "page"): AssistantScope[] {
  return screen === "case" ? ["case", "my_cases", "research"] : ["my_cases", "research"];
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
