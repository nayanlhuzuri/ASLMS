"use client";

/**
 * The cells of the Case inbox and Case claim rows (design portal-ui-redesign, decisions 5 and 6, Work list template):
 * the case number with the parties under it, the stage, the pending action of a file with its due-date badge, and where
 * the file is; the next hearing is the kit's `HearingDate` (design next-hearing-highlight, decision 11). A row opens by
 * click or Enter, so the case number is plain text here (the row is the link).
 */
import { Badge, ListCount, OfficeName, SegmentedSwitch } from "@/components/ui";
import type { CaseSummary, CustodyBrief, StageBrief } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { serverLabel } from "@/lib/displayLabels";

import s from "./inbox.module.css";

export function CaseCell({ c }: { c: Pick<CaseSummary, "case_no_text" | "ref_no" | "cnr" | "petitioner_summary" | "respondent_summary"> }) {
  const parties = [c.petitioner_summary, c.respondent_summary].filter(Boolean);
  return (
    <div className={s.caseCell}>
      <span className={c.case_no_text ? "cno" : "mono"} title={c.cnr ?? undefined}>
        {c.case_no_text || c.ref_no}
      </span>
      {parties.length > 0 ? (
        <span className={s.parties}>
          {c.petitioner_summary ?? "—"} <span className="muted">{T.vs}</span> {c.respondent_summary ?? "—"}
        </span>
      ) : null}
    </div>
  );
}

/**
 * The department's Open / Closed of a case (design close-case, decisions 15-17): a neutral "Closed" when the case is
 * closed, a warning "Ready to Close" when the court has disposed of it and it is still open (`closed` false; nothing
 * when the summary withholds it).
 */
export function ClosureBadge({ c }: { c: Pick<CaseSummary, "status" | "closed"> }) {
  if (c.closed) return <Badge>{T.inbox.closed}</Badge>;
  if (c.closed === false && c.status === "disposed") return <Badge tone="warning">{T.inbox.readyToClose}</Badge>;
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

/** The pending action and due date of the file, with the red "Overdue n days" or amber "Due <date>" badge. */
export function ActionCell({ custody }: { custody: CustodyBrief | null | undefined }) {
  if (!custody || custody.pending_action === "none") return <span className="muted">—</span>;
  return (
    <span className={s.action}>
      <span>{serverLabel(custody.pending_action_label)}</span>
      {custody.overdue ? (
        <Badge tone="danger">{T.inbox.overdueDays(custody.overdue_days)}</Badge>
      ) : custody.due_date ? (
        <Badge tone="warning">{T.inbox.dueOn(formatDate(custody.due_date))}</Badge>
      ) : null}
    </span>
  );
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
