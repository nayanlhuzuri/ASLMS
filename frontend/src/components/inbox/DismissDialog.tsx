"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Office } from "@/lib/types";
import { Dialog, DialogButtons } from "../ui/Dialog";
import { Field, Select, TextArea } from "../ui/Field";
import { useToast } from "../ui/Toast";

/** Dismiss a recommendation with a required reason, optionally suggesting another department. */
export function DismissDialog({
  caseId,
  caseLabel,
  actingOfficeId,
  departments,
  suggestFirst,
  onClose,
  onDone,
}: {
  caseId: string | null;
  caseLabel: string;
  actingOfficeId?: string;
  departments: Office[];
  suggestFirst?: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [suggest, setSuggest] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const close = () => {
    setReason("");
    setSuggest("");
    onClose();
  };

  const submit = async () => {
    if (!caseId || !reason.trim()) return;
    setBusy(true);
    try {
      await api.post(`/cases/${caseId}/dismiss`, {
        office_id: actingOfficeId ?? null,
        reason: reason.trim(),
        suggest_office_id: suggest || null,
      });
      toast.success(suggest ? "Recommendation dismissed and suggested to the other department." : "Recommendation dismissed.");
      setReason("");
      setSuggest("");
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  const others = departments.filter((d) => d.id !== actingOfficeId);

  return (
    <Dialog
      open={caseId !== null}
      onClose={close}
      title={suggestFirst ? "Suggest another department" : "Dismiss recommendation"}
      description={`${caseLabel}. The case stays unassigned; your department will not be recommended this case again.`}
      onSubmit={submit}
      footer={<DialogButtons submitLabel={suggest ? "Dismiss and suggest" : "Dismiss"} busy={busy} onCancel={close} />}
    >
      {suggestFirst ? (
        <Field label="Department that should see this case" hint="That department receives the recommendation.">
          <Select value={suggest} onChange={(e) => setSuggest(e.target.value)} data-autofocus required>
            <option value="">Choose a department</option>
            {others.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
      <Field label="Reason (required)">
        <TextArea required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why this case does not belong to your department" />
      </Field>
      {!suggestFirst ? (
        <Field label="Suggest another department (optional)">
          <Select value={suggest} onChange={(e) => setSuggest(e.target.value)}>
            <option value="">No suggestion</option>
            {others.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
    </Dialog>
  );
}
