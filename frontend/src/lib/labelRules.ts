/**
 * The rules of the Title Case guard over `T` (design portal-ui-polish-2, decision 4), read by `labels.test.ts`.
 *
 * - **Label paths** must pass `isTitleCase`: `nav.**`, `tabs.**`, `crumbs.**`, `crumbPaths.**`; a last key such as
 *   `title`, `label`, `button` or ending in `Title`, `Label`, `Button`…; a parent key such as `cols`, `fields`,
 *   `badges`, `statuses`.
 * - **Sentence paths** (hints, help, placeholders, descriptions, notes, empty states, messages…) are not checked.
 * - **Everything else** is unclassified: a short string that looks like a label (6 words or fewer, no final
 *   `. ? ! :`, no `{` or `%`) must pass `isTitleCase` unless its path is listed in `SENTENCE_EXCEPTIONS` with a reason.
 * - **Functions** under label paths are called with the arguments in `LABEL_FUNCTIONS` and the result is checked.
 */

export type PathKind = "label" | "sentence" | "unclassified";

const LABEL_ROOTS = ["nav", "tabs", "crumbs", "crumbPaths"];
const LABEL_LAST = /^(title|heading|label|button|tab|badge|chip|column|col|field|section)$/;
const LABEL_SUFFIXES = ["Title", "Heading", "Label", "Button", "Tab", "Badge", "Chip", "Col", "Column", "Field", "Section"];
const LABEL_PARENTS = new Set([
  "cols",
  "columns",
  "fields",
  "buttons",
  "badges",
  "statuses",
  "tabs",
  "headings",
  "labels",
  "titles",
]);
export const SENTENCE_KEY =
  /(hint|help|placeholder|description|desc|note|notice|empty|body|message|error|confirm|intro|subtitle|tooltip|aria|explain|why|detail)/i;
const SENTENCE_START = /^(no|none|nothing)([A-Z0-9_]|$)/;

export function isLabelPath(path: string): boolean {
  const keys = path.split(".");
  if (LABEL_ROOTS.includes(keys[0] ?? "")) return true;
  const last = keys[keys.length - 1] ?? "";
  if (LABEL_LAST.test(last) || LABEL_SUFFIXES.some((s) => last.endsWith(s))) return true;
  return keys.length > 1 && LABEL_PARENTS.has(keys[keys.length - 2] ?? "");
}

export function isSentencePath(path: string): boolean {
  const keys = path.split(".");
  const last = keys[keys.length - 1] ?? "";
  return SENTENCE_KEY.test(last) || SENTENCE_START.test(last);
}

export function classify(path: string): PathKind {
  if (isLabelPath(path)) return "label";
  if (isSentencePath(path)) return "sentence";
  return "unclassified";
}

/** An unclassified string that reads like a label: 6 words or fewer, no final `. ? ! :`, no `{` or `%`. */
export function looksLikeLabel(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed || /[{%]/.test(trimmed) || /[.?!:]$/.test(trimmed)) return false;
  return trimmed.split(/\s+/).length <= 6;
}

/**
 * Unclassified short strings that are sentences or values, not labels (path → one-line reason). A new short string
 * must either be Title Case or declare itself here.
 */
export const SENTENCE_EXCEPTIONS: Record<string, string> = {
  // design list-search: nouns read after a number in a count ("12 of 340 codes"), and order names read after "Order:"
  "mapping.codesNoun": "a noun read after a number in a count",
  "mapping.codesNotMapped": "words read after a number in a count",
  "mapping.rulesNoun": "a noun read after a number in a count",
  "mapping.casesNoun": "a noun read after a number in a count",
  "mapping.namesNoun": "a noun read after a number in a count",
  "inbox.casesNoun": "a noun read after a number in a count",
  "inbox.caseNoun": "a noun read after a number in a count",
  "mapping.codeNoun": "a noun read after a number in a count",
  "mapping.codeNotMapped": "words read after a number in a count",
  "mapping.ruleNoun": "a noun read after a number in a count",
  "mapping.caseNoun": "a noun read after a number in a count",
  "mapping.nameNoun": "a noun read after a number in a count",
  "mapping.codesDefault": "an order name, a column then its direction words, read after Order:",
  "discovery.namesDefault": "an order name, a column then its direction words, read after Order:",
  // design data-collection-redesign: reasons read inside an estimate sentence ("no date, the court connection is off")
  "dc.reasons.connection_off": "a reason read inside the estimate sentence",
  "dc.reasons.paused": "a reason read inside the estimate sentence",
  "dc.notMeasured": "a value read inside a sentence of the estimate inputs",
  "system.kpiSub.median": "a unit under a figure",
  "system.kpiSub.leftUnknown": "a value read in a sentence under a figure",
  "system.ms": "a unit abbreviation, written after a number",
  "system.avgMs": "a column header ending in the unit abbreviation ms",
  "system.testing": "a progress sentence with a unit abbreviation",
  "system.console.sending": "a progress sentence with a unit abbreviation",
  "system.console.source.settings": "a fragment after a field value",
  "system.console.source.held": "a fragment after a field value",
  "system.console.source.typed": "a fragment after a field value",
  "system.console.mandatory": "a fragment after a field name",
  "system.console.optional": "a fragment after a field name",
  "system.console.yourSend": "a fragment inside a history line",
  "system.console.aPerson": "a fragment inside a history line",
  "system.console.background": "a fragment inside a history line",
  "system.console.held": "a fragment inside a sentence",
  "system.console.edited": "a fragment inside a history line",
  "system.console.signatureWords.verified": "a value inside a sentence",
  "system.token.notYet": "a value shown in place of a time",
  "system.token.acceptedNo": "a value sentence in a facts list",
  "system.docs.listed": "a fragment after a count",
  "vs": "the word between two parties",
  "access.on": "a state word inside an accessible description",
  "access.off": "a state word inside an accessible description",
  "offices.outgoingOfficer": "a fragment completing a choice sentence",
  "offices.outgoingEnd": "a fragment completing a choice sentence",
  "mapping.changedMark": "a marker inside parentheses",
  "officePicker.subMarker": "a marker beside an office code",
  "inbox.stayWatcher": "a fragment completing a sentence",
  "causelist.versus": "the word between two parties",
  "causelist.provisional": "a value shown in place of a CNR",
  "causelist.connectedFallback": "a fragment completing a sentence",
  "filters.nouns.cases": "a noun inside a count sentence",
  "filters.nouns.alerts": "a noun inside a count sentence",
  "filters.nouns.files": "a noun inside a count sentence",
  "filters.nouns.transfers": "a noun inside a count sentence",
  "filters.nouns.documents": "a noun inside a count sentence",
  "filters.nouns.items": "a noun inside a count sentence",
  "case.notPublished": "a value inside an order line",
  "case.fetchPending": "a value inside an order line",
  "case.former": "a marker inside parentheses",
  "case.bases.state": "a part of the comma-joined line of access bases",
  "case.bases.owner": "a part of the comma-joined line of access bases",
  "case.bases.recommended": "a part of the comma-joined line of access bases",
  "case.bases.transfer_in": "a part of the comma-joined line of access bases",
  "case.bases.pool": "a part of the comma-joined line of access bases",
  "case.bases.allotted": "a part of the comma-joined line of access bases",
  "case.bases.counsel": "a part of the comma-joined line of access bases",
  "case.responsibleUnit": "a part of the ownership card line (design claim-assign-wording, decision 4)",
  "case.dealingOfficer": "a part of the ownership card line (design claim-assign-wording, decision 4)",
  "discovery.notYetSearched": "a value shown in place of a date",
  "reports.inactive": "a marker after an office name",
  "reports.withFiles": "a fragment completing a sentence",
  "data.notVisible": "a fragment completing a sentence",
  "alerts.unreadHidden": "a visually hidden word after an alert",
  "mycal.counts.hearing.0": "a noun after a count",
  "mycal.counts.hearing.1": "a noun after a count",
  "mycal.counts.action_due.0": "a noun after a count",
  "mycal.counts.action_due.1": "a noun after a count",
  "mycal.counts.confirm.0": "a noun after a count",
  "mycal.counts.confirm.1": "a noun after a count",
  "mycal.overdue": "a marker after a line",
  "wf.currentMark": "a marker inside parentheses",
  "wf.currentMarkShort": "a marker inside parentheses",
  "nd.noun": "a noun inside a count sentence",
  "nd.reading.period": "a fragment after a period of days",
  "assistant.suggested.research.0": "a suggested question typed for the person",
  "assistant.includedHere": "a line marking a point in the conversation (design assistant-ollama, decision 14)",
  "assistant.usesInternal": "a sentence under an answer (design assistant-ollama, decision 14)",
};

/** Functions under label paths, with the sample arguments their result is checked with (path → args). */
export const LABEL_FUNCTIONS: Record<string, unknown[]> = {
  "users.moreFiltersButton": [1],
  "kit.moreButton": [2],
  "nav.count": ["Case Inbox", "3"],
  "score.badge": ["Strong Recommendation", "0.91"],
  "own.decideTitle": [true],
  "causelist.courtHeading": [null],
  "remarks.remarksTab": [3],
  "remarks.notesTab": [null],
  "remarks.sentHeading": ["Under Secretary", "Section Officer"],
  "remarks.recalledHeading": ["Under Secretary"],
  "remarks.otherHeading": ["Hand-over", "Under Secretary", "Section Officer"],
  "system.ringLabel": ["80%"],
  "assistant.courtRecordTitle": ["WP(C) 12/2026"],
  "hearing.badges.inDays": [3],
  "list.showMoreButton": [100],
};
