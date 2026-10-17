"use client";

/**
 * The three next-date dialogs (design portal-next-dates, decisions 5-7, 9 and 17), each one existing API call:
 * Confirm (`POST /next-dates/{id}/confirm`, `{}`), Not correct (`POST /next-dates/{id}/reject` with the correct date
 * and the reason only when filled) and Enter date (`POST /cases/{ref}/next-dates`, with `order` when it answers an
 * order of the review list). A 409 `not_pending` closes the dialog, hands the message to the page (the row it came
 * from leaves the list) and reads the list and the case again.
 */
import { useState } from "react";

import { CharCounter, ConfirmDialog, TextArea, TextField } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { NextDate, NextDateRejectOut, NextDateReviewItem } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { NEXT_DATE_ERRORS, T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";
import { todayIst } from "@/lib/workflow";

import { caseName, dateProblem, isStale, NOTE_MAX, noteProblem, useNextDateRefresh } from "./common";

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

export function ConfirmNextDate({
  item,
  open,
  onClose,
  ...outcome
}: { item: NextDateReviewItem; open: boolean; onClose: () => void } & DialogOutcome) {
  const { action, run } = useNextDateAction(item.case.ref_no, outcome);
  const name = caseName(item.case);
  const date = formatDate(item.next_date);
  function close() {
    action.reset();
    onClose();
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.nd.confirmTitle(date, name)}
      onClose={close}
      onConfirm={() =>
        run(
          () => api<NextDate>(`/next-dates/${encodeURIComponent(item.id)}/confirm`, { method: "POST", body: {} }),
          (row) => T.nd.confirmed(formatDate(row.next_date), name),
          close,
        )
      }
      busy={action.busy}
      error={action.error}
      messages={NEXT_DATE_ERRORS}
      confirmLabel={T.nd.confirm}
    >
      <Sentence phrase={item.phrase} />
      <p>{T.nd.confirmEffect}</p>
    </ConfirmDialog>
  );
}

export function RejectNextDate({
  item,
  open,
  onClose,
  ...outcome
}: { item: NextDateReviewItem; open: boolean; onClose: () => void } & DialogOutcome) {
  const { action, run } = useNextDateAction(item.case.ref_no, outcome);
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  const dateError = dateProblem(date, { required: false });
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
    const body: { next_date?: string; note?: string } = {};
    if (date) body.next_date = date;
    if (note.trim()) body.note = note.trim();
    await run(
      () => api<NextDateRejectOut>(`/next-dates/${encodeURIComponent(item.id)}/reject`, { method: "POST", body }),
      (out) => (out.entered ? T.nd.rejectedWith(formatDate(out.entered.next_date)) : T.nd.rejected),
      close,
    );
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.nd.rejectTitle}
      onClose={close}
      onConfirm={submit}
      busy={action.busy}
      error={action.error}
      messages={NEXT_DATE_ERRORS}
      confirmLabel={T.nd.save}
    >
      <p>
        {T.nd.suggestedDate}: <strong>{formatDate(item.next_date)}</strong> · <span className="mono">{caseName(item.case)}</span>
      </p>
      <Sentence phrase={item.phrase} />
      <TextField
        label={T.nd.correctDate}
        type="date"
        min={todayIst()}
        value={date}
        error={tried && dateError ? dateError : undefined}
        onChange={(e) => setDate(e.target.value)}
      />
      <NoteField label={T.nd.reason} value={note} onChange={setNote} error={tried ? noteError : null} />
    </ConfirmDialog>
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
      onClose={close}
      onConfirm={submit}
      busy={action.busy}
      error={action.error}
      messages={NEXT_DATE_ERRORS}
      confirmLabel={T.nd.save}
    >
      <p className="mono">{name}</p>
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
