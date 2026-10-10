"use client";

/**
 * The first-sign-in steps (design portal-shell, decisions 8 and 9): the own password, then the profile with a
 * mandatory mobile number and the notification preferences. The server enforces both (403 gate codes); these pages
 * only follow its `next_step`.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button, CheckField, ErrorBanner, Loading, SelectField, TextField } from "@/components/ui";
import { api, ApiError, session } from "@/lib/api/client";
import { labelOf, useLabels } from "@/lib/api/hooks";
import type { NextStep, ProfileOut } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { safeNext } from "@/lib/safeNext";

import s from "./auth.module.css";
import { afterSignIn } from "./steps";

export function PasswordStepForm() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

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
      const out = await session<{ next_step: NextStep }>("password", {
        current_password: current,
        new_password: password,
      });
      router.replace(afterSignIn(out.next_step, next));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <h1>{T.auth.welcomePasswordTitle}</h1>
      <p>{T.auth.welcomePasswordText}</p>
      <p className={s.policy}>{T.auth.policy}</p>
      <ErrorBanner error={error} />
      <TextField
        label={T.auth.currentPassword}
        type="password"
        autoComplete="current-password"
        required
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
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
      <Button type="submit" busy={busy}>
        {T.auth.setPassword}
      </Button>
    </form>
  );
}

export interface PrefsValue {
  emailEnabled: boolean;
  criticalOnly: boolean;
  digest: string;
}

export function PreferenceFields({ value, onChange }: { value: PrefsValue; onChange: (v: PrefsValue) => void }) {
  return (
    <fieldset className="stack" style={{ border: "1px solid var(--line)", borderRadius: 6, padding: 16 }}>
      <legend>{T.prefs.title}</legend>
      <CheckField label={T.prefs.inApp} checked disabled readOnly />
      <CheckField
        label={T.prefs.email}
        checked={value.emailEnabled}
        onChange={(e) => onChange({ ...value, emailEnabled: e.target.checked })}
      />
      <CheckField
        label={T.prefs.criticalOnly}
        checked={value.criticalOnly}
        disabled={!value.emailEnabled}
        onChange={(e) => onChange({ ...value, criticalOnly: e.target.checked })}
      />
      <SelectField
        label={T.prefs.digest}
        value={value.digest}
        disabled={!value.emailEnabled}
        onChange={(e) => onChange({ ...value, digest: e.target.value })}
        options={[
          { value: "daily", label: T.prefs.digestDaily },
          { value: "none", label: T.prefs.digestOff },
        ]}
      />
      <p className="muted">{T.prefs.sms}</p>
    </fieldset>
  );
}

export function prefsFrom(profile: Pick<ProfileOut, "notification_preferences">): PrefsValue {
  const email = profile.notification_preferences.email;
  return { emailEnabled: email.enabled, criticalOnly: email.critical_only, digest: email.digest || "none" };
}

export function prefsBody(value: PrefsValue) {
  return { email: { enabled: value.emailEnabled, critical_only: value.criticalOnly, digest: value.digest } };
}

export const MOBILE_PATTERN = /^(\+91[\s-]?|91|0)?[6-9]\d{9}$/;

export function ProfileStepForm() {
  const profile = useQuery({ queryKey: ["me", "profile"], queryFn: () => api<ProfileOut>("/me/profile") });
  if (profile.isPending) return <Loading />;
  if (profile.error || !profile.data) return <ErrorBanner error={profile.error} onRetry={() => profile.refetch()} />;
  return <ProfileConfirm profile={profile.data} />;
}

function ProfileConfirm({ profile }: { profile: ProfileOut }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const next = safeNext(useSearchParams().get("next"));
  const labels = useLabels();
  const [name, setName] = useState(profile.full_name);
  const [mobile, setMobile] = useState(profile.mobile ?? "");
  const [prefs, setPrefs] = useState<PrefsValue>(() => prefsFrom(profile));
  const [mobileError, setMobileError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const m = mobile.replace(/[\s-]/g, "");
    if (!m) {
      setMobileError(T.auth.mobileRequired);
      return;
    }
    if (!MOBILE_PATTERN.test(m)) {
      setMobileError(T.auth.mobileHint);
      return;
    }
    setMobileError(undefined);
    setBusy(true);
    try {
      await api("/me/profile/confirm", {
        method: "POST",
        body: { full_name: name.trim(), mobile: m, notification_preferences: prefsBody(prefs) },
      });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      router.replace(next);
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError && err.code === "password_change_required") {
        router.replace("/welcome/password");
        return;
      }
      if (err instanceof ApiError && err.code === "already_confirmed") {
        router.replace(next);
        return;
      }
      setError(err);
    }
  }

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <h1>{T.auth.welcomeProfileTitle}</h1>
      <p>{T.auth.welcomeProfileText}</p>
      <ErrorBanner error={error} />
      <TextField label={T.auth.email} value={profile.email} readOnly disabled />
      <TextField label={T.auth.fullName} required value={name} onChange={(e) => setName(e.target.value)} />
      <TextField
        label={T.auth.mobile}
        type="tel"
        inputMode="tel"
        autoComplete="tel-national"
        required
        hint={T.auth.mobileHint}
        error={mobileError}
        value={mobile}
        onChange={(e) => setMobile(e.target.value)}
      />
      <PreferenceFields value={prefs} onChange={setPrefs} />
      <section aria-label={T.auth.memberships}>
        <h2>{T.auth.memberships}</h2>
        <ul>
          {profile.memberships.map((m) => (
            <li key={`${m.office.code}-${m.role}`}>
              {m.designation ? `${m.designation}, ` : ""}
              {m.office.name} ({labelOf(labels.data?.user_types, m.role)})
              {m.is_primary ? ` — ${T.shell.primary}` : ""}
            </li>
          ))}
        </ul>
      </section>
      <Button type="submit" busy={busy}>
        {T.auth.confirm}
      </Button>
    </form>
  );
}
