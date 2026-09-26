"use client";

import { useState, type FormEvent } from "react";
import { PreferencesForm } from "@/components/settings/PreferencesForm";
import { OfficeFacts, ProfileForm } from "@/components/settings/ProfileForm";
import { useMe } from "@/components/shell/MeContext";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";
import { Card, CardHead, PageHeader } from "@/components/ui/Layout";
import { ErrorState } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

function PasswordForm() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (pw !== pw2) {
      setError("The two new passwords do not match.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await api.post("/me/password", { current_password: current, new_password: pw });
      setCurrent("");
      setPw("");
      setPw2("");
      toast.success("Password changed.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 420 }}>
      {error ? <ErrorState message={error} /> : null}
      <Field label="Current password">
        <TextInput type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
      </Field>
      <Field label="New password" hint="At least 10 characters, with letters and digits.">
        <TextInput type="password" autoComplete="new-password" required minLength={10} value={pw} onChange={(e) => setPw(e.target.value)} />
      </Field>
      <Field label="Repeat the new password">
        <TextInput type="password" autoComplete="new-password" required minLength={10} value={pw2} onChange={(e) => setPw2(e.target.value)} />
      </Field>
      <div>
        <Button type="submit" variant="primary" busy={busy}>
          Change password
        </Button>
      </div>
    </form>
  );
}

export default function SettingsPage() {
  const { me } = useMe();
  return (
    <>
      <PageHeader title="Settings" sub={me.last_login_at ? `Last sign-in ${fmtDateTime(me.last_login_at)}` : undefined} />
      <div style={{ display: "grid", gap: 18, gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))", alignItems: "start" }}>
        <Card labelledBy="set-profile">
          <CardHead id="set-profile" title="Profile" />
          <OfficeFacts me={me} />
          <ProfileForm />
        </Card>
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <Card labelledBy="set-alerts">
            <CardHead id="set-alerts" title="Notifications" />
            <PreferencesForm />
          </Card>
          <Card labelledBy="set-pw">
            <CardHead id="set-pw" title="Change password" />
            <PasswordForm />
          </Card>
        </div>
      </div>
    </>
  );
}
