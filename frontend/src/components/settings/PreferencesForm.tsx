"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Preference, PreferenceIn } from "@/lib/types";
import { Button } from "../ui/Button";
import { Check, Fieldset, Radio } from "../ui/Field";
import { ErrorState, Loading } from "../ui/States";
import { useToast } from "../ui/Toast";

export interface PrefState {
  email: boolean;
  digest: "none" | "daily";
  sms: boolean;
}

export function toPayload(p: PrefState): PreferenceIn[] {
  return [
    { channel: "in_app", enabled: true, digest: "none", critical_only: false },
    { channel: "email", enabled: p.email, digest: p.email ? p.digest : "none", critical_only: false },
    { channel: "sms", enabled: p.sms, digest: "none", critical_only: true },
  ];
}

function fromPrefs(list: Preference[]): PrefState {
  const email = list.find((x) => x.channel === "email");
  const sms = list.find((x) => x.channel === "sms");
  return {
    email: email?.enabled ?? true,
    digest: email?.digest === "daily" ? "daily" : "none",
    sms: sms?.enabled ?? false,
  };
}

/** Alert preferences. With `onChange`, the parent saves; otherwise the form has its own Save button. */
export function PreferencesForm({ onChange }: { onChange?: (p: PrefState) => void }) {
  const [state, setState] = useState<PrefState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api
      .get<Preference[]>("/me/preferences")
      .then((p) => {
        const s = fromPrefs(p);
        setState(s);
        onChange?.(s);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load preferences."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <ErrorState message={error} />;
  if (!state) return <Loading label="Loading preferences" />;

  const update = (patch: Partial<PrefState>) => {
    const next = { ...state, ...patch };
    setState(next);
    onChange?.(next);
  };

  const save = async () => {
    setBusy(true);
    try {
      await api.put("/me/preferences", toPayload(state));
      toast.success("Notification preferences saved.");
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Check label="In the portal (always on)" checked disabled readOnly />
      <Check label="By e-mail" checked={state.email} onChange={(e) => update({ email: e.target.checked })} />
      {state.email ? (
        <div style={{ paddingLeft: 28 }}>
          <Fieldset legend="E-mail delivery">
            <Radio name="digest" label="Each alert as it happens" checked={state.digest === "none"} onChange={() => update({ digest: "none" })} />
            <Radio name="digest" label="One daily digest" checked={state.digest === "daily"} onChange={() => update({ digest: "daily" })} />
          </Fieldset>
        </div>
      ) : null}
      <Check
        label="By SMS, for critical alerts only (hearing within 48 hours)"
        checked={state.sms}
        onChange={(e) => update({ sms: e.target.checked })}
      />
      {!onChange ? (
        <div>
          <Button variant="primary" onClick={save} busy={busy}>
            Save preferences
          </Button>
        </div>
      ) : null}
    </div>
  );
}
