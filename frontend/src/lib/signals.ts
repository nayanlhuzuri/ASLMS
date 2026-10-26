/**
 * The chip text of a recommendation signal (design portal-cases, decision 5), from the signal's `kind` and `matched`
 * as the matching engine stores them: `Code: SC, EDU`, `Keyword: …`, `Name: …`, `Linked: WP(C)/2417/2026`,
 * `Watchlist`, `Suggested unit: …`. An unknown kind shows its own name and match. A partial counsel code (design
 * partial-code-match, decision 13) shows the server's `reason`, or `Partial code: <matched> in <printed>` without one.
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
  counsel_code_partial: "Partial code",
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
  if (kind === "counsel_code_partial") {
    const reason = text(signal.reason);
    if (reason) return reason;
    const matched = text(signal.matched);
    const printed = text(signal.printed);
    return matched && printed ? `${label}: ${matched} in ${printed}` : matched ? `${label}: ${matched}` : label;
  }
  const matched =
    kind === "suggested_unit"
      ? text(signal.office_code) || text(signal.matched)
      : kind === "linked_case"
        ? text(signal.matched) || text(signal.case_no_text) || text(signal.cnr)
        : text(signal.matched);
  return matched ? `${label}: ${matched}` : label;
}
