import Link from "next/link";
import { fmtDate, humanize, parties } from "@/lib/format";
import type { Recommendation } from "@/lib/types";
import { asSignals, caseNumber, Details, ScoreBox, SignalList, signalChip } from "../case/CaseBits";
import s from "../case/case.module.css";
import { Button } from "../ui/Button";
import { HearingPill, Pill } from "../ui/Pill";

const ORIGIN: Record<string, string> = {
  cause_list: "From the cause list",
  discovery: "Found by department discovery",
  suggestion: "Suggested by another department",
};

export function RecommendationCard({
  rec,
  canAct,
  busy,
  onClaim,
  onDismiss,
  onSuggest,
}: {
  rec: Recommendation;
  canAct: boolean;
  busy: boolean;
  onClaim: () => void;
  onDismiss: () => void;
  onSuggest: () => void;
}) {
  const c = rec.case;
  const signals = asSignals(rec.signals);
  return (
    <article className={s.card} aria-label={caseNumber(c)}>
      <ScoreBox score={rec.score} band={rec.band} />
      <div className={s.cardMain}>
        <Link href={`/cases/${c.id}`} className={s.title}>
          {parties(c.petitioner, c.respondent)}
        </Link>
        <div className={s.meta}>
          <span className={s.caseNo}>{caseNumber(c)}</span>
          <span>· {ORIGIN[rec.origin] ?? humanize(rec.origin)}</span>
          {c.next_hearing_date ? <span>· Next hearing {fmtDate(c.next_hearing_date)}</span> : null}
          {c.court ? <span>· {c.court}</span> : null}
          <HearingPill date={c.next_hearing_date} />
        </div>
        <div className={s.chips}>
          {signals.slice(0, 4).map((sig, i) => (
            <Pill key={`${sig.kind}-${i}`} tone="neutral">
              {signalChip(sig)}
            </Pill>
          ))}
          {c.owners?.primary ? <Pill tone="warning">Already held by {c.owners.primary.name}</Pill> : null}
        </div>
        <Details summary="Why this recommendation">
          <SignalList signals={signals} />
          {rec.reason ? (
            <p className="muted" style={{ fontSize: 13, marginTop: 6 }}>
              {rec.reason}
            </p>
          ) : null}
        </Details>
      </div>
      {canAct ? (
        <div className={s.actions}>
          <Button variant="primary" icon="claim" onClick={onClaim} busy={busy}>
            Claim
          </Button>
          <Button onClick={onDismiss} disabled={busy}>
            Dismiss
          </Button>
          <Button variant="link" small onClick={onSuggest} disabled={busy}>
            Suggest department
          </Button>
        </div>
      ) : null}
    </article>
  );
}
