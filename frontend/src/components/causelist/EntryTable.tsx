"use client";

/**
 * The day's entries in court order (design portal-causelist, decisions 3, 6, 7 and 11): a heading row where the court,
 * the bench, the list or the section changes (`<th scope="colgroup">`), then each entry. On the Work list template
 * (design portal-ui-redesign, decision 26): court and item in the fixed leading column (connected matters show "with
 * …" above the case and no item number of their own), the case (linked only when the caller can open it; the CNR
 * beneath, "provisional" without one) with its parties, the ownership, and Claim when the API says `claimable`. Rows
 * become cards on phones; a row opens the whole entry (advocates and counsel codes as printed, remarks) in a side
 * panel.
 */
import Link from "next/link";
import { Fragment, useState, type KeyboardEvent, type MouseEvent } from "react";

import { Chevron } from "@/components/inbox/rows";
import { Button, buttonClass, CaseLink, KvList, Lead, SidePanel } from "@/components/ui";
import type { CauselistEntry } from "@/lib/api/types";
import { headingsOf } from "@/lib/causelist";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";

import { OwnershipCell } from "./OwnershipCell";
import s from "./causelist.module.css";

const COLUMNS = 5;

const TEXTS = {
  court: T.causelist.courtHeading,
  bench: (label: string | null, benchId: number | null) =>
    label ?? (benchId !== null ? T.causelist.benchNumber(benchId) : T.causelist.courtWide),
  list: (listType: string) => T.causelist.listTypes[listType] ?? listType,
};

function caseNo(e: CauselistEntry): string {
  return e.case_no_text ?? e.case?.case_no_text ?? e.case?.ref_no ?? "—";
}

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

function Parties({ e }: { e: CauselistEntry }) {
  return (
    <div className={s.parties}>
      {e.petitioner_text ?? "—"} <span className="muted">{T.causelist.versus}</span> {e.respondent_text ?? "—"}
    </div>
  );
}

function EntryPanel({
  entry,
  names,
  onClose,
  onClaim,
}: {
  entry: CauselistEntry | null;
  names: Record<string, string>;
  onClose: () => void;
  onClaim: (ref: string) => void;
}) {
  const e = entry;
  const claim = e?.claimable && e.case ? e.case.ref_no : null;
  return (
    <SidePanel
      open={e !== null}
      title={e ? caseNo(e) : T.causelist.details}
      onClose={onClose}
      footer={
        e && (claim || (e.case && e.visible)) ? (
          <>
            {claim ? (
              <Button
                variant="secondary"
                onClick={() => {
                  onClose();
                  onClaim(claim);
                }}
              >
                {T.own.claim}
              </Button>
            ) : null}
            {e.case && e.visible ? (
              <Link href={casePath(e.case.ref_no)} className={buttonClass("primary")} data-variant="primary">
                {T.causelist.openCase}
              </Link>
            ) : null}
          </>
        ) : null
      }
    >
      {e ? (
        <KvList
          items={[
            [T.causelist.court, e.court_no],
            [T.causelist.benchLabel, TEXTS.bench(e.bench_label, e.bench_id)],
            [T.causelist.listType, TEXTS.list(e.list_type)],
            [T.causelist.section, e.section],
            [T.causelist.item, e.is_connected ? (e.with_text ?? T.causelist.connectedFallback) : e.printed_sr_no],
            [T.causelist.case, <CaseCell key="c" e={e} />],
            [T.causelist.parties, <Parties key="p" e={e} />],
            [
              T.causelist.advocates,
              <div key="a" className={s.pre}>
                <div>{e.pet_advocate_text ?? "—"}</div>
                <div>{e.res_advocate_text ?? "—"}</div>
              </div>,
            ],
            [T.causelist.codes, e.counsel_codes.length > 0 ? <span className="mono">{e.counsel_codes.join("; ")}</span> : null],
            [T.causelist.ownership, <OwnershipCell key="o" entry={e} names={names} />],
            [T.causelist.remarks, e.remarks],
          ]}
        />
      ) : null}
    </SidePanel>
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
  const [openId, setOpenId] = useState<string | null>(null);
  const open = items.find((e) => e.id === openId) ?? null;

  function onRowClick(ev: MouseEvent<HTMLTableRowElement>, id: string) {
    // a link or a button inside the row does its own job, not the row's
    const inner = (ev.target as HTMLElement).closest?.("a, button");
    if (inner && ev.currentTarget.contains(inner)) return;
    setOpenId(id);
  }

  function onRowKey(ev: KeyboardEvent<HTMLTableRowElement>, id: string) {
    if (ev.key === "Enter" && ev.target === ev.currentTarget) {
      ev.preventDefault();
      setOpenId(id);
    }
  }

  return (
    <>
      <div className={s.entriesWrap}>
        <table className={s.entries}>
          <caption>{T.causelist.table}</caption>
          <thead>
            <tr>
              <th scope="col" className={s.leadCol}>
                {T.causelist.courtItem}
              </th>
              <th scope="col">{T.causelist.case}</th>
              <th scope="col">{T.causelist.ownership}</th>
              <th scope="col">{T.causelist.action}</th>
              <th scope="col" className={s.hideOnPhone}>
                <span className="visually-hidden">{T.causelist.details}</span>
              </th>
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
                <tr
                  className={s.entry}
                  tabIndex={0}
                  aria-label={T.causelist.openEntry(caseNo(e))}
                  onClick={(ev) => onRowClick(ev, e.id)}
                  onKeyDown={(ev) => onRowKey(ev, e.id)}
                >
                  <td className={s.leadCol}>
                    <Lead>
                      <span className={s.courtItem}>
                        {T.causelist.courtItemText(e.court_no, e.is_connected ? null : e.printed_sr_no)}
                      </span>
                    </Lead>
                  </td>
                  <td>
                    {e.is_connected ? <div className={s.connected}>{e.with_text ?? T.causelist.connectedFallback}</div> : null}
                    <CaseCell e={e} />
                    <Parties e={e} />
                  </td>
                  <td data-label={T.causelist.ownership}>
                    <OwnershipCell entry={e} names={names} />
                  </td>
                  <td data-label={T.causelist.action}>
                    {e.claimable && e.case ? (
                      <Button variant="secondary" onClick={() => onClaim(e.case!.ref_no)}>
                        {T.own.claim}
                      </Button>
                    ) : null}
                  </td>
                  <td className={s.hideOnPhone}>
                    <Chevron />
                  </td>
                </tr>
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <EntryPanel entry={open} names={names} onClose={() => setOpenId(null)} onClaim={onClaim} />
    </>
  );
}
