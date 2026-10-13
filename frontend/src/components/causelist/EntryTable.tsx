"use client";

/**
 * The day's entries in court order (design portal-causelist, decisions 3, 6, 7 and 11): a heading row where the court,
 * the bench, the list or the section changes (`<th scope="colgroup">`), then Item (connected matters indented with
 * "with …" and no number of their own), Case (linked only when the caller can open it; the CNR beneath, "provisional"
 * without one), Parties, Advocates, Counsel codes as printed, Ownership and Claim when the API says `claimable`.
 */
import { Fragment } from "react";

import { Button, CaseLink, Table } from "@/components/ui";
import type { CauselistEntry } from "@/lib/api/types";
import { headingsOf } from "@/lib/causelist";
import { T } from "@/lib/messages";

import { OwnershipCell } from "./OwnershipCell";
import s from "./causelist.module.css";

const COLUMNS = 7;

const TEXTS = {
  court: T.causelist.courtHeading,
  bench: (label: string | null, benchId: number | null) =>
    label ?? (benchId !== null ? T.causelist.benchNumber(benchId) : T.causelist.courtWide),
  list: (listType: string) => T.causelist.listTypes[listType] ?? listType,
};

function CaseCell({ e }: { e: CauselistEntry }) {
  const cnr = e.cnr ?? e.case?.cnr ?? null;
  return (
    <>
      {e.case ? (
        <CaseLink value={{ ref_no: e.case.ref_no, cnr, case_no_text: e.case_no_text ?? e.case.case_no_text }} visible={e.visible} />
      ) : (
        <span className="mono">{e.case_no_text ?? "—"}</span>
      )}
      <div className="mono muted">{cnr ?? T.causelist.provisional}</div>
    </>
  );
}

export function EntryTable({
  items,
  names,
  onClaim,
}: {
  items: CauselistEntry[];
  names: Record<string, string>;
  onClaim: (ref: string) => void;
}) {
  const heads = headingsOf(items, TEXTS);
  return (
    <Table caption={T.causelist.table}>
      <thead>
        <tr>
          <th scope="col">{T.causelist.item}</th>
          <th scope="col">{T.causelist.case}</th>
          <th scope="col">{T.causelist.parties}</th>
          <th scope="col">{T.causelist.advocates}</th>
          <th scope="col">{T.causelist.codes}</th>
          <th scope="col">{T.causelist.ownership}</th>
          <th scope="col">{T.causelist.action}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((e, i) => (
          <Fragment key={e.id}>
            {heads[i]!.map((h, j) => (
              <tr key={`${e.id}-h${j}`} className={`${s.heading} ${s[`heading-${h.kind}`] ?? ""}`}>
                <th scope="colgroup" colSpan={COLUMNS}>
                  {h.text}
                </th>
              </tr>
            ))}
            <tr>
              <td>
                {e.is_connected ? (
                  <div className={s.connected}>{e.with_text ?? T.causelist.connectedFallback}</div>
                ) : (
                  (e.printed_sr_no ?? "—")
                )}
              </td>
              <td>
                <CaseCell e={e} />
              </td>
              <td>
                <div>{e.petitioner_text ?? "—"}</div>
                <div className="muted">{T.causelist.versus}</div>
                <div>{e.respondent_text ?? "—"}</div>
              </td>
              <td className={s.pre}>
                <div>{e.pet_advocate_text ?? "—"}</div>
                <div>{e.res_advocate_text ?? "—"}</div>
              </td>
              <td className="mono">{e.counsel_codes.join("; ") || "—"}</td>
              <td>
                <OwnershipCell entry={e} names={names} />
              </td>
              <td>
                {e.claimable && e.case ? <Button onClick={() => onClaim(e.case!.ref_no)}>{T.own.claim}</Button> : null}
              </td>
            </tr>
          </Fragment>
        ))}
      </tbody>
    </Table>
  );
}
