import Link from "next/link";
import type { ReactNode } from "react";
import { fmtDate, fmtDayMonth, fmtScore, humanize, parties, weekday } from "@/lib/format";
import { signalLabel } from "@/lib/labels";
import type { CaseCard, Signal } from "@/lib/types";
import { HearingPill, Pill, StatusPill } from "../ui/Pill";
import s from "./case.module.css";

/** The number shown for a case: registration number, else filing number, else CNR. */
export function caseNumber(c: Pick<CaseCard, "case_no" | "filing_no" | "cnr">): string {
  return c.case_no || (c.filing_no ? `Filing ${c.filing_no}` : "") || c.cnr || "Provisional record";
}

export function ownerName(c: CaseCard): string | null {
  return c.owners?.primary?.name ?? null;
}

/** Compact custody holder for list cards: "With DSE (A. Das) · 12 days". */
export function CustodyChip({ c }: { c: CaseCard }) {
  const k = c.custody;
  if (!k) return null;
  const who = `${k.holder_office.name}${k.holder_user ? ` (${k.holder_user})` : ""}`;
  const days = `${k.days_pending} ${k.days_pending === 1 ? "day" : "days"}`;
  return (
    <Pill tone={k.overdue ? "criticalSoft" : "infoSoft"} title={k.pending_action ? `Pending: ${k.pending_action}` : undefined}>
      With {who} · {days}
      {k.overdue ? " · overdue" : ""}
    </Pill>
  );
}

/** A case as a tracking card: what every signed-in user may see. */
export function TrackingCard({ c, actions, extra }: { c: CaseCard; actions?: ReactNode; extra?: ReactNode }) {
  const owner = ownerName(c);
  return (
    <article className={s.card} aria-label={caseNumber(c)}>
      <div className={s.cardMain}>
        <Link href={`/cases/${c.id}`} className={s.title}>
          {parties(c.petitioner, c.respondent)}
        </Link>
        <div className={s.meta}>
          <span className={s.caseNo}>{caseNumber(c)}</span>
          <span title="Portal reference number">
            Ref <span className="mono">{c.ref_no}</span>
          </span>
          {c.cnr && c.case_no ? (
            <span>
              · CNR <span className="mono">{c.cnr}</span>
            </span>
          ) : null}
          {c.court ? <span>· {c.court}</span> : null}
        </div>
        <div className={s.chips}>
          <StatusPill status={c.status} />
          {c.is_provisional ? <Pill tone="warning">Provisional (no CNR yet)</Pill> : null}
          {owner ? <Pill tone="neutral">Held by {owner}</Pill> : <Pill tone="muted">Not claimed</Pill>}
          <CustodyChip c={c} />
          {c.stage ? <Pill tone="muted">Stage: {humanize(c.stage)}</Pill> : null}
          {c.owners?.watchers?.length ? <Pill tone="muted">Watched by {c.owners.watchers.map((w) => w.code).join(", ")}</Pill> : null}
        </div>
        {extra}
      </div>
      <div className={s.side}>
        {c.next_hearing_date ? (
          <>
            <span>Next hearing</span>
            <span className={s.sideStrong}>{fmtDate(c.next_hearing_date)}</span>
            <HearingPill date={c.next_hearing_date} />
            {c.next_purpose ? <span>{c.next_purpose}</span> : null}
          </>
        ) : c.disposal_date ? (
          <>
            <span>Disposed</span>
            <span className={s.sideStrong}>{fmtDate(c.disposal_date)}</span>
          </>
        ) : (
          <span>No next date known</span>
        )}
      </div>
      {actions ? <div className={s.actions}>{actions}</div> : null}
    </article>
  );
}

export function CardList({ children }: { children: ReactNode }) {
  return <div className={s.list}>{children}</div>;
}

/** One row of the dashboard's upcoming hearings. */
export function HearingRow({ c }: { c: CaseCard }) {
  const date = c.next_hearing_date ?? "";
  const owner = ownerName(c);
  return (
    <Link href={`/cases/${c.id}`} className={s.hearingRow}>
      <div className={s.rowDate}>
        <div className={s.rowDateMain}>{fmtDayMonth(date)}</div>
        <div className={s.rowDateSub}>
          {weekday(date)} · {date.slice(0, 4)}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
        <div className={s.rowTitle}>{parties(c.petitioner, c.respondent)}</div>
        <div>
          <span className={s.caseNo}>{caseNumber(c)}</span>{" "}
          <span className="muted" style={{ fontSize: 13 }}>
            {[c.court, c.next_purpose].filter(Boolean).map((x) => `· ${x}`).join(" ")}
          </span>
        </div>
      </div>
      <div className={s.rowHeld}>
        Held by
        <br />
        <span>{owner ?? "Not claimed"}</span>
      </div>
      <div className={s.rowPill}>
        <HearingPill date={date} />
      </div>
    </Link>
  );
}

export function ScoreBox({ score, band }: { score: number; band: string }) {
  const strong = band === "high";
  return (
    <div className={`${s.score} ${strong ? s.scoreStrong : s.scorePossible}`} aria-label={`Score ${fmtScore(score)}, ${strong ? "strong" : "possible"} match`}>
      <div className={s.scoreValue}>{fmtScore(score)}</div>
      <div className={s.scoreBand}>{strong ? "Strong" : "Possible"}</div>
    </div>
  );
}

export function signalChip(sig: Signal): string {
  return `${signalLabel(sig.kind)}: ${sig.value}`;
}

/** The signals behind a score: kind, value, matched text and weight. */
export function SignalList({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) return <div className="muted" style={{ fontSize: 13 }}>No signals recorded.</div>;
  return (
    <div className={s.signals}>
      {signals.map((sig, i) => (
        <div key={`${sig.kind}-${sig.value}-${i}`} className={s.signal}>
          <span className={s.signalKind}>{signalLabel(sig.kind)}</span>
          <span>
            <span className={sig.kind === "counsel_code" || sig.kind === "watchlist" ? "mono" : undefined}>{sig.value}</span>
            {sig.matched_text && sig.matched_text !== sig.value ? <span className="muted"> · matched “{sig.matched_text}”</span> : null}
          </span>
          <span className={s.signalWeight}>weight {sig.weight.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

export function Details({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className={s.details}>
      <summary>{summary}</summary>
      {children}
    </details>
  );
}

export function HearingRows({ children }: { children: ReactNode }) {
  return <div className={s.rows}>{children}</div>;
}
