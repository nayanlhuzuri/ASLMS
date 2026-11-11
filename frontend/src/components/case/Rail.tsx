"use client";

/**
 * The case page's action rail (design case-workspace-admin, decisions 8 and 10-14; template A, "Workspace with action
 * rail"): four cards beside the tabs from 1100 px (a sticky 320 px column), and below 1100 px the same cards under the
 * header, above the tabs, as collapsibles — "Your task" open, the others closed with their key fact in the title line.
 * - Your task, from the overview's custody card (no new call): the action needed, From, Due by, the latest remark
 *   (when the API returned it) and "See all remarks (n)" / "See the journey (n)" by the history's `remarks_shown`;
 *   Recall case as a secondary danger button by `can_recall`, never primary.
 * - Next hearing: the kit's `HearingDate` (design next-hearing-highlight), court and item when the latest listing is
 *   that day; the collapsed line carries the small badge.
 * - Quick actions: Add note, Upload and Set stage by the three workflow flags (the card hides with none).
 * - Journey of this case: the latest 4 movements, newest first, with the "now" marker.
 * Close Case (design close-case, decision 19): "Ready to Close" with the primary Close Case by `workflow.close`; the
 * reason a closer cannot close yet by `workflow.close_blocked` (`transfer_open`; nothing for `not_disposed`); a closed
 * case shows its closure line in place of the task, with no Send or Recall; Reopen Case by `workflow.reopen`, and the
 * owning-department line by `workflow.reopen_blocked`.
 * The server decides everything shown: the frontend never infers a hidden remark.
 *
 * Design portal-screen-fixes-work, decision 17: every card shows its title at every width ("Your Task" when the file
 * is with the reader, else "Current Task"), the holder is the first row of the task's facts, the Journey card has
 * "View All" in its head (beside the summary below 1100 px, outside the button), a collapsed card has no empty band, and
 * Quick Actions are equal-width buttons.
 */
import { useId, useState, type ReactNode } from "react";

import { Badge, Button, Collapsible, EmptyState, ErrorBanner, HeadLink, HearingDate, Loading, Notice } from "@/components/ui";
import { useJourney, useLatestListing, useMe, useOfficeNames } from "@/lib/api/hooks";
import type { CaseDetail, CustodyCard, CustodyHistory, CustodyLeg, Listing } from "@/lib/api/types";
import { cardHolder, cardSender, daysUntil, legActor, legHolder, withText } from "@/lib/cases";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";
import { serverLabel } from "@/lib/displayLabels";

import s from "./rail.module.css";

export type RailAction = "note" | "upload" | "stage" | "recall" | "next" | "close" | "reopen";

/** The case's open closure, or null (design close-case, decision 1: Closed while not reopened). */
export function openClosure(c: Pick<CaseDetail, "closure">) {
  return c.closure && !c.closure.reopened_at ? c.closure : null;
}

/** "<name>, <designation>" of a closer or reopener. */
export function closerName(by: { name?: string | null; designation?: string | null } | null | undefined): string {
  return [by?.name, by?.designation].filter(Boolean).join(", ") || "—";
}

/** Close Case and Reopen Case on the Your Task card, by the server's flags (decision 19). */
function CloseActions({ c, onAction }: { c: CaseDetail; onAction: (a: RailAction) => void }) {
  const w = c.workflow;
  return (
    <>
      {w.close ? (
        <div className={s.ready} data-ready-to-close="true">
          <Notice>
            <strong>{T.closure.readyToClose}</strong> {T.closure.readyText}
          </Notice>
          <Button onClick={() => onAction("close")}>{T.closure.closeCase}</Button>
        </div>
      ) : w.close_blocked === "transfer_open" ? (
        <p className={s.hint}>{T.closure.blockedTransfer}</p>
      ) : null}
      {w.reopen ? (
        <div className={s.buttons}>
          <Button variant="secondary" onClick={() => onAction("reopen")}>
            {T.closure.reopenCase}
          </Button>
        </div>
      ) : w.reopen_blocked === "not_own_department" ? (
        <p className={s.hint}>{T.closure.notOwnDepartment}</p>
      ) : null}
    </>
  );
}

/** The latest remark, clamped to `lines` with "Show all" when it is long; the full text stays in the page. */
export function ClampedRemark({ text, lines, quote = true }: { text: string; lines: 2 | 6; quote?: boolean }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const long = text.length > (lines === 6 ? 360 : 120) || text.split("\n").length > lines;
  return (
    <div className={s.remark}>
      <div id={id} className={long && !open ? (lines === 6 ? s.clamp6 : s.clamp2) : s.full}>
        {quote ? `“${text}”` : text}
      </div>
      {long ? (
        <Button variant="link" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
          {open ? T.rail.showLess : T.rail.showAll}
        </Button>
      ) : null}
    </div>
  );
}

function DueLine({ card }: { card: CustodyCard }) {
  if (!card.due_date) return <span className="muted">{T.rail.noDue}</span>;
  if (card.overdue) {
    return (
      <span>
        {formatDate(card.due_date)} · <span className={s.danger}>{T.rail.overdueBy(card.overdue_days)}</span>
      </span>
    );
  }
  return (
    <span>
      {formatDate(card.due_date)} · <span className="muted">{T.rail.daysLeft(Math.max(0, daysUntil(card.due_date)))}</span>
    </span>
  );
}

function RemarksButton({ journey, onRemarks }: { journey: CustodyHistory | undefined; onRemarks: () => void }) {
  if (!journey) return null;
  return (
    <Button variant="secondary" onClick={onRemarks}>
      {journey.remarks_shown ? T.rail.seeRemarks(journey.total) : T.rail.seeJourney(journey.total)}
    </Button>
  );
}

/** Decision 10's four states. */
export function YourTask({
  c,
  journey,
  onAction,
  onRemarks,
}: {
  c: CaseDetail;
  journey: CustodyHistory | undefined;
  onAction: (a: RailAction) => void;
  onRemarks: () => void;
}) {
  const me = useMe();
  const names = useOfficeNames().data;
  const card = c.custody;
  if (!card) return <p className="muted">{T.rail.unclaimed}</p>;
  const closed = openClosure(c);
  if (closed) {
    // design close-case, decision 19: the closure line in place of the task; nothing moves while closed
    return (
      <div className={s.task}>
        <p className={s.closedLine}>
          <Badge>{T.closure.closed}</Badge> {T.closure.closedOn(formatDate(closed.closed_at), closerName(closed.closed_by))}
        </p>
        <div className={s.buttons}>
          <RemarksButton journey={journey} onRemarks={onRemarks} />
        </div>
        <CloseActions c={c} onAction={onAction} />
      </div>
    );
  }
  const meId = me.data?.user.id ?? null;
  const mine = !!card.holder_user && !!meId && card.holder_user.id === meId;
  const sender = cardSender(card, names);
  const holder = withText(cardHolder(card), meId);
  const recall = card.can_recall ? (
    <Button variant="danger" onClick={() => onAction("recall")}>
      {T.wf.recall}
    </Button>
  ) : null;
  return (
    <div className={s.task}>
      <div className={s.taskAction}>{serverLabel(card.pending_action_label)}</div>
      <dl className={s.kv}>
        <dt>{T.rail.withFact}</dt>
        <dd title={holder.title}>{holder.text}</dd>
        {sender ? (
          <>
            <dt>{T.rail.from}</dt>
            <dd title={withText(sender).title}>{withText(sender).text}</dd>
          </>
        ) : null}
        <dt>{T.rail.dueBy}</dt>
        <dd>
          <DueLine card={card} />
        </dd>
      </dl>
      {card.remark ? <ClampedRemark text={card.remark} lines={6} /> : null}
      <div className={s.buttons}>
        <RemarksButton journey={journey} onRemarks={onRemarks} />
        {recall}
      </div>
      {mine && card.can_send && !c.workflow.close ? <p className={s.hint}>{T.rail.doneHint}</p> : null}
      <CloseActions c={c} onAction={onAction} />
    </div>
  );
}

export function NextHearing({
  c,
  listing,
  onAction,
}: {
  c: CaseDetail;
  listing: Listing | null | undefined;
  onAction: (a: RailAction) => void;
}) {
  const nh = c.next_hearing ?? null;
  const next = nh?.basis === "court" ? nh.date : null;
  const disposed = c.status.status === "disposed";
  const onDay = next && !disposed && listing && listing.list_date === next && !listing.superseded ? listing : null;
  // design next-hearing-highlight, decision 11, and next-date-direct, decisions 6 and 11: the kit's HearingDate with the
  // one next hearing, the court and item, and Enter Next Date only where the court gave no date
  return (
    <div className={s.hearing}>
      <div className={s.hearingDate}>
        <HearingDate next={nh} status={c.status.status} size="md" lines={!onDay} />
      </div>
      {onDay ? <div className="muted">{T.rail.courtItem(onDay.court_no ?? null, onDay.printed_sr ?? onDay.sr_no)}</div> : null}
      {nh?.reported_at && !disposed ? <div className="muted">{T.hearing.reported(formatDate(nh.reported_at))}</div> : null}
      {!nh && c.workflow.next_dates ? (
        <Button variant="link" onClick={() => onAction("next")}>
          {T.rail.enterNext}
        </Button>
      ) : null}
    </div>
  );
}

function quickItems(c: CaseDetail): { key: RailAction; label: string }[] {
  const out: { key: RailAction; label: string }[] = [];
  if (c.workflow.note_mode) out.push({ key: "note", label: T.wf.addNote });
  if (c.workflow.upload) out.push({ key: "upload", label: T.wf.upload });
  if (c.workflow.set_stage) out.push({ key: "stage", label: T.wf.setStage });
  return out;
}

export function QuickActions({ c, onAction }: { c: CaseDetail; onAction: (a: RailAction) => void }) {
  return (
    <div className={s.quick}>
      {quickItems(c).map((q) => (
        <Button key={q.key} variant="secondary" onClick={() => onAction(q.key)}>
          {q.label}
        </Button>
      ))}
    </div>
  );
}

function legLine(leg: CustodyLeg): string | null {
  return leg.reason === "sent" ? null : serverLabel(leg.reason_label);
}

export function Journey({ journey }: { journey: ReturnType<typeof useJourney> }) {
  const me = useMe();
  const names = useOfficeNames().data;
  const meId = me.data?.user.id ?? null;
  return (
    <div className={s.journey}>
      {journey.isPending ? <Loading lines={2} /> : null}
      <ErrorBanner error={journey.error} onRetry={() => journey.refetch()} />
      {journey.data ? (
        journey.data.legs.length === 0 ? (
          <EmptyState compact>{T.rail.noJourney}</EmptyState>
        ) : (
          <ol className={s.trail} aria-label={T.rail.journey}>
            {journey.data.legs.slice(0, 4).map((leg, i) => {
              const to = withText(legHolder(leg), meId);
              const by = legActor(leg, names);
              const reason = legLine(leg);
              return (
                <li key={leg.seq_no} className={i === 0 ? `${s.leg} ${s.now}` : s.leg} aria-current={i === 0 ? "step" : undefined}>
                  <div className={s.when}>
                    {formatDateTime(leg.started_at)}
                    {i === 0 ? <span className={s.nowMark}>{T.rail.now}</span> : null}
                  </div>
                  <div className={s.who} title={to.title}>
                    {T.rail.withWhom(to.text)}
                  </div>
                  {reason ? <div className="muted">{reason}</div> : null}
                  {leg.remark ? <ClampedRemark text={leg.remark} lines={2} /> : null}
                  {leg.reason === "sent" && by ? <div className="muted">{T.rail.sentByLine(withText(by).text)}</div> : null}
                </li>
              );
            })}
          </ol>
        )
      ) : null}
    </div>
  );
}

/**
 * One rail card: a plain card from 1100 px, a collapsible with its key fact below. The title shows at every width;
 * `action` (a head link) sits at the right of the title row, or beside the collapsible's summary, outside its button.
 */
function RailCard({
  wide,
  title,
  fact,
  open,
  action,
  children,
}: {
  wide: boolean;
  title: string;
  fact?: ReactNode;
  open?: boolean;
  action?: ReactNode;
  children: ReactNode;
}) {
  if (wide) {
    return (
      <section className={s.card} aria-label={title}>
        <div className={s.cardHead}>
          <h2 className={s.cardTitle}>{title}</h2>
          {action ? <div className={s.cardAction}>{action}</div> : null}
        </div>
        {children}
      </section>
    );
  }
  return (
    <section className={s.card} aria-label={title}>
      <Collapsible
        bare
        aside={action}
        defaultOpen={open}
        summary={
          <span className={s.summary}>
            <span className={s.cardTitle}>{title}</span>
            {fact ? <span className={s.fact}>{fact}</span> : null}
          </span>
        }
      >
        {children}
      </Collapsible>
    </section>
  );
}

export function Rail({
  c,
  caseRef,
  wide,
  onAction,
  onRemarks,
}: {
  c: CaseDetail;
  caseRef: string;
  /** From 1100 px: a column of plain cards beside the tabs; below, collapsible cards under the header. */
  wide: boolean;
  onAction: (a: RailAction) => void;
  onRemarks: () => void;
}) {
  const me = useMe();
  const listing = useLatestListing(caseRef);
  const journey = useJourney(caseRef, 4, 0, !!c.custody);
  const quick = quickItems(c);
  const latest = journey.data?.legs[0];
  const meId = me.data?.user.id ?? null;
  // "Your Task" would be wrong for someone else's file
  const mine = !!c.custody?.holder_user && !!meId && c.custody.holder_user.id === meId;
  return (
    <div className={s.rail} data-rail={wide ? "column" : "stacked"}>
      <RailCard wide={wide} title={mine ? T.rail.yourTask : T.rail.currentTask} open>
        <YourTask c={c} journey={c.custody ? journey.data : undefined} onAction={onAction} onRemarks={onRemarks} />
      </RailCard>
      <RailCard wide={wide} title={T.rail.nextHearing} fact={<HearingDate next={c.next_hearing ?? null} status={c.status.status} />}>
        <NextHearing c={c} listing={listing.data?.items[0]} onAction={onAction} />
      </RailCard>
      {quick.length > 0 ? (
        <RailCard wide={wide} title={T.rail.quickActions} fact={T.rail.actionsCount(quick.length)}>
          <QuickActions c={c} onAction={onAction} />
        </RailCard>
      ) : null}
      {c.custody ? (
        <RailCard
          wide={wide}
          title={T.rail.journey}
          fact={latest ? T.rail.withWhom(withText(legHolder(latest), me.data?.user.id).text) : null}
          action={
            <HeadLink href={casePath(caseRef, "custody")} srSuffix={T.rail.journeyLink}>
              {T.viewAll}
            </HeadLink>
          }
        >
          <Journey journey={journey} />
        </RailCard>
      ) : null}
    </div>
  );
}
