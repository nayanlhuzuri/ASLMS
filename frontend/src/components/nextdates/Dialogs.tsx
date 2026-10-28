"use client";

/**
 * The next-date dialogs, each one existing API call:
 * - Enter date (design portal-next-dates, decisions 7, 9 and 17: `POST /cases/{ref}/next-dates`, with `order` when it
 *   answers an order of the review list), offered only where the court gave no date (design next-date-direct,
 *   decision 6: the server answers 409 `court_date_fixed` otherwise);
 * - Report Wrong Next Date (design next-date-direct, decision 17: `POST /next-dates/{id}/report` with the reason) and
 *   Correct Misread Next Date (decision 18: `POST /next-dates/{id}/correct` with the reason and the right date only when
 *   filled, or "Reading Is Right", `POST /next-dates/{id}/keep`), shown only by the server's flags.
 * Confirm and Not Correct are gone (decision 9): a date the court gave is never confirmed or replaced by a person. A
 * 409 `not_pending` closes the dialog, hands the message to the page and reads the list and the case again.
 */
import { useState } from "react";

import { CharCounter, ConfirmDialog, TextArea, TextField } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { NextDate, NextDateCorrectOut, NextDateReportOut } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import type { NextHearing } from "@/lib/hearingDate";
import { NEXT_DATE_ERRORS, T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";
import { todayIst } from "@/lib/workflow";

import { dateProblem, isStale, NOTE_MAX, noteProblem, useNextDateRefresh } from "./common";

/** The reason of a report or a correction (`NextDateReportIn` / `NextDateCorrectIn`): 10 to 300 characters. */
export const REASON_MIN = 10;
export const REASON_MAX = 300;

export interface DialogOutcome {
  /** The notice after a success. */
  onDone: (notice: string) => void;
  /** A stale answer (`not_pending`): the page shows it, the row is gone after the re-read. */
  onStale: (error: unknown) => void;
}

/** One action: on success the notice, on `not_pending` the page's message; the re-read follows either way. */
function useNextDateAction(caseRef: string, { onDone, onStale }: DialogOutcome) {
  const action = useAction();
  const refresh = useNextDateRefresh(caseRef);
  async function run<T>(work: () => Promise<T>, notice: (value: T) => string, close: () => void) {
    let stale: unknown = null;
    const out = await action.run(async () => {
      try {
        return await work();
      } catch (err) {
        if (isStale(err)) stale = err;
        throw err;
      }
    });
    if (out.ok) {
      close();
      onDone(notice(out.value));
    } else if (stale) {
      close();
      onStale(stale);
    }
    if (out.ok || stale) await refresh();
  }
  return { action, run };
}

function Sentence({ phrase }: { phrase: string | null | undefined }) {
  if (!phrase) return null;
  return (
    <blockquote>
      <span className="visually-hidden">{T.nd.says}: </span>
      {T.nd.quoted(phrase)}
    </blockquote>
  );
}

function NoteField({ label, value, onChange, error }: { label: string; value: string; onChange: (v: string) => void; error?: string | null }) {
  return (
    <>
      <TextArea
        label={label}
        value={value}
        rows={2}
        maxLength={NOTE_MAX}
        hint={T.nd.publicHint}
        error={error ?? undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      <CharCounter value={value} max={NOTE_MAX} />
    </>
  );
}

function reasonProblem(value: string): string | null {
  const n = value.trim().length;
  if (n < REASON_MIN) return T.nd.reasonTooShort;
  if (n > REASON_MAX) return T.nd.noteTooLong(REASON_MAX);
  return null;
}

function ReasonField({ label, hint, value, onChange, error }: { label: string; hint: string; value: string; onChange: (v: string) => void; error?: string | null }) {
  return (
    <>
      <TextArea
        label={label}
        value={value}
        rows={3}
        maxLength={REASON_MAX}
        hint={hint}
        aria-required
        error={error ?? undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      <CharCounter value={value} max={REASON_MAX} />
    </>
  );
}

export function EnterNextDate({
  caseRef,
  name,
  orderId,
  phrase,
  open,
  onClose,
  ...outcome
}: {
  caseRef: string;
  /** The case as shown (its number, else its reference). */
  name: string;
  /** The order the date answers (an *enter* item of the review list); none from the case page's button. */
  orderId?: string | null;
  phrase?: string | null;
  open: boolean;
  onClose: () => void;
} & DialogOutcome) {
  const { action, run } = useNextDateAction(caseRef, outcome);
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  const dateError = dateProblem(date, { required: true });
  const noteError = noteProblem(note);
  function close() {
    setDate("");
    setNote("");
    setTried(false);
    action.reset();
    onClose();
  }
  async function submit() {
    setTried(true);
    if (dateError || noteError) return;
    const body: { next_date: string; note?: string; order?: string } = { next_date: date };
    if (note.trim()) body.note = note.trim();
    if (orderId) body.order = orderId;
    await run(
      () => api<NextDate>(apiCasePath(caseRef, "next-dates"), { method: "POST", body }),
      (row) => T.nd.entered(formatDate(row.next_date), name),
      close,
    );
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.nd.enterTitle}
      subtitle={name}
      onClose={close}
      onConfirm={submit}
      busy={action.busy}
      error={action.error}
      messages={NEXT_DATE_ERRORS}
      confirmLabel={T.nd.save}
    >
      <Sentence phrase={phrase} />
      <TextField
        label={T.nd.nextDate}
        type="date"
        min={todayIst()}
        value={date}
        aria-required
        error={tried && dateError ? dateError : undefined}
        onChange={(e) => setDate(e.target.value)}
      />
      <NoteField label={T.nd.note} value={note} onChange={setNote} error={tried ? noteError : null} />
      <p className="muted">{T.nd.enterLine}</p>
    </ConfirmDialog>
  );
}

/** The reading a report or a correction is about: the case's one next hearing read from its latest order. */
interface ReadingProps {
  caseRef: string;
  name: string;
  /** The `next_dates` row read from the latest order (the shown value, or the reading that differs from the court). */
  nextDateId: string;
  /** The date read from the order. */
  dateRead: string;
  next: NextHearing | null;
  open: boolean;
  onClose: () => void;
}

/** Design next-date-direct, decision 17: the reason (10 to 300 characters) is shown to the people who correct dates. */
export function ReportWrongNextDate({ caseRef, name, nextDateId, dateRead, next, open, onClose, ...outcome }: ReadingProps & DialogOutcome) {
  const { action, run } = useNextDateAction(caseRef, outcome);
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const error = reasonProblem(reason);
  function close() {
    setReason("");
    setTried(false);
    action.reset();
    onClose();
  }
  async function submit() {
    setTried(true);
    if (error) return;
    await run(
      () =>
        api<NextDateReportOut>(`/next-dates/${encodeURIComponent(nextDateId)}/report`, {
          method: "POST",
          body: { reason: reason.trim() },
        }),
      () => T.nd.reported,
      close,
    );
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.nd.reportTitle}
      subtitle={name}
      onClose={close}
      onConfirm={submit}
      busy={action.busy}
      error={action.error}
      messages={NEXT_DATE_ERRORS}
      confirmLabel={T.nd.reportSend}
    >
      <p>
        {T.nd.dateRead}: <strong>{formatDate(dateRead)}</strong>
        {next?.order ? <> · {T.nd.orderOf(formatDate(next.order.order_date))}</> : null}
      </p>
      <Sentence phrase={next?.phrase} />
      <ReasonField label={T.nd.reportReason} hint={T.nd.reportHint} value={reason} onChange={setReason} error={tried ? error : null} />
      <p className="muted">{T.nd.reportLine}</p>
    </ConfirmDialog>
  );
}

/**
 * Design next-date-direct, decision 18: Correct (a required reason, the right date only when filled) or Reading Is Right
 * (closes the open reports). The court's own records cannot be changed.
 */
export function CorrectNextDate({
  caseRef,
  name,
  nextDateId,
  dateRead,
  next,
  open,
  onClose,
  reported,
  ...outcome
}: ReadingProps & DialogOutcome & { /** A report is open: Reading Is Right is offered. */ reported: boolean }) {
  const { action, run } = useNextDateAction(caseRef, outcome);
  const keep = useNextDateAction(caseRef, outcome);
  const [reason, setReason] = useState("");
  const [date, setDate] = useState("");
  const [tried, setTried] = useState(false);
  const error = reasonProblem(reason);
  const dateError = dateProblem(date, { required: false });
  function close() {
    setReason("");
    setDate("");
    setTried(false);
    action.reset();
    keep.action.reset();
    onClose();
  }
  async function submit() {
    setTried(true);
    if (error || dateError) return;
    const body: { reason: string; next_date?: string } = { reason: reason.trim() };
    if (date) body.next_date = date;
    await run(
      () => api<NextDateCorrectOut>(`/next-dates/${encodeURIComponent(nextDateId)}/correct`, { method: "POST", body }),
      (out) => (out.entered ? T.nd.corrected(formatDate(out.entered.next_date)) : T.nd.correctedNoDate),
      close,
    );
  }
  async function keepIt() {
    await keep.run(
      () => api<{ kept: boolean }>(`/next-dates/${encodeURIComponent(nextDateId)}/keep`, { method: "POST", body: {} }),
      () => T.nd.kept,
      close,
    );
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.nd.correctTitle}
      subtitle={name}
      onClose={close}
      onConfirm={submit}
      busy={action.busy || keep.action.busy}
      error={action.error ?? keep.action.error}
      messages={NEXT_DATE_ERRORS}
      confirmLabel={T.nd.correctSave}
      cancelLabel={reported ? T.nd.readingIsRight : undefined}
      onCancel={reported ? keepIt : undefined}
    >
      <p>
        {T.nd.dateRead}: <strong>{formatDate(dateRead)}</strong>
        {next?.order ? <> · {T.nd.orderOf(formatDate(next.order.order_date))}</> : null}
      </p>
      <Sentence phrase={next?.phrase} />
      <ReasonField label={T.nd.correctReason} hint={T.nd.correctReasonHint} value={reason} onChange={setReason} error={tried ? error : null} />
      <TextField
        label={T.nd.rightDate}
        type="date"
        min={todayIst()}
        value={date}
        hint={T.nd.rightDateHint}
        error={tried && dateError ? dateError : undefined}
        onChange={(e) => setDate(e.target.value)}
      />
      <p className="muted">{T.nd.courtUnchanged}</p>
    </ConfirmDialog>
  );
}
