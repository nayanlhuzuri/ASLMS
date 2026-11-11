"use client";

/**
 * "Why this is suggested" (design portal-ui-redesign, decision 7), beside the modal's tabs (below them on phones): one
 * line per signal of the recommendation row with its contribution (`signalText`), a match-strength meter filled to
 * the stored score, for a pool case "Best Score" with the department and its score badge (the kit's `ScoreLine`, design
 * portal-screen-fixes-work, decision 20) and who dismissed it, and the rule's line
 * "Claiming makes this case your department's. It never returns to the unclaimed pool."
 */
import { Meter, ScoreLine, useOfficeName } from "@/components/ui";
import type { PoolCase, Recommendation } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { signalText, type Signal } from "@/lib/signals";

import s from "./claim.module.css";

function contribution(signal: Signal): string | null {
  const w = signal.weight;
  return typeof w === "number" ? w.toFixed(3) : null;
}

export function WhyBox({ rec, pool, showRule = true }: { rec?: Recommendation | null; pool?: PoolCase | null; showRule?: boolean }) {
  const nameOf = useOfficeName();
  const signals = (rec?.signals ?? []) as Signal[];
  const score = rec ? rec.score : (pool?.best_score ?? null);
  return (
    <aside className={s.why} aria-label={T.claim.why}>
      <h3>{T.claim.why}</h3>
      {rec ? (
        signals.length > 0 ? (
          <ul>
            {signals.map((sig, i) => (
              <li key={i}>
                <span>{signalText(sig)}</span>
                {contribution(sig) ? <span className={s.contribution}>{contribution(sig)}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p>{T.claim.noSignals}</p>
        )
      ) : null}
      {pool ? (
        <>
          <p className={s.poolBest}>
            <span>{T.claim.best}</span>{" "}
            {pool.best_score !== null ? (
              <ScoreLine office={{ code: pool.best_office_code }} score={pool.best_score} band={pool.best_band} />
            ) : (
              <span className="muted">{T.inbox.noScore}</span>
            )}
          </p>
          {pool.dismissed_by.length > 0 ? <p>{T.claim.poolDismissed(pool.dismissed_by.map((code) => nameOf(code)).join(", "))}</p> : null}
        </>
      ) : null}
      {score !== null && score !== undefined ? <Meter value={score} label={T.claim.meter} /> : null}
      {showRule ? <p>{T.claim.rule}</p> : null}
    </aside>
  );
}
