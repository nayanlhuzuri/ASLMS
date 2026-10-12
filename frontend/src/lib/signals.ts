/**
 * The chip text of a recommendation signal (design portal-cases, decision 5), from the signal's `kind` and `matched`
 * as the matching engine stores them: `Code: SC, EDU`, `Keyword: …`, `Name: …`, `Linked: WP(C)/2417/2026`,
 * `Watchlist`, `Suggested unit: …`. An unknown kind shows its own name and match.
 */
export type Signal = Record<string, unknown>;

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

const LABELS: Record<string, string> = {
  counsel_code: "Code",
  keyword: "Keyword",
  name_pattern: "Name",
  linked_case: "Linked",
  watchlist: "Watchlist",
  suggested_unit: "Suggested unit",
};

export function signalText(signal: Signal): string {
  const kind = text(signal.kind);
  const label = LABELS[kind] ?? (kind ? kind.replace(/_/g, " ") : "Signal");
  if (kind === "watchlist") return label;
  const matched =
    kind === "suggested_unit"
      ? text(signal.office_code) || text(signal.matched)
      : kind === "linked_case"
        ? text(signal.matched) || text(signal.case_no_text) || text(signal.cnr)
        : text(signal.matched);
  return matched ? `${label}: ${matched}` : label;
}
