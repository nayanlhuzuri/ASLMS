"use client";

/**
 * The Ownership cell of a cause-list row (design portal-causelist, decision 6): the owner of a claimed case ("Claimed by
 * EDU", with "Your department" when one of the caller's departments holds it), the recommendations the caller is shown
 * ("Strong · EDU · 0.95"), or "Unclaimed" for a case in the pool. Everything comes from the API; nothing is computed.
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
        <span title={names[owner]}>
          <Badge tone="success">{T.causelist.claimedBy(owner)}</Badge>
        </span>
      ) : null}
      {entry.held_by_you ? (
        <Badge tone="success">
          {entry.held_by_you === "watcher" ? T.causelist.yourDepartmentWatching : T.causelist.yourDepartment}
        </Badge>
      ) : null}
      {entry.recommendations.map((r) => (
        <span key={r.office_code} title={names[r.office_code]}>
          <Badge tone={r.band === "high" ? "warning" : undefined}>{recommendationText(r)}</Badge>
        </span>
      ))}
      {!owner && entry.in_pool ? <Badge>{T.causelist.unclaimed}</Badge> : null}
    </div>
  );
}
