"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";
import { ErrorState } from "@/components/ui/States";
import { api, authCall, errorMessage } from "@/lib/api";
import { safeNext } from "@/lib/safeNext";
import type { Me } from "@/lib/types";
import s from "../auth.module.css";

interface Challenge {
  challenge_id: string;
  detail?: string;
}

export function LoginForm() {
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [step, setStep] = useState<"password" | "otp">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const otpRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (step === "otp") otpRef.current?.focus();
  }, [step]);

  const submitPassword = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const c = await authCall<Challenge>("login", { email, password });
      setChallenge(c);
      setPassword("");
      setStep("otp");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitOtp = async (e: FormEvent) => {
    e.preventDefault();
    if (!challenge) return;
    setError(null);
    setBusy(true);
    try {
      await authCall("verify", { challenge_id: challenge.challenge_id, code });
      let dest = next;
      try {
        const me = await api.get<Me>("/me");
        if (me.must_confirm_profile) dest = "/welcome";
      } catch {
        /* the portal layout will load the profile again */
      }
      window.location.assign(dest);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className={s.card}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 ref={headingRef} style={{ fontSize: 26 }}>
          Sign in
        </h1>
        <p className="muted" style={{ fontSize: 14 }}>
          {step === "password"
            ? "Use the e-mail address registered for your office."
            : (challenge?.detail ?? "A one-time password has been sent to your e-mail.")}
        </p>
      </div>
      {error ? <ErrorState message={error} /> : null}
      {step === "password" ? (
        <form className={s.form} onSubmit={submitPassword}>
          <Field label="E-mail">
            <TextInput type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password">
            <TextInput
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <Button type="submit" variant="primary" busy={busy}>
            Continue
          </Button>
          <div className={s.links}>
            <Link href="/forgot">Forgotten your password?</Link>
          </div>
        </form>
      ) : (
        <form className={s.form} onSubmit={submitOtp}>
          <Field label="One-time password" hint="Six digits, valid for a few minutes.">
            <TextInput
              ref={otpRef}
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
          <Button type="submit" variant="primary" busy={busy} disabled={code.length !== 6}>
            Sign in
          </Button>
          <div className={s.links}>
            <button
              type="button"
              className={s.linkButton}
              onClick={() => {
                setStep("password");
                setCode("");
                setError(null);
              }}
            >
              Use a different account
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
