"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Layout";
import { ErrorState } from "@/components/ui/States";
import { authCall, errorMessage } from "@/lib/api";
import { ResendCode, type OtpChallenge } from "@/components/auth/ResendCode";
import s from "../auth.module.css";

export default function ForgotPage() {
  const [step, setStep] = useState<"email" | "reset" | "done">("email");
  const [email, setEmail] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [resendAfter, setResendAfter] = useState(120);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const sendCode = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const c = await authCall<OtpChallenge>("forgot", { email });
      setChallengeId(c.challenge_id);
      setResendAfter(c.resend_after ?? 120);
      setStep("reset");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const reset = async (e: FormEvent) => {
    e.preventDefault();
    if (pw !== pw2) {
      setError("The two passwords do not match.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await authCall("reset", { challenge_id: challengeId, code, new_password: pw });
      setStep("done");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={s.card}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 style={{ fontSize: 26 }}>Reset your password</h1>
        <p className="muted" style={{ fontSize: 14 }}>
          {step === "email"
            ? "Enter your e-mail address. A one-time password will be sent to it."
            : step === "reset"
              ? "If the address is registered, a one-time password has been sent to it."
              : "Your password has been changed."}
        </p>
      </div>
      {error ? <ErrorState message={error} /> : null}
      {step === "email" ? (
        <form className={s.form} onSubmit={sendCode}>
          <Field label="E-mail">
            <TextInput type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" busy={busy}>
            Send one-time password
          </Button>
        </form>
      ) : step === "reset" ? (
        <form className={s.form} onSubmit={reset}>
          <Field label="One-time password">
            <TextInput
              className={s.otp}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              required
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            />
          </Field>
          <Field label="New password" hint="At least 10 characters, with letters and digits.">
            <TextInput type="password" autoComplete="new-password" required minLength={10} value={pw} onChange={(e) => setPw(e.target.value)} />
          </Field>
          <Field label="Repeat the new password">
            <TextInput type="password" autoComplete="new-password" required minLength={10} value={pw2} onChange={(e) => setPw2(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" busy={busy} disabled={code.length !== 6}>
            Change password
          </Button>
          <ResendCode
            challengeId={challengeId}
            resendAfter={resendAfter}
            onResent={(c) => {
              setChallengeId(c.challenge_id);
              setResendAfter(c.resend_after ?? 120);
              setCode("");
              setError(null);
            }}
            onError={setError}
          />
        </form>
      ) : (
        <Notice>Sign in again with your new password.</Notice>
      )}
      <div className={s.links}>
        <Link href="/login">Back to sign in</Link>
      </div>
    </div>
  );
}
