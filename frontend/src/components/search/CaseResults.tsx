"use client";

/**
 * Rows of `/cases`, `/cases/search` and the court search (design portal-cases, decisions 2 and 9): a visible case
 * links to its page; any other shows the court-public summary, the owning department and "in the unclaimed pool",
 * with Claim when `claimable`. Claim opens the dialog without departments: it reads `GET /cases/{ref}/ownership` and
 * offers its `claim_departments` (design portal-cases-followups, decision 7; nothing is computed in the portal).
 */
import { useState, type ReactNode } from "react";

import { Button, CaseLink, Table } from "@/components/ui";
import { ClaimDialog } from "@/components/inbox/dialogs";
import { ListingLine, PartiesLine } from "@/components/inbox/common";
import type { CaseSearchItem } from "@/lib/api/types";
import { T } from "@/lib/messages";

export function CaseResults({
  items,
  caption,
  extra,
}: {
  items: CaseSearchItem[];
  caption: string;
  extra?: (item: CaseSearchItem) => ReactNode;
}) {
  const [claiming, setClaiming] = useState<string | null>(null);
  return (
    <>
      <Table caption={caption}>
        <thead>
          <tr>
            <th scope="col">{T.inbox.case}</th>
            <th scope="col">{T.inbox.status}</th>
            <th scope="col">{T.inbox.actions}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.case.id}>
              <td>
                <PartiesLine c={it.case} />
                <CaseLink value={it.case} visible={it.visible} />
                {it.case.cnr && it.case.case_no_text ? <span className="mono muted"> · {it.case.cnr}</span> : null}
                <ListingLine c={it.case} />
              </td>
              <td>
                <div>{T.inbox.statuses[it.case.status] ?? it.case.status}</div>
                {it.owner_office_code ? <div className="muted">{T.search.owner(it.owner_office_code)}</div> : null}
                {it.in_pool ? <div className="muted">{T.search.inPool}</div> : null}
                {!it.visible ? <div className="muted">{T.search.notVisible}</div> : null}
                {it.dossier_status !== "fetched" ? <div className="muted">{T.search.notFetched}</div> : null}
              </td>
              <td>
                <div className="row">
                  {it.claimable ? <Button onClick={() => setClaiming(it.case.ref_no)}>{T.own.claim}</Button> : null}
                  {extra ? extra(it) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {claiming ? (
        <ClaimDialog open caseRef={claiming} onClose={() => setClaiming(null)} />
      ) : null}
    </>
  );
}
