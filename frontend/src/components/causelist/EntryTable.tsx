"use client";

/**
 * The day's entries in court order (design portal-causelist, decisions 3, 6, 7 and 11): a heading row where the court,
 * the bench, the list or the section changes (`<th scope="colgroup">`), then each entry. On the Work list template
 * (design portal-ui-redesign, decision 26): court and item in the fixed leading column (connected matters show "with
 * …" above the case and no item number of their own), the case (linked only when the caller can open it; the CNR
 * beneath, "provisional" without one) with its parties, the ownership, and Claim when the API says `claimable`. Rows
 * become cards on phones; a row opens the whole entry (advocates and counsel codes as printed, remarks) in a side
 * panel.
 *
 * Each list heading row carries the court's original PDF of that list (design causelist-pdf-access, decision 4): View
 * PDF (inline, new tab, `documents.view`) and Download PDF (`documents.download`), or the muted "not available" / "not
 * fetched yet" text, read from the day already loaded (`lists`, by list id); a list not in the day shows nothing.
 */
import Link from "next/link";
import { Fragment, useState, type KeyboardEvent, type MouseEvent } from "react";

import { Chevron } from "@/components/inbox/rows";
import { Button, buttonClass, CaseLink, KvList, Lead, SidePanel } from "@/components/ui";
import type { Causelist, CauselistEntry } from "@/lib/api/types";
import { headingsOf } from "@/lib/causelist";
import { canViewInline } from "@/lib/documents";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";

import { listFileUrl } from "./ListStrip";
import { OwnershipCell } from "./OwnershipCell";
import s from "./causelist.module.css";

const COLUMNS = 5;

const TEXTS = {
  court: T.causelist.courtHeading,
  bench: (label: string | null, benchId: number | null) =>
    label ?? (benchId !== null ? T.causelist.benchNumber(benchId) : T.causelist.courtWide),
  list: (listType: string) => T.causelist.listTypes[listType] ?? listType,
};

export function caseNo(e: CauselistEntry): string {
  return e.case_no_text ?? e.case?.case_no_text ?? e.case?.ref_no ?? "—";
}

export function CaseCell({ e }: { e: CauselistEntry }) {
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

export function Parties({ e }: { e: CauselistEntry }) {
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

/** View PDF and Download PDF of one list on its heading row (design causelist-pdf-access, decision 4). */
function ListPdfLinks({
  list,
  name,
  bench,
  canView,
  canDownload,
}: {
  list: Causelist;
  name: string;
  bench: string;
  canView: boolean;
  canDownload: boolean;
}) {
  if (!list.has_pdf) {
    return <span className={s.headingNote}>{list.fetch_status === "pending" ? T.causelist.pdfPending : T.causelist.noPdf}</span>;
  }
  const view = canView && canViewInline("application/pdf");
  if (!view && !canDownload) return null;
  return (
    <span className={s.headingLinks}>
      {view ? (
        <a
          className={buttonClass("secondary", "sm")}
          href={listFileUrl(list.id, "inline")}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={T.causelist.viewPdfOf(name, bench)}
        >
          {T.causelist.viewPdf}
        </a>
      ) : null}
      {canDownload ? (
        <a className={buttonClass("secondary", "sm")} href={listFileUrl(list.id, "attachment")} download aria-label={T.causelist.downloadPdfOf(name, bench)}>
          {T.causelist.downloadPdf}
        </a>
      ) : null}
    </span>
  );
}

export function EntryTable({
  items,
  names,
  onClaim,
  lists = {},
  canView = false,
  canDownload = false,
}: {
  items: CauselistEntry[];
  names: Record<string, string>;
  onClaim: (ref: string) => void;
  /** The day's lists by id, for the PDF links on each list heading. */
  lists?: Record<string, Causelist>;
  canView?: boolean;
  canDownload?: boolean;
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
                {heads[i]!.map((h, j) => {
                  const list = h.kind === "list" ? lists[e.causelist_id] : undefined;
                  return (
                    <tr key={`${e.id}-h${j}`} className={`${s.heading} ${s[`heading-${h.kind}`] ?? ""}`}>
                      <th scope="colgroup" colSpan={COLUMNS}>
                        {list ? (
                          <span className={s.headingRow}>
                            <span data-heading-text="">{h.text}</span>
                            <ListPdfLinks
                              list={list}
                              name={h.text}
                              bench={`${T.causelist.courtHeading(e.court_no?.trim() || null)} · ${TEXTS.bench(e.bench_label, e.bench_id)}`}
                              canView={canView}
                              canDownload={canDownload}
                            />
                          </span>
                        ) : (
                          <span data-heading-text="">{h.text}</span>
                        )}
                      </th>
                    </tr>
                  );
                })}
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
