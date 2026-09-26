import type { ReactNode } from "react";
import { hearingBand } from "@/lib/format";
import s from "./ui.module.css";

export type Tone =
  | "neutral"
  | "muted"
  | "critical"
  | "criticalSoft"
  | "warning"
  | "success"
  | "info"
  | "infoSoft";

export function Pill({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`${s.pill} ${s[`pill-${tone}`]}`} title={title}>
      {children}
    </span>
  );
}

export function StatusPill({ status }: { status: string }) {
  if (status === "disposed") return <Pill tone="success">Disposed</Pill>;
  if (status === "pending") return <Pill tone="warning">Pending</Pill>;
  return <Pill tone="muted">Status unknown</Pill>;
}

/** "Within 48 h" / "This week" for a hearing date; nothing otherwise. */
export function HearingPill({ date }: { date: string | null | undefined }) {
  const band = hearingBand(date);
  if (band === "critical") return <Pill tone="critical">Within 48 h</Pill>;
  if (band === "week") return <Pill tone="warning">This week</Pill>;
  return null;
}

export function SeverityPill({ severity }: { severity: string }) {
  if (severity === "critical") return <Pill tone="critical">Critical</Pill>;
  if (severity === "high") return <Pill tone="warning">This week</Pill>;
  return <Pill tone="muted">Normal</Pill>;
}

export function AlertStatusPill({ status }: { status: string }) {
  if (status === "open") return <Pill tone="info">Open</Pill>;
  if (status === "acknowledged") return <Pill tone="warning">Acknowledged</Pill>;
  if (status === "done") return <Pill tone="success">Done</Pill>;
  return <Pill tone="muted">Expired</Pill>;
}
