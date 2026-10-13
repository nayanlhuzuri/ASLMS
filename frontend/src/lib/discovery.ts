/**
 * Helpers of department discovery (design department-discovery, decision 1; owner's decisions of 14 Oct 2026). A plain
 * module, so a unit test may import it. Every check here is a convenience: the API checks again and decides.
 */

/** The server's `normalise_term`: upper case, dots as spaces, white space collapsed. */
export function normaliseTerm(value: string): string {
  return value.toUpperCase().replace(/\./g, " ").split(/\s+/).filter(Boolean).join(" ");
}

/** The server's `TERM_RE`: 3 to 200 letters, digits, spaces and . , ' & ( ) / - (after normalising). */
export const TERM_PATTERN = /^[A-Z0-9 .,'&()/-]{3,200}$/;

/** Whether a rule's text may be searched at the court: never a regular expression. */
export function isDiscoverable(text: string, kind?: string | null): boolean {
  if (kind === "regex") return false;
  return TERM_PATTERN.test(normaliseTerm(text));
}

/**
 * The years typed on the Court search tab: `2010`, `2010, 2012` or `2010-2014` (and mixes), newest first, without
 * repeats. Returns null when a part is not a year from 1950 to `thisYear` or more than 30 years are asked.
 */
export function parseYears(value: string, thisYear: number): number[] | null {
  const out = new Set<number>();
  const parts = value
    .split(/[,\s]+/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length === 0) return null;
  for (const part of parts) {
    const range = /^(\d{4})\s*-\s*(\d{4})$/.exec(part);
    if (range) {
      const a = Number(range[1]);
      const b = Number(range[2]);
      const [lo, hi] = a <= b ? [a, b] : [b, a];
      for (let y = lo; y <= hi; y++) out.add(y);
    } else if (/^\d{4}$/.test(part)) {
      out.add(Number(part));
    } else {
      return null;
    }
  }
  const years = [...out].sort((a, b) => b - a);
  if (years.length > 30 || years.some((y) => y < 1950 || y > thisYear)) return null;
  return years;
}
