"use client";

/**
 * The Ownership cell of a cause-list row (design portal-causelist, decision 6): the owner of a claimed case ("Claimed by
 * EDU", with "Your department" when one of the caller's departments holds it), the recommendations the caller is shown
 * ("Strong · EDU · 0.95"), or "Unclaimed" for a case in the pool. Everything comes from the API; nothing is computed.
 * The department is shown by name with its code as the tooltip (design portal-names-and-labels, decision 6), and a
 * badge that names one wraps at word boundaries, so a long name never pushes the entries table past the page
 * (deviation 9).
 */
import { Badge } from "@/components/ui";
import type { CauselistEntry } from "@/lib/api/types";
import { recommendationText } from "@/lib/causelist";
import { T } from "@/lib/messages";

import s from "./causelist.module.css";

export function OwnershipCell({ entry, names }: { entry: CauselistEntry; names: Record<string, string> }) {
  const owner = entry.owner_office_code;
  return (
    <div className={s.badges}>
      {owner ? (
        <Badge tone="success" title={owner} wrap>
          {T.causelist.claimedBy(names[owner] ?? owner)}
        </Badge>
      ) : null}
      {entry.held_by_you ? (
        <Badge tone="success">
          {entry.held_by_you === "watcher" ? T.causelist.yourDepartmentWatching : T.causelist.yourDepartment}
        </Badge>
      ) : null}
      {entry.recommendations.map((r) => (
        <Badge key={r.office_code} tone={r.band === "high" ? "warning" : undefined} title={r.office_code} wrap>
          {recommendationText(r, names)}
        </Badge>
      ))}
      {!owner && entry.in_pool ? <Badge>{T.causelist.unclaimed}</Badge> : null}
    </div>
  );
}
