/**
 * The portal's date helpers join a date's parts with no-break spaces (design portal-ui-kit-fixes, decision 3).
 * `nb("Due 20 Oct 2026, 11:00")` gives the same text with U+00A0 inside each day-month-year date and each month-year,
 * so a test can compare exact strings with the helpers' output.
 */
const MONTH = "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)";
const MONTH_LONG = "(?:January|February|March|April|May|June|July|August|September|October|November|December)";

export const NBSP = " ";

export function nb(text: string): string {
  return text
    .replace(new RegExp(`\\b(\\d{1,2}) (${MONTH}) (\\d{4})\\b`, "g"), `$1${NBSP}$2${NBSP}$3`)
    .replace(new RegExp(`\\b(${MONTH_LONG}) (\\d{4})\\b`, "g"), `$1${NBSP}$2`)
    .replace(new RegExp(`\\b(${MONTH}) (\\d{1,2}), (\\d{4})\\b`, "g"), `$1${NBSP}$2,${NBSP}$3`);
}
