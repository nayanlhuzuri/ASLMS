/**
 * A one-line detail for the common timeline event types (design portal-cases, decision 13; the workflow types of
 * portal-workflow, decision 19), read from known payload keys. Any other type shows the API's label only; the payload
 * is never printed as raw JSON. The `custody_moved` payload never carries the remark, and no line reads one; nor does
 * any next-date line read a note (design portal-next-dates, decision 15).
 */
import { formatDate } from "./format";

type Payload = Record<string, unknown>;

function str(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number") return String(value);
  return null;
}

function pair(value: unknown): [unknown, unknown] | null {
  return Array.isArray(value) && value.length === 2 ? [value[0], value[1]] : null;
}

function date(value: unknown): string | null {
  const s = str(value);
  return s ? formatDate(s) : null;
}

function join(parts: (string | null | undefined)[]): string | null {
  const kept = parts.filter((p): p is string => !!p);
  return kept.length ? kept.join(" · ") : null;
}

/** Labels from `GET /workflow/codes` and `/reference/labels` (code → label); a missing label shows the code. */
export interface TimelineLabels {
  reasons?: Record<string, string>;
  actions?: Record<string, string>;
  kinds?: Record<string, string>;
  stages?: Record<string, string>;
  alertKinds?: Record<string, string>;
}

function label(map: Record<string, string> | undefined, value: unknown): string | null {
  const code = str(value);
  return code ? (map?.[code] ?? code.replace(/_/g, " ")) : null;
}

const DETAIL: Record<string, (p: Payload, l: TimelineLabels) => string | null> = {
  next_date_changed: (p) => {
    const d = pair(p.next_hearing_date);
    if (!d) return null;
    return `${date(d[0]) ?? "—"} → ${date(d[1]) ?? "—"}`;
  },
  // design next-date-direct, decision 5: the latest order gives an exact date other than the court's record
  next_date_differs: (p) => {
    const court = date(p.court_date);
    const order = date(p.order_next_date);
    if (!court || !order) return null;
    const od = date(p.order_date);
    return od ? `The order of ${od} gives ${order}; the court's record gives ${court}` : `Order ${order} · court ${court}`;
  },
  listed: (p) => join([date(p.list_date ?? p.date), str(p.court_no) ? `Court ${str(p.court_no)}` : null]),
  listed_supplementary: (p) => join([date(p.list_date ?? p.date), str(p.court_no) ? `Court ${str(p.court_no)}` : null]),
  order_found: (p) => join([str(p.order_no) ? `Order ${str(p.order_no)}` : null, date(p.order_date)]),
  order_stored: (p) => join([str(p.order_no) ? `Order ${str(p.order_no)}` : null, date(p.order_date)]),
  status_changed: (p) => {
    const s = pair(p.status);
    return s ? `${str(s[0]) ?? "—"} → ${str(s[1]) ?? "—"}` : null;
  },
  claimed: (p) => join([str(p.office_code), str(p.role)]),
  allotted: (p) => join([str(p.office_code), str(p.unit_code)]),
  dismissed: (p) => join([str(p.office_code), str(p.reason)]),
  // design ownership-refinements, decision 10
  recommendation_closed: (p) => {
    const office = str(p.office_code);
    const by = str(p.claimed_by_office_code);
    return office && by ? `${office} — claimed by ${by}` : (office ?? null);
  },
  suggested_elsewhere: (p) => {
    const from = str(p.from_office_code);
    const to = str(p.to_office_code);
    return to ? `${from ?? "—"} → ${to}` : null;
  },
  transfer_requested: (p) => {
    const to = str(p.to_office_code);
    return to ? join([`${str(p.from_office_code) ?? "—"} → ${to}`, str(p.ref_no)]) : null;
  },
  transfer_decided: (p) => join([str(p.decision), str(p.to_office_code), str(p.ref_no)]),
  case_taken_over: (p) => {
    const to = str(p.to_user_name);
    return to ? join([`${str(p.from_user_name) ?? "—"} → ${to}`, str(p.office_code)]) : null;
  },
  case_merged: (p) => {
    const merged = str(p.merged_ref_no);
    return merged ? `Provisional ${merged} merged into this case` : null;
  },
  custody_moved: (p, l) => {
    const holder = [str(p.user_name), str(p.holder_designation)].filter(Boolean).join(", ") || null;
    const due = date(p.due_date);
    return join([label(l.reasons, p.reason), str(p.office_code), holder, label(l.actions, p.pending_action), due ? `due ${due}` : null]);
  },
  stage_set: (p, l) => join([str(p.label) ?? label(l.stages, p.stage), str(p.office_code)]),
  note_added: (p, l) => join([label(l.kinds, p.kind), str(p.ref_no), p.finalised === true ? "from a draft" : null]),
  document_uploaded: (p) => join([str(p.doc_type)?.replace(/_/g, " ") ?? null, str(p.office_code)]),
  alert_raised: (p, l) => label(l.alertKinds, p.kind),
  // design portal-next-dates, decision 15: payload keys only, never the note
  next_date_extracted: (p) => {
    const order = str(p.order_no) ? `Order ${str(p.order_no)}${date(p.order_date) ? ` of ${date(p.order_date)}` : ""}` : null;
    const next = date(p.next_date);
    return join([order, next ?? "no date read", p.review === true && next ? "to be confirmed" : null]);
  },
  next_date_reviewed: (p) => {
    const action = p.action === "confirm" ? "Confirmed" : p.action === "reject" ? "Not accepted" : null;
    return join([action, date(p.next_date), str(p.office_code)]);
  },
  next_date_entered: (p) => join([date(p.next_date), str(p.office_code), str(p.ref_no)]),
};

export function timelineDetail(type: string, payload: unknown, labels: TimelineLabels = {}): string | null {
  const fn = DETAIL[type];
  if (!fn || !payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  return fn(payload as Payload, labels);
}
