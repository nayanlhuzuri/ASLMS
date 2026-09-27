"use client";

import { useEffect, useState } from "react";
import { ApiError, authCall, errorMessage } from "@/lib/api";
import s from "@/app/(public)/auth.module.css";

export interface OtpChallenge {
  challenge_id: string;
  detail?: string;
  resend_after?: number;
}

interface Props {
  challengeId: string;
  /** Seconds before a new code may be requested (from the backend, normally 120). */
  resendAfter: number;
  onResent: (c: OtpChallenge) => void;
  onError: (message: string) => void;
}

function mmss(total: number): string {
  const m = Math.floor(total / 60);
  const sec = total % 60;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

/**
 * "Resend code" with a countdown. The button stays disabled until the wait is over; the backend enforces the same
 * wait, and if it still answers 429 the countdown restarts from its `retry_after`.
 */
export function ResendCode({ challengeId, resendAfter, onResent, onError }: Props) {
  const [deadline, setDeadline] = useState(() => Date.now() + resendAfter * 1000);
  const [left, setLeft] = useState(resendAfter);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    const tick = () => setLeft(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [deadline]);

  const resend = async () => {
    setBusy(true);
    setSent(false);
    try {
      const c = await authCall<OtpChallenge>("resend", { challenge_id: challengeId });
      setDeadline(Date.now() + (c.resend_after ?? 120) * 1000);
      setSent(true);
      onResent(c);
    } catch (err) {
      const retry = err instanceof ApiError ? Number(err.details?.retry_after) : NaN;
      if (Number.isFinite(retry) && retry > 0) setDeadline(Date.now() + retry * 1000);
      onError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const waiting = left > 0;
  return (
    <div className={s.resend}>
      <span aria-live="polite" className="muted">
        {sent ? "A new code has been sent. " : null}
        {waiting ? `You can ask for a new code in ${mmss(left)}.` : "Didn't receive the code?"}
      </span>
      <button type="button" className={s.linkButton} onClick={resend} disabled={waiting || busy} aria-disabled={waiting || busy}>
        {busy ? "Sending…" : "Resend code"}
      </button>
    </div>
  );
}
