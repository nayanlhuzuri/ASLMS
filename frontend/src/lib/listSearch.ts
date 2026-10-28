/**
 * The browser side of a list search (design list-search, decisions 3 and 8): `matchesWords` filters the lists the
 * API answers whole (every word must appear in one of the texts the row shows; case and accents ignored), and
 * `searchShown` says when a list draws its search box (more than `LIST_SEARCH_FROM` rows, or a search set).
 */

/** A list shows its search box above this many rows (decision 8). */
export const LIST_SEARCH_FROM = 10;
/** The shortest query sent or applied (decision 6: codes such as "SC" and "GA" are two letters). */
export const LIST_MIN_CHARS = 2;
/** The case lists keep their own minimum (`case_filters.MIN_QUERY`). */
export const CASE_MIN_CHARS = 3;

/** Lower case with accents removed (NFD, combining marks dropped). */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase();
}

/** Whether every word of `query` appears in at least one of `texts`; true for an empty query. */
export function matchesWords(query: string, ...texts: (string | number | null | undefined)[]): boolean {
  const words = fold(query).trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const hay = texts.filter((t) => t !== null && t !== undefined && t !== "").map((t) => fold(String(t)));
  return words.every((w) => hay.some((h) => h.includes(w)));
}

/** Decision 8: the box shows when a search is set, otherwise when the list holds more than 10 rows. */
export function searchShown(rows: number | null | undefined, q: string): boolean {
  return q.trim() !== "" || (rows ?? 0) > LIST_SEARCH_FROM;
}
