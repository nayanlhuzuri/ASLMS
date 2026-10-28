"use client";

/**
 * The case page frame (design portal-cases, decision 10; plan §5.3; Annexure B "Case detail"; rebuilt by
 * portal-ui-redesign, decisions 10.9, 10.10 and 24, and by case-workspace-admin, decisions 8-16, template A
 * "Workspace with action rail"):
 * - the summary header, a card, full width: the case number, the status badge, an ownership badge ("Your department"
 *   when the caller's department is the primary owner, else the owner's code) and "Action due <date>" when the case
 *   is with the caller and has a due date (danger, "Overdue since <date>", once overdue); the parties line; five facts
 *   — Next hearing (the date with a whole-day countdown, the court and item of the latest listing when it is that day,
 *   the 48 h or week badge), With (the designation, decision 13), Stage, Owner department and Status (hidden on
 *   phones, where the badge stays);
 * - the actions at the right: at most one primary, chosen in a fixed order among the flags the server returns (Send
 *   case by `custody.can_send`, else Claim by `ownership.actions.claim`, else Accept transfer by `decide_transfer`);
 *   a "More actions" menu with Recall case, Enter next date, Claim, Accept transfer, Assign, Take over, Request
 *   transfer, Stop watching, Suggest, Dismiss and Audit trail, each by its existing flag or function. Add note, Upload
 *   and Set stage are only in the rail's Quick actions, so no action shows twice. The API still decides every call;
 * - the banners for provisional, merged and not-yet-fetched cases;
 * - below, two columns from 1100 px: the tabs card (each tab its own route, with the API's `counts`: Overview,
 *   Hearings, Orders, Documents, Notes, Timeline, the Assistant with `assistant.use` while the assistant is on, and
 *   More) and the action rail (`Rail`, a sticky 320 px column); below 1100 px the rail's cards sit under the header,
 *   above the tabs, as collapsible cards;
 * - the remarks history, a wide side panel on `?remarks=all` (`RemarksPanel`): Back closes it and the link can be
 *   shared.
 * A case the API answers 404 shows one neutral message, so the page reveals nothing.
 */
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { OwnershipDialogs, type DialogKind } from "@/components/inbox/dialogs";
import { EnterNextDate } from "@/components/nextdates/Dialogs";
import { Badge, Breadcrumb, Button, EmptyState, ErrorBanner, HearingDate, Loading, Menu, Notice, Tabs, type MenuItem } from "@/components/ui";
import { useWorkflowRefresh } from "@/components/workflow/common";
import { RecallDialog, SendDialog } from "@/components/workflow/CustodyDialogs";
import { NoteDialog } from "@/components/workflow/NoteDialog";
import { StageDialog } from "@/components/workflow/StageDialog";
import { UploadDialog } from "@/components/workflow/Upload";
import { api, ApiError } from "@/lib/api/client";
import { caseKey, useCase, useLatestListing, useMe, useOwnership } from "@/lib/api/hooks";
import type { CaseDetail, CaseOwnershipView, Listing, Me } from "@/lib/api/types";
import { can, departmentsOf, readsAudit } from "@/lib/can";
import { cardHolder, withText } from "@/lib/cases";
import { formatDate } from "@/lib/format";
import { NEXT_DATE_ERRORS, T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { apiCasePath, casePath, currentCaseHref } from "@/lib/refs";
import { CASE_TABS, showsAssistant } from "@/lib/routes";
import { useAction } from "@/lib/useAction";
import { RAIL_MIN_WORKSPACE, useElementWidth, useMediaQuery, WIDE_CASE_PAGE } from "@/lib/useMediaQuery";
import { useUrlOverlay } from "@/lib/useUrlOverlay";

import s from "./case.module.css";
import { Rail, type RailAction } from "./Rail";
import { RemarksPanel } from "./Remarks";

// decision 10.15: green means done (disposed); pending and unknown are neutral, amber is kept for due soon
function statusTone(status: string) {
  return status === "disposed" ? "success" : undefined;
}

/** The case as shown in dialogs and headings: its number, else its reference. */
export function caseName(c: Pick<CaseDetail, "identity" | "ref_no">): string {
  return c.identity.case_no_text || c.ref_no;
}

function Fact({ label, children, status }: { label: string; children: ReactNode; status?: boolean }) {
  return (
    <div className={status ? `${s.fact} ${s.factStatus}` : s.fact} data-fact={status ? "status" : undefined}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** The latest listing when it places the case on its next hearing date (the header's rule), else null. */
export function listingOnDay(c: CaseDetail, listing: Listing | null | undefined): Listing | null {
  // the one next hearing (design next-date-direct, decision 11); a listing places it only when the court's record gives it
  const next = c.next_hearing?.basis === "court" ? c.next_hearing.date : null;
  // a row of a list replaced by a corrected list no longer places the case (design court-data-freshness, decision 12)
  return listing && next && listing.list_date === next && !listing.superseded ? listing : null;
}

/**
 * The header's next hearing (design next-hearing-highlight, decision 11; next-date-direct, decisions 5, 8 and 11): the
 * kit's `HearingDate` in the medium size with the case's one next hearing, the word before the weekday and date, then
 * the court and item when the latest listing places the case on that day, else the line saying where the date comes
 * from; "Order Differs" with its sentence when the latest order gives another exact date; "Reported as possibly wrong"
 * while a report is open.
 */
function NextHearingFact({ c, listing }: { c: CaseDetail; listing: Listing | null | undefined }) {
  const onDay = listingOnDay(c, listing);
  const disposed = c.status.status === "disposed";
  const reported = c.next_hearing?.reported_at;
  return (
    <span className={s.factLine}>
      <HearingDate next={c.next_hearing ?? null} status={c.status.status} size="md" lines={!onDay} />
      {/* the item number as printed in the cause list, else the serial (design portal-ui-polish, decision 12) */}
      {onDay && !disposed ? <span className="muted">{T.rail.courtItem(onDay.court_no ?? null, onDay.printed_sr ?? onDay.sr_no)}</span> : null}
      {reported && !disposed ? (
        <span className="muted" data-reported="true">
          {T.hearing.reported(formatDate(reported))}
        </span>
      ) : null}
    </span>
  );
}

/** Decision 13: "<designation>, <office>" with "(you)"; the name only without a designation, and as the title. */
function WithFact({ c, me }: { c: CaseDetail; me: Me | undefined }) {
  if (!c.custody) return <span className="muted">—</span>;
  const w = withText(cardHolder(c.custody), me?.user.id);
  return <span title={w.title}>{w.text}</span>;
}

function OwnerBadge({ c, me }: { c: CaseDetail; me: Me | undefined }) {
  const owner = c.ownership.primary;
  if (!owner?.office_code) return null;
  const mine = departmentsOf(me).includes(owner.office_code);
  return mine ? <Badge tone="info">{T.case.yourDepartment}</Badge> : <Badge>{owner.office_code}</Badge>;
}

/** Decision 9: "Action due <date>" while the case is with the caller and has a due date; danger once overdue. */
export function ActionDueBadge({ c, me }: { c: CaseDetail; me: Me | undefined }) {
  const k = c.custody;
  if (!k?.due_date || !k.holder_user || !me || k.holder_user.id !== me.user.id) return null;
  return k.overdue ? (
    <Badge tone="danger">{T.rail.actionOverdue(formatDate(k.due_date))}</Badge>
  ) : (
    <Badge tone="warning">{T.rail.actionDue(formatDate(k.due_date))}</Badge>
  );
}

export type Open = { kind: RailAction | "send" } | { kind: "ownership"; dialog: DialogKind };

/**
 * The header's actions (decision 9): one primary at most and "More actions". What shows comes from the overview's
 * flags and the ownership view's `actions`; a caller who cannot read the ownership view (404) has no ownership action
 * here. Add note, Upload and Set stage are the rail's Quick actions only (decision 12).
 */
function CaseActions({ caseRef, c, onOpen }: { caseRef: string; c: CaseDetail; onOpen: (open: Open) => void }) {
  const me = useMe();
  const view = useOwnership(caseRef);
  const k = c.custody;
  const v: CaseOwnershipView | undefined = view.data;
  const a = v?.actions;
  const t = v?.open_transfer ?? null;
  const rows = v ? [v.primary, ...v.watchers].filter((r): r is NonNullable<typeof r> => !!r) : [];
  const holders = rows.map((r) => r.office_code);
  const own = (dialog: DialogKind) => onOpen({ kind: "ownership", dialog });
  const claim = () =>
    own({ kind: "claim", caseRef, departments: a?.claim_departments ?? null, currentOwner: v?.primary?.office_code ?? null });
  const accept = () => t && own({ kind: "decide", caseRef, transferId: t.id, accept: true });

  // the fixed order of portal-ui-redesign, decision 24
  const primary: { label: string; run: () => void; key: string } | null = k?.can_send
    ? { key: "send", label: T.wf.send, run: () => onOpen({ kind: "send" }) }
    : a?.claim
      ? { key: "claim", label: T.own.claim, run: claim }
      : a?.decide_transfer && t
        ? { key: "accept", label: T.claim.accept, run: accept }
        : null;

  const items: MenuItem[] = [];
  const add = (key: string, label: string, onSelect: () => void) => {
    if (primary?.key !== key) items.push({ key, label, onSelect });
  };
  if (k?.can_recall) add("recall", T.wf.recall, () => onOpen({ kind: "recall" }));
  if (c.workflow.next_dates) add("next", T.nd.enterNext, () => onOpen({ kind: "next" }));
  if (a?.claim) add("claim", T.own.claim, claim);
  if (a?.decide_transfer && t) add("accept", T.claim.accept, accept);
  if (a?.allot && a.allot_departments.length > 0) {
    add("allot", T.own.allot, () => own({ kind: "allot", caseRef, departments: a.allot_departments, rows }));
  }
  if (a?.take_over && a.take_over_departments.length > 0) {
    add("take_over", T.own.takeOver, () => own({ kind: "take_over", caseRef, departments: a.take_over_departments, rows }));
  }
  if (a?.request_transfer) {
    add("transfer", T.own.requestTransfer, () => own({ kind: "transfer", caseRef, exclude: [a.transfer_from] }));
  }
  if (a?.stop_watching) {
    add("stop", T.own.stopWatching, () => own({ kind: "stop_watching", caseRef, departments: a.stop_watching_departments }));
  }
  if (a?.suggest) {
    add("suggest", T.own.suggest, () => own({ kind: "suggest", caseRef, departments: a.suggest_departments, exclude: holders }));
  }
  if (a?.dismiss) add("dismiss", T.own.dismiss, () => own({ kind: "dismiss", caseRef, departments: a.dismiss_departments }));
  if (readsAudit(me.data)) {
    // design portal-audit-health, decision 7: audit readers only; the API re-checks
    items.push({ key: "audit", label: T.audit.trail, href: `/audit${queryString({ case: c.ref_no })}` });
  }

  return (
    <div className={s.actions} role="group" aria-label={T.case.actions}>
      {items.length > 0 ? <Menu label={T.kit.actions} items={items} /> : null}
      {primary ? <Button onClick={primary.run}>{primary.label}</Button> : null}
    </div>
  );
}

/**
 * Every dialog of the case page in one place, opened from the header or from the rail: Send case, Recall case, Set
 * stage, Upload, Enter next date, Add note and the ownership dialogs. Each mounts only with its flag, unchanged.
 */
function CaseDialogs({
  caseRef,
  c,
  open,
  onClose,
  onNotice,
  onStale,
}: {
  caseRef: string;
  c: CaseDetail;
  open: Open | null;
  onClose: () => void;
  onNotice: (text: string) => void;
  onStale: (error: unknown) => void;
}) {
  const refresh = useWorkflowRefresh(caseRef);
  const k = c.custody;
  return (
    <>
      {k?.can_send ? <SendDialog open={open?.kind === "send"} caseRef={caseRef} detail={c} onClose={onClose} onDone={onNotice} /> : null}
      {k?.can_recall ? <RecallDialog open={open?.kind === "recall"} caseRef={caseRef} card={k} onClose={onClose} onDone={onNotice} /> : null}
      {c.workflow.set_stage ? (
        <StageDialog
          open={open?.kind === "stage"}
          caseRef={caseRef}
          current={c.stage ? { stage: c.stage.stage, response_mode: c.stage.response_mode } : null}
          onClose={onClose}
          onDone={onNotice}
        />
      ) : null}
      {c.workflow.upload ? (
        <UploadDialog
          open={open?.kind === "upload"}
          caseRef={caseRef}
          onClose={onClose}
          onUploaded={async (doc) => {
            onNotice(T.wf.uploaded(doc.ref_no ?? doc.original_filename ?? ""));
            await refresh();
          }}
        />
      ) : null}
      {c.workflow.next_dates ? (
        <EnterNextDate
          caseRef={caseRef}
          name={caseName(c)}
          open={open?.kind === "next"}
          onClose={onClose}
          onDone={onNotice}
          onStale={onStale}
        />
      ) : null}
      {c.workflow.note_mode ? (
        <NoteDialog open={open?.kind === "note"} caseRef={caseRef} mode={c.workflow.note_mode} onClose={onClose} onDone={onNotice} />
      ) : null}
      <OwnershipDialogs open={open?.kind === "ownership" ? open.dialog : null} onClose={onClose} />
    </>
  );
}

/**
 * The summary header (decision 9). Without `onOpen` (the merged case) it offers no action. `notice` and `stale` are the
 * outcome of the latest dialog, shown under the facts.
 */
export function CaseHeader({
  c,
  caseRef,
  onOpen,
  notice = null,
  stale = null,
}: {
  c: CaseDetail;
  caseRef: string;
  onOpen?: (open: Open) => void;
  notice?: string | null;
  stale?: unknown;
}) {
  const me = useMe();
  const listing = useLatestListing(caseRef);
  const owner = c.ownership.primary;
  const pet = c.parties_as_printed.petitioner_summary;
  const res = c.parties_as_printed.respondent_summary;
  const status = T.inbox.statuses[c.status.status] ?? c.status.status;
  return (
    <section className={s.header} aria-label={T.case.summary}>
      <Breadcrumb />
      <div className={s.titleRow}>
        {/* a case number is `cno`, a bare ref_no stays monospace (decision 10.1; design portal-ui-polish, decision 2) */}
        <h1 className={`${s.caseNo} ${c.identity.case_no_text ? "cno" : "mono"}`}>{caseName(c)}</h1>
        <Badge tone={statusTone(c.status.status)}>{status}</Badge>
        <OwnerBadge c={c} me={me.data} />
        <ActionDueBadge c={c} me={me.data} />
        {onOpen ? <CaseActions caseRef={caseRef} c={c} onOpen={onOpen} /> : null}
      </div>
      {pet || res ? (
        <p className={s.parties}>
          {pet ?? "—"} <span className="muted">{T.vs}</span> {res ?? "—"}
        </p>
      ) : null}
      <dl className={s.facts}>
        <Fact label={T.case.nextHearing}>
          <NextHearingFact c={c} listing={listing.data?.items[0]} />
        </Fact>
        <Fact label={T.rail.withFact}>
          <WithFact c={c} me={me.data} />
        </Fact>
        <Fact label={T.case.stage}>{c.stage ? c.stage.label : <span className="muted">{T.case.noStage}</span>}</Fact>
        <Fact label={T.rail.ownerFact}>{owner ? (owner.office_name ?? owner.office_code ?? "—") : T.case.unowned}</Fact>
        <Fact label={T.rail.statusFact} status>
          {status}
        </Fact>
      </dl>
      {notice ? <Notice>{notice}</Notice> : null}
      <ErrorBanner error={stale} messages={NEXT_DATE_ERRORS} />
    </section>
  );
}

function FetchFromCourt({ caseRef }: { caseRef: string }) {
  const queryClient = useQueryClient();
  const action = useAction();
  async function fetchIt() {
    const out = await action.run(() => api(`${apiCasePath(caseRef)}/fetch-court`, { method: "POST" }));
    if (out.ok) await queryClient.invalidateQueries({ queryKey: caseKey(caseRef) });
  }
  return (
    <>
      <Button variant="secondary" busy={action.busy} onClick={fetchIt}>
        {T.case.fetch}
      </Button>
      <ErrorBanner error={action.error} />
    </>
  );
}

function useSearch(): Params {
  const search = useSearchParams();
  const out: Params = {};
  search?.forEach((value, key) => {
    out[key] = value;
  });
  return out;
}

/** The page once the case is loaded and not merged: the header, the rail, the tabs, the dialogs and the panel. */
function Workspace({ caseRef, c, children }: { caseRef: string; c: CaseDetail; children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "";
  const params = useSearch();
  const workspace = useRef<HTMLDivElement>(null);
  const width = useElementWidth(workspace);
  // from 1100 px, and only while the workspace beside the sidebar holds both columns
  const wide = useMediaQuery(WIDE_CASE_PAGE) && (width === null || width >= RAIL_MIN_WORKSPACE);
  const remarks = useUrlOverlay("remarks", params, pathname || casePath(caseRef));
  const [open, setOpen] = useState<Open | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [stale, setStale] = useState<unknown>(null);
  const base = casePath(caseRef);
  const tab = (t: (typeof CASE_TABS)[number]) => {
    const href = t.key ? `${base}/${t.key}` : base;
    const n = t.count ? c.counts[t.count] : null;
    return {
      href,
      label: t.label,
      count: n,
      active: t.key ? pathname.endsWith(`/${t.key}`) : pathname === base || pathname === decodeURIComponent(base),
    };
  };
  const rail = <Rail c={c} caseRef={caseRef} wide={wide} onAction={(kind) => setOpen({ kind })} onRemarks={() => remarks.open("all")} />;
  return (
    <div className="stack">
      <CaseHeader
        c={c}
        caseRef={caseRef}
        onOpen={setOpen}
        notice={notice}
        stale={stale}
      />
      {c.portal.is_provisional ? <Notice>{T.case.provisional}</Notice> : null}
      {c.dossier_status !== "fetched" ? (
        <div className={s.banner} role="status">
          <span>{T.case.notFetched}</span>
          {can(me.data, "cases.search_court") ? <FetchFromCourt caseRef={caseRef} /> : null}
        </div>
      ) : null}
      <div ref={workspace} className={s.workspace} data-layout={wide ? "rail" : "stacked"}>
        {wide ? null : rail}
        <div className={s.main}>
          <Tabs
            label={T.case.tabs}
            items={CASE_TABS.filter((t) => !t.more && (t.key !== "assistant" || showsAssistant(me.data))).map(tab)}
            more={CASE_TABS.filter((t) => t.more).map(tab)}
          />
          {children}
        </div>
        {wide ? (
          <aside className={s.railColumn} aria-label={T.rail.label}>
            {rail}
          </aside>
        ) : null}
      </div>
      <CaseDialogs
        caseRef={caseRef}
        c={c}
        open={open}
        onClose={() => setOpen(null)}
        onNotice={(text) => {
          setStale(null);
          setNotice(text);
        }}
        onStale={(error) => {
          setNotice(null);
          setStale(error);
        }}
      />
      <RemarksPanel caseRef={caseRef} c={c} open={remarks.value === "all"} onClose={remarks.close} />
    </div>
  );
}

export function CaseFrame({ caseRef, children }: { caseRef: string; children: ReactNode }) {
  const query = useCase(caseRef);
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const search = useSearchParams()?.toString() ?? "";
  const refNo = query.data?.ref_no;
  // an old case number in the address (a mail link sent before the renumbering) gives way to the current one
  // (design case-ref-court-prefix, decision 20)
  useEffect(() => {
    if (!refNo) return;
    const href = currentCaseHref(pathname, search, caseRef, refNo);
    if (href) router.replace(href);
  }, [caseRef, pathname, refNo, router, search]);
  if (query.isPending) return <Loading />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return <EmptyState>{T.case.notFound}</EmptyState>;
  }
  if (query.error || !query.data) return <ErrorBanner error={query.error} onRetry={() => query.refetch()} />;
  const c = query.data;
  if (c.merged_into_ref_no) {
    return (
      <div className="stack">
        <CaseHeader c={c} caseRef={caseRef} />
        <Notice>
          {T.case.merged}{" "}
          <Link href={casePath(c.merged_into_ref_no)} className="mono">
            {T.case.openSurvivor(c.merged_into_ref_no)}
          </Link>
        </Notice>
      </div>
    );
  }
  return (
    <Workspace caseRef={caseRef} c={c}>
      {children}
    </Workspace>
  );
}
