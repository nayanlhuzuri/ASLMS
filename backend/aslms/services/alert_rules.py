"""The alert rules without a database (design `alerts-notifications`, decisions 4, 6, 10, 11, 17, 19):
severities from dates, the recency window, dedupe keys, the e-mail preference rules with their defaults, and
the rendering of alert titles, bodies, mails and the daily digest. Nothing here reads a note, a document
description or an internal document name: a mail carries the alert title, the case number, CNR, court, the
date and a link."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aslms.core import clock
from aslms.domain.alerts import Severity
from aslms.domain.org import Channel, DigestMode, UserNotificationPreference
from aslms.domain.reference import AlertKind

IST = ZoneInfo("Asia/Kolkata")
TITLE_MAX = 300
HEARING_GRACE = timedelta(hours=12)  # a hearing alert expires this long after its due time
SEVERITY_RANK = {Severity.NORMAL: 0, Severity.HIGH: 1, Severity.CRITICAL: 2}
INFO_KINDS = frozenset(
    {
        AlertKind.NEXT_DATE_CHANGED,
        AlertKind.NEW_ORDER,
        AlertKind.STATUS_CHANGED,
        AlertKind.OWNERSHIP,
        AlertKind.NEW_DOCUMENT,
        AlertKind.NEW_NOTE,  # design alerts-visibility-roles, decision 7
    }
)
CASE_KINDS = INFO_KINDS | {
    AlertKind.HEARING_DUE,
    AlertKind.COMPLIANCE_DUE,
    AlertKind.WORKFLOW,
    AlertKind.NEXT_DATE_REVIEW,
    AlertKind.LISTED_TOMORROW,  # design alerts-visibility-roles, decision 12: not informational
}
LIST_TYPE_LABELS = {
    "daily": "daily cause list",
    "supplementary": "supplementary list",
    "lawazima": "lawazima list",
    "vacation": "vacation list",
    "other": "cause list",
}
# workflow alerts that are informational (design custody-workflow, decision 23 a, b): expire with the others
WORKFLOW_INFO_EVENTS = frozenset({"file_received", "file_recalled"})


def higher(a: Severity, b: Severity) -> bool:
    return SEVERITY_RANK[Severity(a)] > SEVERITY_RANK[Severity(b)]


# ------------------------------------------------------------------------------------------------ dates


def parse_sitting_time(value: str) -> time:
    h, _, m = (value or "10:30").partition(":")
    return time(int(h), int(m or 0))


def hearing_due_at(d: date, sitting_time: str | time = "10:30") -> datetime:
    """The date at the court's sitting time, IST."""
    t = sitting_time if isinstance(sitting_time, time) else parse_sitting_time(sitting_time)
    return datetime.combine(d, t, tzinfo=IST)


def today_ist(now: datetime) -> date:
    return clock.today_ist(now)


def severity_for_hearing(due_at: datetime, now: datetime, critical_hours: int = 48) -> Severity | None:
    """Decision 6: `high` inside the look-ahead window, `critical` within `critical_hours`; none once the
    sitting time has passed."""
    if due_at <= now:
        return None
    if due_at - now <= timedelta(hours=critical_hours):
        return Severity.CRITICAL
    return Severity.HIGH


def severity_for_due(due_date: date, today: date, soon_days: int = 2) -> Severity | None:
    """Decision 11 (requests): within `soon_days` → high; today and overdue → critical; later → none."""
    days = (due_date - today).days
    if days > soon_days:
        return None
    if days <= 0:
        return Severity.CRITICAL
    return Severity.HIGH


def severity_for_custody_due(due_date: date, today: date, soon_days: int = 2) -> Severity | None:
    """Design custody-workflow, decision 23c: `high` when due within `soon_days` (today included), `critical`
    once overdue; nothing further out."""
    days = (due_date - today).days
    if days > soon_days:
        return None
    return Severity.CRITICAL if days < 0 else Severity.HIGH


def severity_for_compliance(
    due_date: date, today: date, window_days: int = 7, critical_days: int = 2
) -> Severity | None:
    """Decision 10: raised within `window_days` or past; `critical` from `critical_days` before and when
    overdue, else `high`."""
    days = (due_date - today).days
    if days > window_days:
        return None
    if days <= critical_days:
        return Severity.CRITICAL
    return Severity.HIGH


def is_recent(court_date: date | None, today: date, max_age_days: int = 14) -> bool:
    """Decision 4: a court date within `max_age_days` of today (future dates count as recent); an unknown
    date is not recent."""
    if court_date is None:
        return False
    return court_date >= today - timedelta(days=max_age_days)


def hearing_expired(due_at: datetime, now: datetime) -> bool:
    return due_at + HEARING_GRACE < now


# ------------------------------------------------------------------------------------------------ keys


def dedupe_key(kind: AlertKind | str, *parts: Any) -> str:
    code = kind.value if isinstance(kind, AlertKind) else str(kind)
    return ":".join([code, *(str(p) for p in parts)])[:300]


def notification_key(alert_id: Any, user_id: Any, channel: Channel | str, severity: Severity | str) -> str:
    ch = channel.value if isinstance(channel, Channel) else str(channel)
    sev = severity.value if isinstance(severity, Severity) else str(severity)
    return f"n:{alert_id}:{user_id}:{ch}:{sev}"[:300]


# ------------------------------------------------------------------------------------------------ preferences


@dataclass(frozen=True)
class Prefs:
    """Decision 17's defaults: e-mail on, the daily digest, not critical-only; in-app always on."""

    email_enabled: bool = True
    digest: DigestMode = DigestMode.DAILY
    critical_only: bool = False


def effective_preferences(rows: list[UserNotificationPreference] | None) -> Prefs:
    for row in rows or []:
        if Channel(row.channel) == Channel.EMAIL:
            return Prefs(
                email_enabled=bool(row.enabled),
                digest=DigestMode(row.digest),
                critical_only=bool(row.critical_only),
            )
    return Prefs()


def immediate_email(prefs: Prefs, severity: Severity | str) -> bool:
    """An e-mail at once when e-mail is enabled and the alert is critical, or the user asked for no digest
    and not critical-only."""
    if not prefs.email_enabled:
        return False
    if Severity(severity) == Severity.CRITICAL:
        return True
    return prefs.digest == DigestMode.NONE and not prefs.critical_only


def wants_digest(prefs: Prefs) -> bool:
    return prefs.email_enabled and prefs.digest == DigestMode.DAILY


# ------------------------------------------------------------------------------------------------ rendering


def _d(value: Any) -> str:
    if value is None:
        return "?"
    if isinstance(value, datetime):
        return value.astimezone(IST).strftime("%d %b %Y")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b %Y")
    except ValueError:
        return str(value)


def case_label(case: Any) -> str:
    """The case as a user names it: the printed number, else the CNR, else the reference number."""
    return getattr(case, "case_no_text", None) or getattr(case, "cnr", None) or getattr(case, "ref_no", "?")


def _title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1] + "…"


def render_alert(kind: AlertKind | str, case: Any, data: dict[str, Any]) -> tuple[str, str]:
    """The title (≤ 300 characters) and body of an alert; never a note, a document description or an
    internal document name (a `new_document` alert names only the document type)."""
    kind = AlertKind(kind)
    d = data or {}
    if kind == AlertKind.ADMIN_TICKET:
        return render_ticket_alert(d)
    label = case_label(case)
    if kind == AlertKind.HEARING_DUE:
        title = f"Hearing on {_d(d.get('hearing_date'))}: {label}"
        if d.get("source") == "causelist":
            where = []
            if d.get("item_no"):
                where.append(f"item {d['item_no']}")
            if d.get("court_no"):
                where.append(f"court {d['court_no']}")
            body = f"Listed in the cause list of {_d(d.get('hearing_date'))}" + (
                ", " + ", ".join(where) if where else ""
            )
            if d.get("purpose"):
                body += f" ({d['purpose']})"
            body += "."
        elif d.get("source") == "next_date":
            body = "Next date entered or read from an order."
        else:
            body = "Next date per court records."
            if d.get("purpose"):
                body = f"Next date per court records ({d['purpose']})."
    elif kind == AlertKind.NEXT_DATE_CHANGED:
        title = f"Next date changed to {_d(d.get('hearing_date'))}: {label}"
        body = f"Previously {_d(d.get('previous_date'))}."
    elif kind == AlertKind.NEW_ORDER:
        title = f"New order of {_d(d.get('order_date'))}: {label}"
        body = f"Order {d.get('order_no') or ''} dated {_d(d.get('order_date'))} is available in the portal."
    elif kind == AlertKind.STATUS_CHANGED:
        status = d.get("status") or "unknown"
        if status == "disposed":
            title = f"Case disposed on {_d(d.get('disposal_date'))}: {label}"
            body = f"The court records show the case disposed ({d.get('disposal_nature') or 'nature not stated'})."
        else:
            title = f"Status changed to {status}: {label}"
            body = f"Previously {d.get('previous_status') or 'unknown'}."
    elif kind == AlertKind.COMPLIANCE_DUE:
        title = f"Compliance due {_d(d.get('compliance_by_date'))}: {label}"
        body = (
            f"Objections raised on scrutiny of {_d(d.get('scrutiny_date'))} are to be complied with by "
            f"{_d(d.get('compliance_by_date'))}."
        )
    elif kind == AlertKind.REQUEST_DUE:
        overdue = d.get("overdue")
        when = _d(d.get("due_date"))
        title = (f"Request overdue since {when}: " if overdue else f"Request due {when}: ") + label
        body = f"{d.get('request_kind_label') or 'Request'} from {d.get('from_office') or 'another office'}."
    elif kind == AlertKind.RECOMMENDATION and d.get("origin") == "suggestion":
        # design ownership-refinements, decision 15 (the suggestion's reason is shown in the inbox, not here)
        title = f"Suggested for {d.get('office_code') or 'your department'}: {label}"
        body = (
            f"{d.get('from_office_code') or 'Another office'} suggests this case belongs to your department; "
            "claim or dismiss it in the inbox."
        )
    elif kind == AlertKind.RECOMMENDATION:
        title = f"Strong match for {d.get('office_code') or 'your department'}: {label}"
        body = f"Recommended with score {d.get('score')}; claim or dismiss it in the inbox."
    elif kind == AlertKind.OWNERSHIP:
        sub = d.get("event") or "ownership"
        if sub == "allotted":
            title = f"Case allotted: {label}"
            body = f"Allotted to {d.get('officer_name') or d.get('unit_code') or 'your unit'} by {d.get('actor_name') or 'the department'}."
        elif sub == "case_taken_over":
            title = f"Case taken over by {d.get('to_user_name') or 'a colleague'}: {label}"
            body = f"The case allotted to you was taken over by {d.get('to_user_name') or 'a colleague'}."
        elif sub == "transfer_requested":
            title = f"Transfer requested by {d.get('from_office_code') or '?'}: {label}"
            body = f"{d.get('from_office_code') or 'A department'} asks {d.get('to_office_code') or 'your department'} to take the case."
        elif sub == "transfer_decided":
            title = f"Transfer {d.get('decision') or 'decided'} by {d.get('to_office_code') or '?'}: {label}"
            body = f"Your transfer request {d.get('ref_no') or ''} was {d.get('decision') or 'decided'}."
        elif sub == "recommendation_closed":  # design ownership-refinements, decision 10
            by = d.get("claimed_by_office_code") or "Another department"
            title = f"Claimed by {by}: {label}"
            body = f"{by} claimed this case; your department's recommendation is closed."
        else:
            title = f"Ownership change: {label}"
            body = ""
    elif kind == AlertKind.WORKFLOW:
        title, body = render_workflow(d, label)
    elif kind == AlertKind.NEXT_DATE_REVIEW:
        title, body = render_next_date_review(d, label)
    elif kind == AlertKind.NEW_DOCUMENT:
        title = f"New {d.get('doc_type_label') or d.get('doc_type') or 'document'} uploaded: {label}"
        body = f"A document of type {d.get('doc_type_label') or d.get('doc_type') or 'unknown'} was uploaded by {d.get('office_code') or 'an office'}."
    elif kind == AlertKind.NEW_NOTE:
        title, body = render_new_note(d, label)
    elif kind == AlertKind.LISTED_TOMORROW:
        title, body = render_listed_tomorrow(d, label)
    else:
        title = f"{kind.value}: {label}"
        body = ""
    return _title(title), body


def _note_kind_phrase(kind_label: str) -> str:
    """ "Hearing note" -> "hearing note", "General" -> "general note"."""
    words = kind_label.strip().lower() or "case"
    return words if ("note" in words or "noting" in words) else f"{words} note"


def render_new_note(d: dict[str, Any], label: str) -> tuple[str, str]:
    """A `new_note` alert (design alerts-visibility-roles, decision 5): the note's kind label, `ref_no`, the author's
    designation (or name) and office code; never the note text."""
    kind_label = d.get("kind_label") or d.get("kind") or "Note"
    if d.get("supersedes_ref_no"):
        title = f"Note corrected: {label}"
    else:
        title = f"New {_note_kind_phrase(str(kind_label))}: {label}"
    who = d.get("author_designation") or d.get("author_name") or "an officer"
    if d.get("office_code"):
        who = f"{who}, {d['office_code']}"
    body = f"Note {d.get('ref_no') or ''} ({kind_label}) by {who}."
    if d.get("supersedes_ref_no"):
        body += f" It corrects note {d['supersedes_ref_no']}."
    body += " Open the case to read it."
    return title, body


def listing_text(entries: list[dict[str, Any]], sep: str = ", ") -> list[str]:
    """Each listing as printed: "court 3, item 14" (`sep` joins the court and the item; the item is the printed
    serial number, else the serial number)."""
    out: list[str] = []
    for e in entries or []:
        parts = []
        if e.get("court_no"):
            parts.append(f"court {e['court_no']}")
        if e.get("item_no"):
            parts.append(f"item {e['item_no']}")
        out.append(sep.join(parts) or "item not printed")
    return out


def render_listed_tomorrow(d: dict[str, Any], label: str) -> tuple[str, str]:
    """A `listed_tomorrow` alert (design alerts-visibility-roles, decision 9): the court and the item of each listing
    of the day, as printed; no party or advocate text."""
    entries = list(d.get("entries") or [])
    total = int(d.get("entries_total") or len(entries))
    when = _d(d.get("hearing_date"))
    first = listing_text(entries[:1], sep=" ")
    more = f" +{total - 1} more" if total > 1 else ""
    title = f"Listed tomorrow, {when}" + (f", {first[0]}" if first else "") + f"{more}: {label}"
    phrases = []
    for i, (e, where) in enumerate(zip(entries, listing_text(entries), strict=True)):
        list_label = LIST_TYPE_LABELS.get(str(e.get("list_type") or ""), "cause list")
        if i == 0:
            phrases.append(f"Listed in the {list_label} of {when}: {where}")
        else:
            phrases.append(f"{list_label}: {where}")
    body = "; ".join(phrases) if phrases else f"Listed in the cause list of {when}"
    if total > len(entries):
        body += f"; and {total - len(entries)} more"
    return title, body + "."


def render_next_date_review(d: dict[str, Any], label: str) -> tuple[str, str]:
    """A `next_date_review` alert (design next-date-extraction, decision 13): the date to confirm with the order it
    was read from, or the order that gives no date; never a phrase of the order or a note."""
    if d.get("hearing_date"):
        how = "counted from" if d.get("source") == "order_period" else "read from"
        title = f"Next date to confirm, {_d(d.get('hearing_date'))}: {label}"
        body = (
            f"Next date to confirm: {_d(d.get('hearing_date'))} {how} the order of {_d(d.get('order_date'))}."
        )
    else:
        title = f"Enter the next date: {label}"
        body = (
            f"Enter the next date: the order of {_d(d.get('order_date'))} gives no date that could be read."
        )
    return title, body


def _holder(d: dict[str, Any], prefix: str = "holder") -> str:
    who = d.get(f"{prefix}_designation") or d.get(f"{prefix}_user_name") or "an officer"
    office = d.get(f"{prefix}_office_code")
    return f"{who}, {office}" if office else who


def render_workflow(d: dict[str, Any], label: str) -> tuple[str, str]:
    """A `workflow` alert (design custody-workflow, decision 23): kind label, offices, officer designation, case
    number, pending action and due date; never the remark or a note."""
    event = d.get("event") or "workflow"
    action = d.get("pending_action_label") or d.get("pending_action") or "action"
    due = f", due {_d(d.get('due_date'))}" if d.get("due_date") else ""
    if event == "file_received":
        title = f"File received from {d.get('from_office_code') or 'another office'}: {label}"
        body = f"Sent to {_holder(d)} for {action}{due}."
    elif event == "file_recalled":
        title = f"File taken back by {d.get('holder_office_code') or 'the owning department'}: {label}"
        body = f"The file you held is now with {_holder(d)} ({d.get('reason_label') or d.get('reason') or 'moved'})."
    elif event == "due":
        when = _d(d.get("due_date"))
        title = (f"File overdue since {when}: " if d.get("overdue") else f"File due {when}: ") + label
        body = f"{action} pending with {_holder(d)}."
    else:
        title, body = f"Workflow: {label}", ""
    return title, body


def render_ticket_alert(d: dict[str, Any]) -> tuple[str, str]:
    """An `admin_ticket` alert (design `user-memberships`, decision 19): the ticket ref, kind and department;
    never the payload."""
    ref = d.get("ticket_ref") or "?"
    kind = d.get("kind_label") or d.get("kind") or "request"
    dept = d.get("department_code") or "?"
    event = d.get("event") or "opened"
    if event == "opened":
        title = f"Admin ticket {ref} awaits your decision: {kind}, {dept}"
        body = (
            f"Requested by {d.get('requested_by') or 'a department admin'}. Open the ticket panel to decide."
        )
    else:
        title = f"Admin ticket {ref} {event}: {kind}, {dept}"
        body = f"The super admin {event} the request."
        if d.get("remark"):
            body += f" Remark: {d['remark']}"
    return _title(title), body


def ticket_url_ref(ref: str | None) -> str:
    return (ref or "").replace("/", "-")


def render_ticket_mail(alert: Any, portal_base_url: str) -> tuple[str, str]:
    """Subject and text of a single `admin_ticket` alert mail: the ticket ref, kind, department and the panel
    link, never the payload."""
    d = alert.data or {}
    sev = Severity(alert.severity).value.upper()
    subject = _title(f"[ASLMS {sev}] {alert.title}")
    lines = [
        alert.title,
        "",
        f"Ticket: {d.get('ticket_ref') or '-'}",
        f"Kind: {d.get('kind_label') or d.get('kind') or '-'}",
        f"Department: {d.get('department_code') or '-'}",
    ]
    if alert.body:
        lines += ["", alert.body]
    lines += [
        "",
        f"Open: {portal_base_url.rstrip('/')}/admin/tickets/{ticket_url_ref(d.get('ticket_ref'))}",
        "",
        "ASLMS - Assam State Litigation Management System",
    ]
    return subject, "\n".join(lines)


def render_mail(
    alert: Any, case: Any, court_name: str | None, portal_base_url: str, case_url_ref: str
) -> tuple[str, str]:
    """Subject and text of a single-alert mail (decision 19's content rule)."""
    sev = Severity(alert.severity).value.upper()
    subject = _title(f"[ASLMS {sev}] {alert.title}")
    lines = [
        alert.title,
        "",
        f"Case: {getattr(case, 'case_no_text', None) or '-'}",
        f"CNR: {getattr(case, 'cnr', None) or '-'}",
        f"Court: {court_name or '-'}",
    ]
    if alert.due_at is not None:
        lines.append(f"Date: {alert.due_at.astimezone(IST).strftime('%d %b %Y %H:%M IST')}")
    if alert.body:
        lines += ["", alert.body]
    lines += [
        "",
        f"Open: {portal_base_url.rstrip('/')}/cases/{case_url_ref}",
        "",
        "ASLMS - Assam State Litigation Management System",
    ]
    return subject, "\n".join(lines)


def render_digest(
    digest_date: date,
    groups: list[tuple[str, list[dict[str, Any]]]],
    hearings: list[dict[str, Any]],
    hearings_total: int,
    medium_recommendations: int | None,
    portal_base_url: str,
) -> tuple[str, str]:
    """Subject and text of the daily digest: alerts since the last digest grouped by kind, the hearings of
    the next seven days (capped, with the count), the department's possible matches."""
    base = portal_base_url.rstrip("/")
    subject = f"ASLMS daily digest - {digest_date.strftime('%d %b %Y')}"
    lines = [f"Your ASLMS digest for {digest_date.strftime('%d %b %Y')}", ""]
    if groups:
        lines.append("New alerts")
        for label, items in groups:
            lines.append(f"  {label} ({len(items)})")
            for it in items:
                link = it.get("link") or f"{base}/cases/{it['case_ref']}"
                lines.append(f"    - {it['title']}  {link}")
        lines.append("")
    if hearings_total:
        lines.append(f"Hearings today and in the next 7 days ({hearings_total})")
        for h in hearings:
            lines.append(
                f"    - {_d(h['date'])}  {h['case_label']}  [{h['source']}]  {base}/cases/{h['case_ref']}"
            )
        if hearings_total > len(hearings):
            lines.append(f"    ... and {hearings_total - len(hearings)} more in the portal calendar")
        lines.append("")
    if medium_recommendations:
        lines.append(
            f"Possible matches awaiting a decision in your department's inbox: {medium_recommendations}"
        )
        lines.append("")
    lines.append("ASLMS - Assam State Litigation Management System")
    return subject, "\n".join(lines)
