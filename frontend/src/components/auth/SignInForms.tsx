"use client";

/**
 * The sign-in screens (design portal-shell, decision 8), following the API's steps exactly: e-mail and password →
 * the e-mailed code → by `next_step` the welcome pages or the page asked for. The forgotten-password pair gives the
 * same neutral answer whatever the account. No bypass and no "trust this device" box.
 */
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button, ErrorBanner, Notice, TextField } from "@/components/ui";
import { ApiError, session } from "@/lib/api/client";
import type { LoginStep, NextStep, ResetStep } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { safeNext } from "@/lib/safeNext";

import { SignInSteps } from "./AuthFrame";
import s from "./auth.module.css";
import { afterSignIn, clearStep, loadStep, resendLeft, saveStep, type StoredStep } from "./steps";

function useNext(): string {
  const params = useSearchParams();
  return safeNext(params.get("next"));
}

function withNext(path: string, next: string): string {
  return next && next !== "/" ? `${path}?next=${encodeURIComponent(next)}` : path;
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = useNext();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const step = await session<LoginStep>("login", { email, password });
      saveStep({ sent_to: step.sent_to, expires_in: step.expires_in, resend_after: step.resend_after });
      router.push(withNext("/login/code", next));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <h1>{T.auth.signIn}</h1>
      <p>{T.auth.signInSub}</p>
      <SignInSteps step={1} />
      {params.get("reset") === "done" ? <Notice>{T.auth.passwordChanged}</Notice> : null}
      {params.get("expired") ? <ErrorBanner error={new ApiError(401, "otp_expired", "")} /> : null}
      <ErrorBanner error={error} />
      <TextField
        label={T.auth.email}
        type="email"
        name="email"
        autoComplete="username"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <TextField
        label={T.auth.password}
        type="password"
        name="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <Button type="submit" busy={busy}>
        {busy ? T.auth.signingIn : T.auth.signIn}
      </Button>
      <div className={s.links}>
        <Link href="/forgot">{T.auth.forgot}</Link>
      </div>
    </form>
  );
}

function useCountdown(step: StoredStep | null): [number, (seconds: number) => void] {
  const [left, setLeft] = useState(() => resendLeft(step));
  useEffect(() => {
    if (left <= 0) return;
    const timer = setInterval(() => setLeft((n) => Math.max(0, n - 1)), 1000);
    return () => clearInterval(timer);
  }, [left]);
  return [left, setLeft];
}

export function CodeForm() {
  const router = useRouter();
  const next = useNext();
  const [step] = useState<StoredStep | null>(() => (typeof window === "undefined" ? null : loadStep()));
  const [left, setLeft] = useCountdown(step);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [resent, setResent] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResent(false);
    try {
      const out = await session<{ next_step: NextStep }>("verify", { code: code.trim() });
      clearStep();
      router.replace(afterSignIn(out.next_step, next));
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError && err.code === "otp_expired") {
        clearStep();
        const query = new URLSearchParams({ expired: "1" });
        if (next !== "/") query.set("next", next);
        router.replace(`/login?${query.toString()}`);
        return;
      }
      setError(err);
    }
  }

  async function resend() {
    setError(null);
    setResent(false);
    try {
      const out = await session<LoginStep>("resend");
      saveStep({ sent_to: out.sent_to, expires_in: out.expires_in, resend_after: out.resend_after });
      setLeft(out.resend_after ?? 0);
      setResent(true);
    } catch (err) {
      if (err instanceof ApiError && typeof err.extra.retry_after === "number") setLeft(err.extra.retry_after);
      setError(err);
    }
  }

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <h1>{T.auth.codeTitle}</h1>
      <SignInSteps step={2} />
      <p>{step?.sent_to ? T.auth.codeSent(step.sent_to) : T.auth.codeSentGeneric}</p>
      {resent ? <Notice>{T.auth.resent}</Notice> : null}
      <ErrorBanner error={error} />
      <TextField
        label={T.auth.code}
        name="code"
        className={s.code}
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]{6}"
        maxLength={6}
        required
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
      />
      <Button type="submit" busy={busy} disabled={code.length !== 6}>
        {busy ? T.auth.verifying : T.auth.verify}
      </Button>
      <div className={s.links}>
        <Button variant="link" onClick={resend} disabled={left > 0}>
          {left > 0 ? T.auth.resendIn(left) : T.auth.resend}
        </Button>
        <Link href={withNext("/login", next)}>{T.auth.startAgain}</Link>
      </div>
    </form>
  );
}

export function ForgotForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const step = await session<ResetStep>("reset/request", { email });
      saveStep({ expires_in: step.expires_in, resend_after: step.resend_after });
      router.push("/forgot/code");
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <h1>{T.auth.forgotTitle}</h1>
      <p>{T.auth.forgotText}</p>
      <ErrorBanner error={error} />
      <TextField
        label={T.auth.email}
        type="email"
        name="email"
        autoComplete="username"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Button type="submit" busy={busy}>
        {T.auth.sendCode}
      </Button>
      <div className={s.links}>
        <Link href="/login">{T.back}</Link>
      </div>
    </form>
  );
}

export function ForgotCodeForm() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [mismatch, setMismatch] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== repeat) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    setBusy(true);
    try {
      await session("reset/confirm", { code: code.trim(), new_password: password });
      clearStep();
      router.replace("/login?reset=done");
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError && err.code === "otp_expired") {
        clearStep();
        router.replace("/forgot");
        return;
      }
      setError(err);
    }
  }

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <h1>{T.auth.forgotTitle}</h1>
      <p>{T.auth.forgotSent}</p>
      <ErrorBanner error={error} />
      <TextField
        label={T.auth.code}
        name="code"
        className={s.code}
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        required
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
      />
      <TextField
        label={T.auth.newPassword}
        type="password"
        autoComplete="new-password"
        hint={T.auth.policy}
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <TextField
        label={T.auth.repeatPassword}
        type="password"
        autoComplete="new-password"
        required
        error={mismatch ? T.auth.mismatch : undefined}
        value={repeat}
        onChange={(e) => setRepeat(e.target.value)}
      />
      <Button type="submit" busy={busy} disabled={code.length !== 6}>
        {T.auth.setPassword}
      </Button>
    </form>
  );
}

