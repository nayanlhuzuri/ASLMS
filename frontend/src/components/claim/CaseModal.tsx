"use client";

/**
 * The case details modal of Case claim (design portal-ui-redesign, decision 7): a large modal (1040 px, up to 86% of
 * the window height, full screen on phones) whose address is in the query string (`?case=<ref in dash form>`), so Back
 * closes it and a link reopens it.
 *
 * Header: the origin line ("Suggested for your department · cause list of 21 Oct", "Suggested by FIN: <reason>", the
 * court search, the pool, or the transfer), the case number and parties, the match badge from the API's `band`, Close,
 * and four facts (Next hearing, Status, Filed, Owner). Tabs, each loaded when first opened: Parties & advocates,
 * Hearings & listings, Orders (collapsible rows with the PDF inline), Linked cases (visible ones open the case page in a
 * new tab) and Case details (identity and classification). Beside them, "Why this is suggested". The footer holds the
 * actions the server allows (`ModalActions`). A case the caller cannot open (404) shows only the row's own facts, with
 * "The full case opens after you accept." Nothing here decides visibility: every read is the API's.
 */
import { useQuery } from "@tanstack/react-query";
import { useState, type KeyboardEvent } from "react";

import { IdentityDetails } from "@/components/case/Details";
import { Hearings } from "@/components/case/Hearings";
import { Parties } from "@/components/case/Parties";
import { Badge, CaseLink, cx, EmptyState, ErrorBanner, KvList, Loading, Modal, ScoreBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { caseKey, useMe, useOwnership } from "@/lib/api/hooks";
import type { CaseDetail, CaseSummary, LinkList, OwnershipActions, PoolCase, Recommendation, Transfer } from "@/lib/api/types";
import { canIn } from "@/lib/can";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import type { ClaimTab } from "@/lib/routes";

import s from "./claim.module.css";
import { ModalActions, type ActionKind } from "./ModalActions";
import { OrderRows } from "./OrderRow";
import { WhyBox } from "./WhyBox";

/** The row the modal was opened from (absent when the address was opened directly). */
export type RowContext =
  | { kind: "recommended"; rec: Recommendation }
  | { kind: "pool"; item: PoolCase }
  | { kind: "transfer"; transfer: Transfer };

const TABS = ["parties", "hearings", "orders", "links", "details"] as const;
type ModalTab = (typeof TABS)[number];

const TAB_LABELS: Record<ModalTab, string> = {
  parties: T.claim.tabParties,
  hearings: T.claim.tabHearings,
  orders: T.claim.tabOrders,
  links: T.claim.tabLinks,
  details: T.claim.tabDetails,
};

function summaryOf(row: RowContext | null | undefined): CaseSummary | null {
  if (!row) return null;
  return row.kind === "recommended" ? row.rec.case : row.kind === "pool" ? row.item.case : row.transfer.case;
}

function ModalLinks({ caseRef }: { caseRef: string }) {
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "links"],
    queryFn: () => api<LinkList>(`${apiCasePath(caseRef)}/links`),
  });
  if (list.isPending) return <Loading />;
  if (list.error) return <ErrorBanner error={list.error} onRetry={() => list.refetch()} />;
  if (list.data.items.length === 0) return <EmptyState>{T.case.noLinks}</EmptyState>;
  return (
    <ul className={s.links}>
      {list.data.items.map((l, i) => (
        <li key={i}>
          <span className="muted">{l.kind} · </span>
          {l.case ? (
            <>
              <CaseLink value={l.case} visible={l.visible} newTab />
              {l.visible ? <span className="visually-hidden"> {T.claim.newTab}</span> : null}
            </>
          ) : (
            <span className="mono">{l.case_no_text ?? l.filing_number_text ?? "—"}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function ModalTabs({ caseRef }: { caseRef: string }) {
  const [active, setActive] = useState<ModalTab>("parties");
  const [opened, setOpened] = useState<Set<ModalTab>>(() => new Set(["parties"]));
  const select = (t: ModalTab) => {
    setActive(t);
    setOpened((prev) => (prev.has(t) ? prev : new Set([...prev, t])));
  };
  function onKey(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = TABS[(index + delta + TABS.length) % TABS.length]!;
    select(next);
    document.getElementById(`claim-tab-${next}`)?.focus();
  }
  return (
    <div>
      <div role="tablist" aria-label={T.claim.modalTabs} className={s.tablist}>
        {TABS.map((t, i) => (
          <button
            key={t}
            id={`claim-tab-${t}`}
            type="button"
            role="tab"
            className={s.tab}
            aria-selected={active === t}
            aria-controls={`claim-panel-${t}`}
            tabIndex={active === t ? 0 : -1}
            onClick={() => select(t)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>
      {TABS.filter((t) => opened.has(t)).map((t) => (
        <div key={t} id={`claim-panel-${t}`} role="tabpanel" aria-labelledby={`claim-tab-${t}`} hidden={active !== t}>
          {t === "parties" ? <Parties caseRef={caseRef} /> : null}
          {t === "hearings" ? <Hearings caseRef={caseRef} /> : null}
          {t === "orders" ? <OrderRows caseRef={caseRef} /> : null}
          {t === "links" ? <ModalLinks caseRef={caseRef} /> : null}
          {t === "details" ? <IdentityDetails caseRef={caseRef} /> : null}
        </div>
      ))}
    </div>
  );
}

export function CaseModal({
  open = true,
  caseRef,
  tab,
  department,
  row,
  outgoing = false,
  onClose,
  onDone,
}: {
  /** False while the modal eases out after closing (it stays mounted for the exit, inert). */
  open?: boolean;
  caseRef: string;
  tab: ClaimTab;
  department: string | null;
  row?: RowContext | null;
  /** Transfers "From us": the footer offers Withdraw. */
  outgoing?: boolean;
  onClose: () => void;
  onDone: (kind: ActionKind, label: string, department: string | null) => void;
}) {
  const me = useMe();
  const detail = useQuery({
    queryKey: [...caseKey(caseRef), "overview"],
    queryFn: () => api<CaseDetail>(apiCasePath(caseRef)),
  });
  const notVisible = detail.error instanceof ApiError && detail.error.status === 404;
  const ownership = useOwnership(caseRef, detail.isSuccess);
  const view = ownership.data;
  const c = detail.data;
  const rec: Recommendation | null =
    row?.kind === "recommended"
      ? row.rec
      : tab === "recommended"
        ? (view?.recommendations.find((r) => r.office_code === department && r.status === "recommended") ?? null)
        : null;
  const pool = row?.kind === "pool" ? row.item : null;
  const transfer: Transfer | null =
    tab === "transfers" ? (view?.open_transfer ?? (row?.kind === "transfer" ? row.transfer : null)) : null;
  const rowTransfer = row?.kind === "transfer" ? row.transfer : null;
  // the row's summary, else the one the server's recommendation or transfer carries (an address opened directly)
  const summary = summaryOf(row) ?? rec?.case ?? transfer?.case ?? null;
  const label = c?.identity.case_no_text || summary?.case_no_text || c?.ref_no || summary?.ref_no || caseRef;
  const petitioner = c?.parties_as_printed.petitioner_summary ?? summary?.petitioner_summary ?? null;
  const respondent = c?.parties_as_printed.respondent_summary ?? summary?.respondent_summary ?? null;

  let origin: string;
  if (tab === "transfers") origin = T.claim.transferFrom(transfer?.from_office_code ?? rowTransfer?.from_office_code ?? null);
  else if (tab === "pool") origin = T.claim.inPool;
  else if (rec?.origin === "suggestion" && rec.suggested_by_office_code) origin = T.claim.suggestedBy(rec.suggested_by_office_code, rec.reason);
  else if (rec?.origin === "discovery") origin = T.claim.discovered;
  else origin = T.claim.suggestedFor(summary?.last_listing ? formatDate(summary.last_listing.list_date) : null);

  const next = c?.status.next_hearing_date ?? summary?.next_hearing_date ?? null;
  const last = summary?.last_listing ?? null;
  const at = last && last.list_date === next ? last : null;
  const status = c?.status.status ?? summary?.status ?? null;
  const owner =
    view?.primary?.office_code ?? c?.ownership.primary?.office_code ?? rec?.current_owner_code ?? (notVisible ? (rowTransfer?.from_office_code ?? null) : null);
  const ownerText = !owner
    ? T.claim.notClaimed
    : tab !== "transfers" && owner !== department
      ? T.claim.ownedWatcher(owner)
      : T.claim.ownedBy(owner);

  // a 404 transfer row: the API decides on the call; the footer offers what the row allows
  const fallbackActions: OwnershipActions | null =
    notVisible && rowTransfer && rowTransfer.status === "requested" && canIn(me.data, department, "cases.transfer_decide")
      ? ({ decide_transfer: true } as OwnershipActions)
      : null;
  const actions = view?.actions ?? fallbackActions;
  const transferId = tab === "transfers" ? (transfer?.status === "requested" ? transfer.id : null) : null;

  const why = tab !== "transfers" || !!rec;
  const header = (
    <div>
      <p className={s.origin}>{origin}</p>
      {petitioner || respondent ? (
        <p className={s.parties}>
          {petitioner ?? "—"} <span className="muted">{T.vs}</span> {respondent ?? "—"}
        </p>
      ) : null}
      {rec ? <ScoreBadge score={rec.score} band={rec.band} /> : null}
      <dl className={s.facts}>
        <div>
          <dt>{T.claim.factNext}</dt>
          <dd>{next ? T.claim.nextAt(formatDate(next), at?.court_no ?? null, at ? at.sr_no : null) : "—"}</dd>
        </div>
        <div>
          <dt>{T.claim.factStatus}</dt>
          <dd>{status ? <Badge tone={status === "disposed" ? "success" : undefined}>{T.inbox.statuses[status] ?? status}</Badge> : "—"}</dd>
        </div>
        <div>
          <dt>{T.claim.factFiled}</dt>
          <dd>{c?.identity.filing_date ? formatDate(c.identity.filing_date) : "—"}</dd>
        </div>
        <div>
          <dt>{T.claim.factOwner}</dt>
          <dd>{ownerText}</dd>
        </div>
      </dl>
    </div>
  );

  const footer = (
    <ModalActions
      caseRef={caseRef}
      department={department}
      actions={actions}
      transferId={tab === "transfers" ? (transferId ?? (fallbackActions ? rowTransfer!.id : null)) : null}
      outgoing={outgoing}
      currentOwner={tab === "transfers" ? null : owner}
      onClose={onClose}
      onDone={(kind, dept) => onDone(kind, label, dept)}
    />
  );

  return (
    <Modal open={open} title={<span className="cno">{label}</span>} onClose={onClose} header={header} footer={footer}>
      {detail.isPending ? <Loading /> : null}
      {notVisible ? (
        <div className="stack">
          {rowTransfer ? (
            <KvList
              items={[
                [T.claim.fromDepartment, rowTransfer.from_office_code ?? "—"],
                [T.claim.reason, rowTransfer.reason ?? "—"],
                [T.claim.requested, T.inbox.requested(rowTransfer.requested_by?.full_name ?? "—", formatDateTime(rowTransfer.requested_at))],
              ]}
            />
          ) : null}
          <p>{T.claim.afterAccept}</p>
        </div>
      ) : detail.error ? (
        <ErrorBanner error={detail.error} onRetry={() => detail.refetch()} />
      ) : c ? (
        <div className={cx(s.layout, !why && s.single)}>
          <ModalTabs caseRef={caseRef} />
          {why ? <WhyBox rec={rec} pool={pool} showRule={tab !== "transfers"} /> : null}
        </div>
      ) : null}
    </Modal>
  );
}
