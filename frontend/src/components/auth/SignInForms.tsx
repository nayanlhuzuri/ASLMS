"use client";

/**
 * The sign-in screens (design portal-shell, decision 8), following the API's steps exactly: e-mail and password →
 * the e-mailed code → by `next_step` the welcome pages or the page asked for. The forgotten-password pair gives the
 * same neutral answer whatever the account. No bypass and no "trust this device" box.
 * Design home-page, decisions 12 and 13: the password and code steps live in the home page's sign-in card, which moves
 * between them in place, so `LoginForm` and `CodeForm` hand their step changes to the card (`onSent`, `onStartAgain`,
 * `onExpired`) instead of navigating; the code step marks the arrival fade before it opens the portal.
 */
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useState, useSyncExternalStore, type FormEvent, type MouseEvent } from "react";

import { markArrive } from "@/components/shell/arrive";
import { Button, ErrorBanner, Notice, TextField } from "@/components/ui";
import { ApiError, session } from "@/lib/api/client";
import type { LoginStep, NextStep, ResetStep } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { safeNext } from "@/lib/safeNext";
import { sessionStore, signOutReasonText, type StoredLimits } from "@/lib/session/store";

import { SignInSteps } from "./AuthFrame";
import s from "./auth.module.css";
import { afterSignIn, clearStep, loadStep, resendLeft, saveStep, type StoredStep } from "./steps";

function useNext(): string {
  const params = useSearchParams();
  return safeNext(params.get("next"));
}

/** The shared clock is read once for the banner; nothing to subscribe to on the sign-in page. */
function noSubscription(): () => void {
  return () => undefined;
}

function withNext(path: string, next: string): string {
  return next && next !== "/" ? `${path}?next=${encodeURIComponent(next)}` : path;
}

/** The step's heading: `h1` on a page of its own, `h2` in the home page's card under the page's `h1`. */
export type HeadingLevel = "h1" | "h2";

export function LoginForm({ onSent, headingLevel = "h1" }: { onSent: () => void; headingLevel?: HeadingLevel }) {
  const Heading = headingLevel;
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const reason = params.get("reason");
  // design session-timeout, decision 20: why the person is here; the figures come from the shared clock (read after
  // mount: the browser's storage), never from the address
  // a JSON string: a stable snapshot for React (read once; nothing to subscribe to)
  const stored = useSyncExternalStore(noSubscription, () => JSON.stringify(sessionStore().storedLimits()), () => "null");
  const reasonText = signOutReasonText(reason, JSON.parse(stored) as StoredLimits | null, T.login);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const step = await session<LoginStep>("login", { email, password });
      saveStep({ sent_to: step.sent_to, expires_in: step.expires_in, resend_after: step.resend_after });
      onSent();
      // the home page's card keeps this form mounted while it fades out and brings the same one back if the step
      // returns within that time (Back, Start Again), so it must not stay busy (row 274 review advisory)
      setBusy(false);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <Heading>{T.auth.signIn}</Heading>
      <p>{T.auth.signInSub}</p>
      <SignInSteps step={1} />
      {params.get("reset") === "done" ? <Notice tone="success">{T.auth.passwordChanged}</Notice> : null}
      {reasonText ? <Notice>{reasonText}</Notice> : null}
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

export function CodeForm({
  onStartAgain,
  onExpired,
  headingLevel = "h1",
}: {
  onStartAgain: () => void;
  onExpired: () => void;
  headingLevel?: HeadingLevel;
}) {
  const Heading = headingLevel;
  const router = useRouter();
  const next = useNext();
  const sentId = useId();
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
      // a new session: the previous one's limits (its hard end above all) must not show here (review finding 2)
      sessionStore().clearLimits();
      const target = afterSignIn(out.next_step, next);
      // design home-page, decision 13: the portal fades in once; the first-sign-in pages have their own entry
      if (!target.startsWith("/welcome/")) markArrive();
      router.replace(target);
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError && err.code === "otp_expired") {
        clearStep();
        onExpired();
        return;
      }
      setError(err);
    }
  }

  function startAgain(e: MouseEvent<HTMLAnchorElement>) {
    // without JavaScript the link's address still leads back to the password step
    e.preventDefault();
    onStartAgain();
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
      <Heading>{T.auth.codeTitle}</Heading>
      <SignInSteps step={2} />
      <p id={sentId}>{step?.sent_to ? T.auth.codeSent(step.sent_to) : T.auth.codeSentGeneric}</p>
      {resent ? <Notice tone="success">{T.auth.resent}</Notice> : null}
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
        aria-describedby={sentId}
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
        <Link href={withNext("/login", next)} onClick={startAgain}>
          {T.auth.startAgain}
        </Link>
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

