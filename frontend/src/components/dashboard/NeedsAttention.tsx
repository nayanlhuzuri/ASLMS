import Link from "next/link";
import { fmtDate, fmtNumber } from "@/lib/format";
import { alertKindLabel } from "@/lib/labels";
import type { Alert } from "@/lib/types";
import { Pill, type Tone } from "../ui/Pill";
import s from "./dashboard.module.css";

function alertPill(a: Alert): { tone: Tone; text: string } {
  const overdue = a.due_at ? new Date(a.due_at).getTime() < Date.now() : false;
  if (overdue && a.kind !== "order_received") return { tone: "criticalSoft", text: "Overdue" };
  if (a.kind === "order_received") return { tone: "success", text: "New order" };
  if (a.kind === "next_date") return { tone: "warning", text: "Review" };
  if (a.severity === "critical") return { tone: "critical", text: "Within 48 h" };
  if (a.severity === "high") return { tone: "warning", text: "This week" };
  return { tone: "info", text: alertKindLabel(a.kind) };
}

export interface AttentionProps {
  recommended?: number | null;
  recommendedHigh?: number | null;
  transfersIn?: number | null;
  alerts: Alert[];
}

export function NeedsAttention({ recommended: r, recommendedHigh: rh, transfersIn: ti, alerts }: AttentionProps) {
  const recommended = r ?? 0;
  const recommendedHigh = rh ?? 0;
  const transfersIn = ti ?? 0;
  const empty = recommended === 0 && transfersIn === 0 && alerts.length === 0;
  return (
    <div className={s.attention}>
      {empty ? <p className="muted" style={{ fontSize: 14, padding: "14px 0", borderTop: "1px solid var(--border)" }}>Nothing needs your attention right now.</p> : null}
      {recommended > 0 ? (
        <div className={s.item}>
          <div className={s.itemHead}>
            <Pill tone="info">New</Pill>
            <Link href="/inbox" className={s.itemLink}>
              Review
            </Link>
          </div>
          <div className={s.itemTitle}>
            {fmtNumber(recommended)} {recommended === 1 ? "case is" : "cases are"} recommended to your department
          </div>
          <div className={s.itemSub}>
            {recommendedHigh > 0 ? `${fmtNumber(recommendedHigh)} strong ${recommendedHigh === 1 ? "match" : "matches"}` : "Possible matches only"} · none is
            assigned until you claim it
          </div>
        </div>
      ) : null}
      {transfersIn > 0 ? (
        <div className={s.item}>
          <div className={s.itemHead}>
            <Pill tone="warning">Transfer</Pill>
            <Link href="/inbox?tab=transfers" className={s.itemLink}>
              Decide
            </Link>
          </div>
          <div className={s.itemTitle}>
            {fmtNumber(transfersIn)} incoming transfer {transfersIn === 1 ? "request" : "requests"}
          </div>
          <div className={s.itemSub}>Another department asks you to take over a case</div>
        </div>
      ) : null}
      {alerts.map((a) => {
        const pill = alertPill(a);
        return (
          <div key={a.id} className={s.item}>
            <div className={s.itemHead}>
              <Pill tone={pill.tone}>{pill.text}</Pill>
              <Link href={a.case_id ? `/cases/${a.case_id}` : "/alerts"} className={s.itemLink} aria-label={`Open: ${a.title}`}>
                Open
              </Link>
            </div>
            <div className={s.itemTitle}>{a.title}</div>
            <div className={s.itemSub}>
              {[a.body, a.due_at ? `due ${fmtDate(a.due_at)}` : null].filter(Boolean).join(" · ") || alertKindLabel(a.kind)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
