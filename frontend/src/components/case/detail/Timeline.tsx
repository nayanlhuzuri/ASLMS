import { fmtDate, fmtDateTime, humanize } from "@/lib/format";
import { eventLabel } from "@/lib/labels";
import type { EventOut } from "@/lib/types";
import s from "./detail.module.css";

const DATE_KEY = /(date|_on)$/;
const HIDDEN = /(_id|^id|hash|key|token)$/;

function fmtValue(k: string, v: unknown): string {
  if (typeof v === "string" && DATE_KEY.test(k) && /^\d{4}-\d{2}-\d{2}/.test(v)) return fmtDate(v);
  if (typeof v === "number") return k.includes("score") ? v.toFixed(2) : String(v);
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

/** A short readable line from an event payload, without internal identifiers. */
export function payloadSummary(payload: Record<string, unknown>): string {
  const parts: string[] = [];
  if ("from" in payload && "to" in payload) {
    parts.push(`${fmtValue("from", payload.from)} to ${fmtValue("to", payload.to)}`);
  }
  for (const [k, v] of Object.entries(payload)) {
    if (k === "from" || k === "to" || HIDDEN.test(k)) continue;
    if (v === null || v === undefined || v === "" || typeof v === "object") continue;
    parts.push(`${humanize(k)}: ${fmtValue(k, v)}`);
    if (parts.length >= 5) break;
  }
  return parts.join(" · ");
}

export interface TimelineEntry {
  key: string;
  date: string;
  title: string;
  text?: string;
  dateOnly?: boolean;
}

export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  return (
    <ol className={s.timeline}>
      {entries.map((e, i) => (
        <li key={e.key} className={s.tlItem}>
          <div className={s.tlRail} aria-hidden="true">
            <div className={`${s.tlDot} ${i === 0 ? s.tlDotFirst : ""}`} />
            {i < entries.length - 1 ? <div className={s.tlLine} /> : null}
          </div>
          <div className={s.tlBody}>
            <div className={s.tlDate}>{e.dateOnly ? fmtDate(e.date) : fmtDateTime(e.date)}</div>
            <div className={s.tlTitle}>{e.title}</div>
            {e.text ? <div className={s.tlText}>{e.text}</div> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function eventsToEntries(events: EventOut[]): TimelineEntry[] {
  return [...events]
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
    .map((e) => ({ key: e.id, date: e.occurred_at, title: eventLabel(e.type), text: payloadSummary(e.payload) || undefined }));
}
