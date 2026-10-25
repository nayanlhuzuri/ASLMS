/**
 * The Title Case rule of the portal's labels (design portal-ui-polish-2, decisions 1 and 2), the same rule as
 * `backend/aslms/core/titlecase.py`, with the same pinned examples in both test suites.
 *
 * Labels (navigation entries, tabs, buttons, card titles, column headers, field labels, section headings, badges and
 * chips) use Title Case: short joining words stay lower case unless they come first or last in their segment, acronyms
 * stay in capitals, every other word gets a capital first letter and keeps the rest (so a hyphenated word capitalises
 * only its first part: "Sign-in", "Office-only"). Sentences keep sentence case.
 */

export const SMALL_WORDS: ReadonlySet<string> = new Set([
  "a",
  "an",
  "the",
  "and",
  "or",
  "of",
  "by",
  "to",
  "in",
  "on",
  "for",
  "at",
  "with",
]);

/** Lower case to the written form; "apis" keeps its plural s in lower case. */
export const ACRONYMS: Readonly<Record<string, string>> = Object.fromEntries(
  ["ASLMS", "CNR", "NAPIX", "PDF", "API", "APIs", "OTP", "IST", "URL", "ID", "SMS", "CSV", "AI", "JSON", "IP", "NJDG"].map(
    (w) => [w.toLowerCase(), w],
  ),
);

const SEPARATORS = /( · | \/ | — | – |: )/;
const LEADING = "([\"'“‘";
const TRAILING = ")]\"'”’,;.!?";

function caseWord(word: string, first: boolean, last: boolean): string {
  let start = 0;
  while (start < word.length && LEADING.includes(word.charAt(start))) start += 1;
  let end = word.length;
  while (end > start && TRAILING.includes(word.charAt(end - 1))) end -= 1;
  const core = word.slice(start, end);
  if (!core) return word;
  const lower = core.toLowerCase();
  let cased: string;
  if (/\d/.test(core) || /\p{Lu}/u.test(core.slice(1))) cased = core;
  else if (Object.prototype.hasOwnProperty.call(ACRONYMS, lower)) cased = ACRONYMS[lower] ?? core;
  else if (SMALL_WORDS.has(lower) && !first && !last) cased = lower;
  else cased = core.charAt(0).toUpperCase() + core.slice(1);
  return word.slice(0, start) + cased + word.slice(end);
}

function caseSegment(segment: string): string {
  const words = segment.split(" ");
  const filled = words.map((w, i) => (w ? i : -1)).filter((i) => i >= 0);
  if (!filled.length) return segment;
  const first = filled[0];
  const last = filled[filled.length - 1];
  return words.map((w, i) => (w ? caseWord(w, i === first, i === last) : w)).join(" ");
}

/** `text` in Title Case by the rule of decision 2. */
export function titleCase(text: string): string {
  return text
    .split(SEPARATORS)
    .map((part, i) => (i % 2 ? part : caseSegment(part)))
    .join("");
}

export function isTitleCase(text: string): boolean {
  return titleCase(text) === text;
}
