"use client";

/**
 * The cells of the Case inbox and Case claim rows (design portal-ui-redesign, decisions 5 and 6, Work list template):
 * the case number with the parties under it, the stage, the pending action of a file with its Due line, and where
 * the file is; the next hearing is the kit's `HearingDate` (design next-hearing-highlight, decision 11). A row opens by
 * click or Enter, so the case number is plain text here (the row is the link). Design portal-screen-fixes-work,
 * decisions 2 to 5: this `CaseCell` is the inbox's only case cell, with the case's marks (New, Recalled, Ready to Close,
 * Closed) as small badges under the number; one Action Needed cell holds the action over its `DueLine`.
 */
import { Badge, ListCount, OfficeName, SegmentedSwitch, type Tone } from "@/components/ui";
import type { CaseSummary, CustodyBrief, StageBrief } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { serverLabel } from "@/lib/displayLabels";

import s from "./inbox.module.css";

/** A mark of the case drawn under its number (design portal-screen-fixes-work, decision 2). */
export interface CaseMark {
  label: string;
  tone?: Tone;
}

export function CaseCell({
  c,
  marks,
}: {
  c: Pick<CaseSummary, "case_no_text" | "ref_no" | "cnr" | "petitioner_summary" | "respondent_summary">;
  marks?: (CaseMark | null | undefined)[];
}) {
  const parties = [c.petitioner_summary, c.respondent_summary].filter(Boolean);
  const shown = (marks ?? []).filter((m): m is CaseMark => !!m);
  return (
    <div className={s.caseCell}>
      <span className={c.case_no_text ? "cno" : "mono"} title={c.cnr ?? undefined}>
        {c.case_no_text || c.ref_no}
      </span>
      {shown.length > 0 ? (
        <span className={s.marks} data-marks="">
          {shown.map((m) => (
            <Badge key={m.label} tone={m.tone}>
              {m.label}
            </Badge>
          ))}
        </span>
      ) : null}
      {parties.length > 0 ? (
        <span className={s.parties}>
          {c.petitioner_summary ?? "—"} <span className="muted">{T.vs}</span> {c.respondent_summary ?? "—"}
        </span>
      ) : null}
    </div>
  );
}

/**
 * The department's Open / Closed of a case (design close-case, decisions 15-17) as a mark of the case (design
 * portal-screen-fixes-work, decision 4): a neutral "Closed" when the case is closed, a warning "Ready to Close" when the
 * court has disposed of it and it is still open (`closed` false; nothing when the summary withholds it).
 */
export function closureMark(c: Pick<CaseSummary, "status" | "closed">): CaseMark | null {
  if (c.closed) return { label: T.inbox.closed };
  if (c.closed === false && c.status === "disposed") return { label: T.inbox.readyToClose, tone: "warning" };
  return null;
}

/** My Cases' and Department's Open / Closed switch (design close-case, decisions 16 and 17): Open is the default. */
export function ClosureSwitch({ value, onChange }: { value: "open" | "closed"; onChange: (v: "open" | "closed") => void }) {
  return (
    <SegmentedSwitch
      label={T.inbox.closureSwitch}
      options={[
        { value: "open", label: T.inbox.open },
        { value: "closed", label: T.inbox.closed },
      ]}
      value={value}
      onChange={(v) => onChange(v === "closed" ? "closed" : "open")}
    />
  );
}

export function StageCell({ stage }: { stage: StageBrief | null | undefined }) {
  if (!stage) return <span className="muted">{T.inbox.noStage}</span>;
  return <span>{serverLabel(stage.label)}</span>;
}

/** The parts of a due date `DueLine` reads: the date and, where the server sends them, its flags. */
export interface DueState {
  date: string | null | undefined;
  overdue: boolean;
  overdueDays: number;
  dueSoon: boolean;
}

/**
 * The one Due line (design portal-screen-fixes-work, decision 5): a muted "No Due Date"; a red "Overdue by N Days"
 * with the date as its title; an amber "Due 12 Nov 2026" when due soon; otherwise the date as text. The caller decides
 * the flags (the server's on With Me and My Cases, `sentDue` on Sent by Me).
 */
export function DueLine({ due }: { due: DueState }) {
  if (!due.date) return <span className="muted">{T.due.none}</span>;
  if (due.overdue) {
    return (
      <Badge tone="danger" title={formatDate(due.date)}>
        {T.due.overdueBy(due.overdueDays)}
      </Badge>
    );
  }
  if (due.dueSoon) return <Badge tone="warning">{T.inbox.dueOn(formatDate(due.date))}</Badge>;
  return <span>{formatDate(due.date)}</span>;
}

/** A custody card's or brief's due state, from the server's flags. */
export function briefDue(
  custody: Pick<CustodyBrief, "due_date" | "overdue" | "overdue_days" | "due_soon"> | null | undefined,
): DueState {
  return {
    date: custody?.due_date ?? null,
    overdue: !!custody?.overdue,
    overdueDays: custody?.overdue_days ?? 0,
    dueSoon: !!custody?.due_soon,
  };
}

/**
 * The one Action Needed cell (design portal-screen-fixes-work, decision 5): the pending action on the first line and
 * the Due line under it; "—" when there is no pending action.
 */
export function ActionDueCell({ action, due }: { action: string | null | undefined; due: DueState }) {
  if (!action) return <span className="muted">—</span>;
  return (
    <span className={s.actionDue}>
      <span>{action}</span>
      <DueLine due={due} />
    </span>
  );
}

/** The Action Needed cell of a custody brief or card (`pending_action` "none" or absent: no action). */
export function custodyAction(
  custody: Pick<CustodyBrief, "pending_action" | "pending_action_label"> | null | undefined,
): string | null {
  if (!custody || !custody.pending_action || custody.pending_action === "none") return null;
  return serverLabel(custody.pending_action_label) ?? custody.pending_action;
}

/** Who holds the file: "You", the officer with the designation, or the office. */
export function HolderCell({ custody }: { custody: CustodyBrief | null | undefined }) {
  if (!custody) return <span className="muted">—</span>;
  if (custody.with_me) return <span>{T.inbox.you}</span>;
  if (custody.holder_user) {
    return (
      <span>
        {custody.holder_user.full_name}
        {custody.holder_user.designation ? <span className="muted">, {custody.holder_user.designation}</span> : null}
        {custody.holder_office ? (
          <span className="muted">
            {" · "}
            <OfficeName code={custody.holder_office.code} name={custody.holder_office.name} />
          </span>
        ) : null}
      </span>
    );
  }
  return <OfficeName code={custody.holder_office?.code} name={custody.holder_office?.name} />;
}

export function Chevron() {
  return (
    <svg className={s.chevron} aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

/**
 * The list's count line, the kit's `ListCount` (design list-search, decision 7): "n cases", "n of m cases" when
 * filtered (m = the tab's unfiltered count), or "n cases match" when m is not known.
 */
export function CountLine({ total, of, filtered }: { total: number | undefined; of: number | null | undefined; filtered: boolean }) {
  if (total === undefined) return null;
  return (
    <p className={s.count}>
      <ListCount shown={total} total={of} noun={T.inbox.casesNoun} nounOne={T.inbox.caseNoun} searching={filtered} />
    </p>
  );
}
