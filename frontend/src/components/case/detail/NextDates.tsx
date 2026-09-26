"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { nextDateSourceLabel } from "@/lib/labels";
import type { NextDate } from "@/lib/types";
import { Button } from "../../ui/Button";
import { Dialog, DialogButtons } from "../../ui/Dialog";
import { Field, TextArea, TextInput } from "../../ui/Field";
import { Pill } from "../../ui/Pill";
import { DataTable } from "../../ui/Table";
import { useToast } from "../../ui/Toast";

function reviewPill(nd: NextDate) {
  if (nd.review_status === "pending" || (nd.needs_review && nd.review_status === "none")) return <Pill tone="warning">Needs review</Pill>;
  if (nd.review_status === "confirmed") return <Pill tone="success">Confirmed</Pill>;
  if (nd.review_status === "rejected") return <Pill tone="muted">Rejected</Pill>;
  return null;
}

/** Next dates from every source; dates read from orders that need review can be confirmed, rejected or corrected. */
export function NextDates({ rows, canReview, onChanged }: { rows: NextDate[]; canReview: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<NextDate | null>(null);
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");

  const review = async (nd: NextDate, confirm: boolean, nextDate?: string, noteText?: string): Promise<boolean> => {
    setBusy(nd.id);
    try {
      await api.post(`/next-dates/${nd.id}/review`, { confirm, next_date: nextDate ?? null, note: noteText || null });
      toast.success(confirm ? (nextDate ? `Next date corrected to ${fmtDate(nextDate)}.` : "Next date confirmed.") : "Next date rejected.");
      onChanged();
      return true;
    } catch (e) {
      toast.error(e);
      return false;
    } finally {
      setBusy(null);
    }
  };

  const sorted = [...rows].sort((a, b) => b.next_date.localeCompare(a.next_date));
  const pending = (nd: NextDate) => nd.needs_review && (nd.review_status === "pending" || nd.review_status === "none");

  return (
    <>
      <DataTable
        bare
        caption="Next dates"
        rows={sorted}
        rowKey={(r) => r.id}
        columns={[
          { key: "date", header: "Date", render: (r) => <strong>{fmtDate(r.next_date)}</strong> },
          { key: "source", header: "Source", render: (r) => nextDateSourceLabel(r.source) },
          {
            key: "conf",
            header: "Confidence",
            render: (r) => (r.confidence !== null && r.confidence !== undefined ? `${Math.round(r.confidence * 100)}%` : "-"),
          },
          { key: "review", header: "Review", render: (r) => reviewPill(r) ?? "-" },
          { key: "note", header: "Note", render: (r) => r.note || "-" },
          {
            key: "act",
            header: "",
            actions: true,
            render: (r) =>
              canReview && pending(r) ? (
                <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <Button small variant="primary" busy={busy === r.id} onClick={() => review(r, true)}>
                    Confirm
                  </Button>
                  <Button
                    small
                    disabled={busy === r.id}
                    onClick={() => {
                      setDate(r.next_date);
                      setNote("");
                      setCorrecting(r);
                    }}
                  >
                    Correct
                  </Button>
                  <Button small variant="danger" disabled={busy === r.id} onClick={() => review(r, false)}>
                    Reject
                  </Button>
                </span>
              ) : null,
          },
        ]}
      />
      <Dialog
        open={correcting !== null}
        onClose={() => setCorrecting(null)}
        title="Correct the next date"
        description="Enter the date the court actually fixed. The correction is recorded with your name."
        onSubmit={async () => {
          if (!correcting || !date) return;
          const ok = await review(correcting, true, date, note.trim());
          if (ok) setCorrecting(null);
        }}
        footer={<DialogButtons submitLabel="Save date" busy={busy === correcting?.id} onCancel={() => setCorrecting(null)} />}
      >
        <Field label="Next date">
          <TextInput type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Note (optional)">
          <TextArea value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. as per order dated ..." />
        </Field>
      </Dialog>
    </>
  );
}
