"use client";

/**
 * The case's Alerts tab (design portal-workflow, decision 15; plan §5.5) and the Acknowledge / Done actions (shared
 * with row 55's alerts screen). The list is `GET /cases/{ref}/alerts` (open and acknowledged by default, or all);
 * the actions show only where the API's `can_act` is true and by status. A reader who does not work on the case gets
 * an empty list from the API and the tab says why. There is no count badge (the overview carries none). A
 * `next_date_review` alert has "Answer it" to the review list (design portal-next-dates, decision 14).
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AnswerIt } from "@/components/alerts/AlertLink";
import {
  Button,
  CharCounter,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Pagination,
  SelectField,
  SeverityBadge,
  TextArea,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useCase } from "@/lib/api/hooks";
import type { AlertItem, AlertList } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { ALERT_ERRORS, T } from "@/lib/messages";
import { PAGE } from "@/lib/params";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";

import cs from "@/components/case/case.module.css";

import { useWorkflowRefresh, WORKING_BASES } from "./common";

const NOTE_MAX = 500;
const OPEN = ["open", "acknowledged"];

/** Acknowledge (open) and Done (open or acknowledged), only with the API's `can_act`; an optional note. */
export function AlertActions({ alert, onChanged }: { alert: AlertItem; onChanged: () => Promise<void> }) {
  const action = useAction();
  const [open, setOpen] = useState<"acknowledge" | "done" | null>(null);
  const [note, setNote] = useState("");
  if (!alert.can_act || !OPEN.includes(alert.status)) return null;

  function close() {
    setOpen(null);
    setNote("");
    action.reset();
  }

  async function submit() {
    if (!open || note.trim().length > NOTE_MAX) return;
    const out = await action.run(() =>
      api(`/alerts/${encodeURIComponent(alert.id)}/${open}`, { method: "POST", body: { note: note.trim() || null } }),
    );
    await onChanged();
    if (out.ok) close();
  }

  return (
    <div className="row">
      {alert.status === "open" ? (
        <Button variant="secondary" onClick={() => setOpen("acknowledge")}>
          {T.wf.acknowledge}
        </Button>
      ) : null}
      <Button variant="secondary" onClick={() => setOpen("done")}>
        {T.wf.done}
      </Button>
      <ConfirmDialog
        open={open !== null}
        title={open === "done" ? T.wf.doneTitle : T.wf.ackTitle}
        onClose={close}
        onConfirm={submit}
        busy={action.busy}
        error={action.error}
        messages={ALERT_ERRORS}
        confirmLabel={open === "done" ? T.wf.done : T.wf.acknowledge}
      >
        <p>
          <strong>{alert.title}</strong>
        </p>
        <TextArea
          label={T.wf.alertNote}
          value={note}
          rows={2}
          maxLength={NOTE_MAX}
          hint={T.wf.alertNoteHint}
          onChange={(e) => setNote(e.target.value)}
        />
        <CharCounter value={note} max={NOTE_MAX} />
      </ConfirmDialog>
    </div>
  );
}

export function CaseAlerts({ caseRef }: { caseRef: string }) {
  const detail = useCase(caseRef);
  const refresh = useWorkflowRefresh(caseRef);
  const [all, setAll] = useState(false);
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "alerts", all, offset],
    queryFn: () =>
      api<AlertList>(apiCasePath(caseRef, "alerts"), { query: { status: all ? "all" : undefined, limit: PAGE, offset } }),
    placeholderData: keepPreviousData,
  });
  const bases = detail.data?.access_basis ?? [];
  const reader = !bases.includes("state") && !bases.some((b) => WORKING_BASES.includes(b));
  return (
    <div className="stack">
      <SelectField
        label={T.wf.statusFilter}
        options={[
          { value: "open", label: T.wf.openAndAcknowledged },
          { value: "all", label: T.wf.allAlerts },
        ]}
        value={all ? "all" : "open"}
        onChange={(e) => {
          setAll(e.target.value === "all");
          setOffset(0);
        }}
      />
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{reader ? T.wf.alertsReader : T.wf.noAlerts}</EmptyState>
        ) : (
          <>
            <ul className="stack" style={{ listStyle: "none", padding: 0 }} aria-label={T.wf.alertsTab}>
              {list.data.items.map((a) => (
                <li key={a.id} className={cs.note}>
                  <div className={cs.noteHead}>
                    <SeverityBadge severity={a.severity} />
                    <strong>{a.kind_label}</strong>
                    <span>{T.wf.alertStatus[a.status] ?? a.status}</span>
                    <span className="mono muted">{a.ref_no}</span>
                    {a.due_at ? <span>{T.wf.dueAt(formatDateTime(a.due_at))}</span> : null}
                  </div>
                  <div>
                    <strong>{a.title}</strong>
                  </div>
                  {a.body ? <p className={cs.noteBody}>{a.body}</p> : null}
                  {a.acknowledged_by && a.acknowledged_at ? (
                    <div className="muted">{T.wf.acknowledgedBy(a.acknowledged_by.full_name, formatDateTime(a.acknowledged_at))}</div>
                  ) : null}
                  <AnswerIt alert={a} />
                  <AlertActions alert={a} onChanged={refresh} />
                </li>
              ))}
            </ul>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </div>
  );
}
