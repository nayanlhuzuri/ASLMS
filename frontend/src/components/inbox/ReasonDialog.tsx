"use client";

import { useState } from "react";
import { Dialog, DialogButtons } from "../ui/Dialog";
import { Field, TextArea } from "../ui/Field";

/** Asks for a reason, then calls `onConfirm(reason)`. */
export function ReasonDialog({
  open,
  title,
  description,
  submitLabel,
  required = true,
  danger,
  onClose,
  onConfirm,
}: {
  open: boolean;
  title: string;
  description?: string;
  submitLabel: string;
  required?: boolean;
  danger?: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<boolean>;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const close = () => {
    setReason("");
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={title}
      description={description}
      onSubmit={async () => {
        if (required && !reason.trim()) return;
        setBusy(true);
        const ok = await onConfirm(reason.trim());
        setBusy(false);
        if (ok) setReason("");
      }}
      footer={<DialogButtons submitLabel={submitLabel} busy={busy} onCancel={close} danger={danger} />}
    >
      <Field label={required ? "Reason (required)" : "Reason (optional)"}>
        <TextArea required={required} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
    </Dialog>
  );
}
