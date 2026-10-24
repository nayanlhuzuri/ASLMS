"use client";

/**
 * The case page frame (design portal-cases, decision 10; plan §5.3; Annexure B "Case detail"; rebuilt by
 * portal-ui-redesign, decisions 10.9, 10.10 and 24):
 * - the summary header, a card: the case number, the status badge and an ownership badge ("Your department" when the
 *   caller's department is the primary owner, else the owner's code); the parties line; four facts — Next hearing
 *   (with the court and item of the latest listing when it is that day, and the 48 h or week badge), File is with,
 *   Stage and Owner;
 * - the actions at the right: at most one primary, chosen in a fixed order among the flags the server returns (Send
 *   file by `custody.can_send`, else Claim by `ownership.actions.claim`, else Accept transfer by `decide_transfer`);
 *   Add note as a secondary button when `workflow.note_mode` is set; a "More actions" menu with Recall, Set stage,
 *   Upload document, Enter next date, Allot, Take over, Request transfer, Stop watching, Suggest, Dismiss and Audit
 *   trail, each by its existing flag or function. The API still decides every call;
 * - the banners for provisional, merged and not-yet-fetched cases;
 * - the tabs, each its own route, with the API's `counts`: Overview, Hearings, Orders, Documents, Notes, Timeline and
 *   More (Parties, Linked cases, Custody and stage, Alerts, Details); the Assistant tab after Timeline with
 *   `assistant.use` while the assistant is on (design assistant, decision 14).
 * A case the API answers 404 shows one neutral message, so the page reveals nothing.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { OwnershipDialogs, type DialogKind } from "@/components/inbox/dialogs";
import { EnterNextDate } from "@/components/nextdates/Dialogs";
import { Badge, Breadcrumb, Button, EmptyState, ErrorBanner, Loading, Menu, Notice, Tabs, type MenuItem } from "@/components/ui";
import { useWorkflowRefresh } from "@/components/workflow/common";
import { RecallDialog, SendDialog } from "@/components/workflow/CustodyDialogs";
import { NoteDialog } from "@/components/workflow/NoteDialog";
import { StageDialog } from "@/components/workflow/StageDialog";
import { UploadDialog } from "@/components/workflow/Upload";
import { api, ApiError } from "@/lib/api/client";
import { caseKey, useCase, useMe, useOwnership } from "@/lib/api/hooks";
import type { CaseDetail, CaseOwnershipView, ListingList, Me } from "@/lib/api/types";
import { can, departmentsOf, readsAudit } from "@/lib/can";
import { formatDate, hearingBadge } from "@/lib/format";
import { NEXT_DATE_ERRORS, T } from "@/lib/messages";
import { queryString } from "@/lib/params";
import { apiCasePath, casePath } from "@/lib/refs";
import { CASE_TABS, showsAssistant } from "@/lib/routes";
import { useAction } from "@/lib/useAction";

import s from "./case.module.css";

// decision 10.15: green means done (disposed); pending and unknown are neutral, amber is kept for due soon
function statusTone(status: string) {
  return status === "disposed" ? "success" : undefined;
}

/** The case as shown in dialogs and headings: its number, else its reference. */
export function caseName(c: Pick<CaseDetail, "identity" | "ref_no">): string {
  return c.identity.case_no_text || c.ref_no;
}

function useLatestListing(caseRef: string) {
  return useQuery({
    queryKey: [...caseKey(caseRef), "listings", 1],
    queryFn: () => api<ListingList>(`${apiCasePath(caseRef)}/listings`, { query: { limit: 1 } }),
  });
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={s.fact}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function NextHearingFact({ caseRef, c }: { caseRef: string; c: CaseDetail }) {
  const listing = useLatestListing(caseRef);
  const next = c.status.next_hearing_date;
  if (!next) return <span className="muted">{T.case.noNext}</span>;
  const last = listing.data?.items[0];
  // a row of a list replaced by a corrected list no longer places the case (design court-data-freshness, decision 12)
  const onDay = last && last.list_date === next && !last.superseded ? last : null;
  const badge = hearingBadge(next);
  return (
    <span className={s.factLine}>
      {/* the item number as printed in the cause list, else the serial (design portal-ui-polish, decision 12) */}
      <span>{T.case.nextAt(formatDate(next), onDay?.court_no ?? null, onDay ? (onDay.printed_sr ?? onDay.sr_no) : null)}</span>
      {badge === "critical" ? <Badge tone="danger">{T.case.within48}</Badge> : null}
      {badge === "week" ? <Badge>{T.case.thisWeek}</Badge> : null}
    </span>
  );
}

function holderText(c: CaseDetail, me: Me | undefined): string {
  const k = c.custody;
  if (!k) return "—";
  if (k.holder_user) {
    if (me && k.holder_user.id === me.user.id) return T.case.you(k.holder_user.designation);
    return [k.holder_user.full_name, k.holder_user.designation].filter(Boolean).join(" · ");
  }
  return k.holder_office ? k.holder_office.name : "—";
}

function OwnerBadge({ c, me }: { c: CaseDetail; me: Me | undefined }) {
  const owner = c.ownership.primary;
  if (!owner?.office_code) return null;
  const mine = departmentsOf(me).includes(owner.office_code);
  return mine ? <Badge tone="info">{T.case.yourDepartment}</Badge> : <Badge>{owner.office_code}</Badge>;
}

type Open =
  | { kind: "send" | "recall" | "stage" | "upload" | "next" | "note" }
  | { kind: "ownership"; dialog: DialogKind };

/**
 * The header's actions (decision 24): one primary at most, Add note, and "More actions". What shows comes from the
 * overview's flags and the ownership view's `actions`; a caller who cannot read the ownership view (404) has no
 * ownership action here.
 */
function CaseActions({
  caseRef,
  c,
  onNotice,
  onStale,
}: {
  caseRef: string;
  c: CaseDetail;
  onNotice: (text: string) => void;
  onStale: (error: unknown) => void;
}) {
  const me = useMe();
  const view = useOwnership(caseRef);
  const refresh = useWorkflowRefresh(caseRef);
  const [open, setOpen] = useState<Open | null>(null);
  const k = c.custody;
  const v: CaseOwnershipView | undefined = view.data;
  const a = v?.actions;
  const t = v?.open_transfer ?? null;
  const rows = v ? [v.primary, ...v.watchers].filter((r): r is NonNullable<typeof r> => !!r) : [];
  const holders = rows.map((r) => r.office_code);
  const own = (dialog: DialogKind) => setOpen({ kind: "ownership", dialog });
  const claim = () =>
    own({ kind: "claim", caseRef, departments: a?.claim_departments ?? null, currentOwner: v?.primary?.office_code ?? null });
  const accept = () => t && own({ kind: "decide", caseRef, transferId: t.id, accept: true });

  // the fixed order of decision 24
  const primary: { label: string; run: () => void; key: string } | null = k?.can_send
    ? { key: "send", label: T.wf.send, run: () => setOpen({ kind: "send" }) }
    : a?.claim
      ? { key: "claim", label: T.own.claim, run: claim }
      : a?.decide_transfer && t
        ? { key: "accept", label: T.claim.accept, run: accept }
        : null;

  const items: MenuItem[] = [];
  const add = (key: string, label: string, onSelect: () => void) => {
    if (primary?.key !== key) items.push({ key, label, onSelect });
  };
  if (k?.can_recall) add("recall", T.wf.recall, () => setOpen({ kind: "recall" }));
  if (c.workflow.set_stage) add("stage", T.wf.setStage, () => setOpen({ kind: "stage" }));
  if (c.workflow.upload) add("upload", T.wf.upload, () => setOpen({ kind: "upload" }));
  if (c.workflow.next_dates) add("next", T.nd.enterNext, () => setOpen({ kind: "next" }));
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

  const close = () => setOpen(null);
  return (
    <div className={s.actions} role="group" aria-label={T.case.actions}>
      {items.length > 0 ? <Menu label={T.kit.actions} items={items} /> : null}
      {c.workflow.note_mode ? (
        <Button variant="secondary" onClick={() => setOpen({ kind: "note" })}>
          {T.wf.addNote}
        </Button>
      ) : null}
      {primary ? <Button onClick={primary.run}>{primary.label}</Button> : null}
      {k?.can_send ? <SendDialog open={open?.kind === "send"} caseRef={caseRef} detail={c} onClose={close} onDone={onNotice} /> : null}
      {k?.can_recall ? <RecallDialog open={open?.kind === "recall"} caseRef={caseRef} card={k} onClose={close} onDone={onNotice} /> : null}
      {c.workflow.set_stage ? (
        <StageDialog
          open={open?.kind === "stage"}
          caseRef={caseRef}
          current={c.stage ? { stage: c.stage.stage, response_mode: c.stage.response_mode } : null}
          onClose={close}
          onDone={onNotice}
        />
      ) : null}
      {c.workflow.upload ? (
        <UploadDialog
          open={open?.kind === "upload"}
          caseRef={caseRef}
          onClose={close}
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
          onClose={close}
          onDone={onNotice}
          onStale={onStale}
        />
      ) : null}
      {c.workflow.note_mode ? (
        <NoteDialog open={open?.kind === "note"} caseRef={caseRef} mode={c.workflow.note_mode} onClose={close} onDone={onNotice} />
      ) : null}
      <OwnershipDialogs open={open?.kind === "ownership" ? open.dialog : null} onClose={close} />
    </div>
  );
}

/** The summary header (decision 24). `actions` false: the merged case, which offers no action. */
export function CaseHeader({ c, caseRef, actions = true }: { c: CaseDetail; caseRef: string; actions?: boolean }) {
  const me = useMe();
  const [notice, setNotice] = useState<string | null>(null);
  const [stale, setStale] = useState<unknown>(null);
  const owner = c.ownership.primary;
  const pet = c.parties_as_printed.petitioner_summary;
  const res = c.parties_as_printed.respondent_summary;
  return (
    <section className={s.header} aria-label={T.case.summary}>
      <Breadcrumb />
      <div className={s.titleRow}>
        {/* a case number is `cno`, a bare ref_no stays monospace (decision 10.1; design portal-ui-polish, decision 2) */}
        <h1 className={`${s.caseNo} ${c.identity.case_no_text ? "cno" : "mono"}`}>{caseName(c)}</h1>
        <Badge tone={statusTone(c.status.status)}>{T.inbox.statuses[c.status.status] ?? c.status.status}</Badge>
        <OwnerBadge c={c} me={me.data} />
        {actions ? (
          <CaseActions
            caseRef={caseRef}
            c={c}
            onNotice={(text) => {
              setStale(null);
              setNotice(text);
            }}
            onStale={(error) => {
              setNotice(null);
              setStale(error);
            }}
          />
        ) : null}
      </div>
      {pet || res ? (
        <p className={s.parties}>
          {pet ?? "—"} <span className="muted">{T.vs}</span> {res ?? "—"}
        </p>
      ) : null}
      <dl className={s.facts}>
        <Fact label={T.case.nextHearing}>
          <NextHearingFact caseRef={caseRef} c={c} />
        </Fact>
        <Fact label={T.case.fileWith}>{holderText(c, me.data)}</Fact>
        <Fact label={T.case.stage}>{c.stage ? c.stage.label : <span className="muted">{T.case.noStage}</span>}</Fact>
        <Fact label={T.case.owner}>{owner ? (owner.office_name ?? owner.office_code ?? "—") : T.case.unowned}</Fact>
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

export function CaseFrame({ caseRef, children }: { caseRef: string; children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "";
  const query = useCase(caseRef);
  if (query.isPending) return <Loading />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return <EmptyState>{T.case.notFound}</EmptyState>;
  }
  if (query.error || !query.data) return <ErrorBanner error={query.error} onRetry={() => query.refetch()} />;
  const c = query.data;
  const base = casePath(caseRef);
  if (c.merged_into_ref_no) {
    return (
      <div className="stack">
        <CaseHeader c={c} caseRef={caseRef} actions={false} />
        <Notice>
          {T.case.merged}{" "}
          <Link href={casePath(c.merged_into_ref_no)} className="mono">
            {T.case.openSurvivor(c.merged_into_ref_no)}
          </Link>
        </Notice>
      </div>
    );
  }
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
  return (
    <div className="stack">
      <CaseHeader c={c} caseRef={caseRef} />
      {c.portal.is_provisional ? <Notice>{T.case.provisional}</Notice> : null}
      {c.dossier_status !== "fetched" ? (
        <div className={s.banner} role="status">
          <span>{T.case.notFetched}</span>
          {can(me.data, "cases.search_court") ? <FetchFromCourt caseRef={caseRef} /> : null}
        </div>
      ) : null}
      <Tabs
        label={T.case.tabs}
        items={CASE_TABS.filter((t) => !t.more && (t.key !== "assistant" || showsAssistant(me.data))).map(tab)}
        more={CASE_TABS.filter((t) => t.more).map(tab)}
      />
      {children}
    </div>
  );
}
