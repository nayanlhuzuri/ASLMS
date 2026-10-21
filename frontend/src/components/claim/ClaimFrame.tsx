"use client";

/**
 * Case claim = suggestions to decide on (design portal-ui-redesign, decisions 6, 7 and 9; plan §5.4 and §4.2):
 * Recommended, Unclaimed pool and Transfers to us, read for one department at a time (`?department=CODE`, sent as
 * `office`; portal-cases decision 4). A tab whose count is `null` in that department's `/inbox/counts` block is not
 * shown (the API's rule). The subtitle keeps the rule's notice: nothing is assigned automatically. A row opens the
 * case details modal, whose address is `?case=<ref in dash form>` (Back closes it, a link reopens it; closing goes back
 * when this page opened it, else replaces the address: `useUrlOverlay`, design portal-ui-polish, decision 10). After an action
 * the modal closes, a notice names the action with "Open case page", and the lists, counts and case are read again.
 */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { DepartmentSelect, useInboxSelection } from "@/components/inbox/selection";
import { DURATION, EmptyState, ErrorBanner, Loading, Notice, PageHeader, Tabs } from "@/components/ui";
import type { InboxCounts } from "@/lib/api/types";
import { departmentsOf } from "@/lib/can";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { casePath, refPath } from "@/lib/refs";
import { CLAIM_TABS, type ClaimTab } from "@/lib/routes";
import { useUrlOverlay } from "@/lib/useUrlOverlay";

import s from "../inbox/inbox.module.css";
import { CaseModal, type RowContext } from "./CaseModal";
import type { ActionKind } from "./ModalActions";
import { Pool } from "./Pool";
import { Recommended } from "./Recommended";
import { Transfers } from "./Transfers";

/** The tabs a counts block allows, in order. */
export function claimTabsFor(block: InboxCounts | null | undefined): ClaimTab[] {
  if (!block) return [];
  const out: ClaimTab[] = [];
  if (block.recommended_high !== null || block.recommended_medium !== null) out.push("recommended");
  if (block.pool_with_hearing_7d !== null) out.push("pool");
  if (block.transfers_in_open !== null) out.push("transfers");
  return out;
}

function badge(tab: ClaimTab, block: InboxCounts): number | null {
  if (tab === "recommended") return (block.recommended_high ?? 0) + (block.recommended_medium ?? 0);
  if (tab === "transfers") return block.transfers_in_open;
  return null; // the pool: the API counts only pool cases with a hearing in 7 days
}

export function claimHref(tab: ClaimTab, department: string | null): string {
  const base = CLAIM_TABS.find((t) => t.key === tab)!.href;
  return base + queryString({ department: department ?? undefined });
}

interface Done {
  text: string;
  caseRef: string;
}

/** The modal's case in the URL, kept through the exit animation so the closing modal keeps its content. */
function useModalCase(params: Params) {
  const current = params.case || null;
  const [last, setLast] = useState<string | null>(current);
  // the latest case opened, adjusted while rendering (React's "storing information from previous renders")
  if (current && current !== last) setLast(current);
  useEffect(() => {
    if (current) return;
    // after the exit animation the modal (and its queries) unmount
    const timer = setTimeout(() => setLast(null), DURATION.med + 50);
    return () => clearTimeout(timer);
  }, [current]);
  return { open: !!current, caseRef: current ?? last };
}

export function ClaimFrame({ tab, params }: { tab: ClaimTab; params: Params }) {
  const pathname = usePathname() ?? CLAIM_TABS.find((t) => t.key === tab)!.href;
  const overlay = useUrlOverlay("case", params, pathname);
  const sel = useInboxSelection(params.department);
  const [row, setRow] = useState<RowContext | null>(null);
  const [done, setDone] = useState<Done | null>(null);
  const modal = useModalCase(params);
  if (sel.isPending) return <Loading />;
  const tabs = claimTabsFor(sel.block);
  const readOnly = !!sel.department && !departmentsOf(sel.me).includes(sel.department);

  function open(next: RowContext) {
    const summary = next.kind === "recommended" ? next.rec.case : next.kind === "pool" ? next.item.case : next.transfer.case;
    setRow(next);
    setDone(null);
    overlay.open(refPath(summary.ref_no));
  }
  function close() {
    overlay.close();
  }
  function finished(kind: ActionKind, label: string, department: string | null) {
    const text =
      kind === "claim" || kind === "suggest" ? T.claim.done[kind](label, department) : T.claim.done[kind](label);
    setDone({ text, caseRef: modal.caseRef ?? "" });
    close();
  }

  return (
    <div className="stack">
      <PageHeader title={T.claim.title} subtitle={T.claim.subtitle} />
      <ErrorBanner error={sel.error} onRetry={sel.refetch} />
      {done ? (
        <Notice>
          <span className={s.notice}>
            <span>{done.text}</span>
            {done.caseRef ? <Link href={casePath(done.caseRef)}>{T.claim.openCasePage}</Link> : null}
          </span>
        </Notice>
      ) : null}
      <DepartmentSelect sel={sel} hrefFor={(code) => claimHref(tab, code)} />
      {readOnly ? <p className="muted">{T.inbox.readOnly}</p> : null}
      {sel.block && tabs.length > 0 ? (
        <Tabs
          label={T.claim.tabs}
          items={tabs.map((t) => ({
            href: claimHref(t, sel.department),
            label: CLAIM_TABS.find((x) => x.key === t)!.label,
            active: t === tab,
            count: badge(t, sel.block!),
          }))}
        />
      ) : null}
      {!sel.block ? null : !tabs.includes(tab) ? (
        <EmptyState>{sel.department || tab === "pool" ? T.notFoundText : T.inbox.noDepartmentInbox}</EmptyState>
      ) : tab === "recommended" ? (
        sel.department ? <Recommended params={params} department={sel.department} onOpen={open} /> : null
      ) : tab === "pool" ? (
        <Pool params={params} department={sel.department} onOpen={open} />
      ) : sel.department ? (
        <Transfers params={params} department={sel.department} onOpen={open} />
      ) : null}
      {modal.caseRef ? (
        <CaseModal
          key={modal.caseRef}
          open={modal.open}
          caseRef={modal.caseRef}
          tab={tab}
          department={sel.department}
          row={row && rowRef(row) === modal.caseRef ? row : null}
          outgoing={tab === "transfers" && params.direction === "out"}
          onClose={close}
          onDone={finished}
        />
      ) : null}
    </div>
  );
}

function rowRef(row: RowContext): string {
  const c = row.kind === "recommended" ? row.rec.case : row.kind === "pool" ? row.item.case : row.transfer.case;
  return refPath(c.ref_no);
}

/** `/claim`: the first tab the login may read (keeping `?department`). */
export function ClaimIndex({ params }: { params: Params }) {
  const router = useRouter();
  const sel = useInboxSelection(params.department);
  const first = claimTabsFor(sel.block)[0];
  useEffect(() => {
    if (first) router.replace(claimHref(first, params.department ? sel.department : null));
  }, [first, router, params.department, sel.department]);
  if (sel.isPending || first) return <Loading />;
  return (
    <div className="stack">
      <PageHeader title={T.claim.title} subtitle={T.claim.subtitle} />
      <ErrorBanner error={sel.error} onRetry={sel.refetch} />
      <EmptyState>{T.inbox.noDepartmentInbox}</EmptyState>
    </div>
  );
}
