"use client";

/**
 * My profile (design portal-shell, decision 15): name and mobile, notification preferences, the password change
 * (through the session handler, which keeps the new tokens in cookies) and the devices with "sign out this device".
 * On the Settings template (design portal-ui-redesign, decision 26): the four groups as a sub-menu on the left on
 * laptops and a select on phones, one group at a time (`?group=`), so each screen has at most one primary button.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { PreferenceFields, prefsBody, prefsFrom, type PrefsValue } from "@/components/auth/WelcomeForms";
import { Badge, Button, ErrorBanner, Loading, Notice, PageHeader, SettingsLayout, DataTable, TextField } from "@/components/ui";
import { api, session } from "@/lib/api/client";
import type { DeviceOut, NotificationPreferences, ProfileOut } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";
import { useAction } from "@/lib/useAction";

export const PROFILE_GROUPS = ["details", "notifications", "password", "devices"] as const;
export type ProfileGroup = (typeof PROFILE_GROUPS)[number];

const GROUP_LABELS: Record<ProfileGroup, string> = {
  details: T.profile.details,
  notifications: T.profile.notifications,
  password: T.profile.password,
  devices: T.profile.devices,
};

export function ProfilePage({ params = {} }: { params?: Params }) {
  const profile = useQuery({ queryKey: ["me", "profile"], queryFn: () => api<ProfileOut>("/me/profile") });
  const group: ProfileGroup = (PROFILE_GROUPS as readonly string[]).includes(params.group ?? "")
    ? (params.group as ProfileGroup)
    : "details";
  if (profile.isPending) return <Loading />;
  if (profile.error || !profile.data) return <ErrorBanner error={profile.error} onRetry={() => profile.refetch()} />;
  return (
    <div className="stack">
      <PageHeader title={T.profile.title} />
      <SettingsLayout
        label={T.profile.groups}
        selectLabel={T.profile.group}
        items={PROFILE_GROUPS.map((g) => ({
          key: g,
          label: GROUP_LABELS[g],
          href: g === "details" ? "/profile" : `/profile?group=${g}`,
          active: g === group,
        }))}
      >
        {group === "details" ? <DetailsCard profile={profile.data} /> : null}
        {group === "notifications" ? <PreferencesCard profile={profile.data} /> : null}
        {group === "password" ? <PasswordCard /> : null}
        {group === "devices" ? <DevicesCard /> : null}
      </SettingsLayout>
    </div>
  );
}

function DetailsCard({ profile }: { profile: ProfileOut }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(profile.full_name);
  const [mobile, setMobile] = useState(profile.mobile ?? "");
  const save = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const out = await save.run(() =>
      api<ProfileOut>("/me/profile", { method: "PATCH", body: { full_name: name.trim(), mobile: mobile.trim() } }),
    );
    if (out.ok) {
      queryClient.setQueryData(["me", "profile"], out.value);
      await queryClient.invalidateQueries({ queryKey: ["me"], exact: true });
    }
  }

  return (
    <form className="card stack" onSubmit={submit} aria-label={T.profile.details}>
      <h2>{T.profile.details}</h2>
      <TextField label={T.auth.email} value={profile.email} readOnly disabled />
      <TextField label={T.auth.fullName} required value={name} onChange={(e) => setName(e.target.value)} />
      <TextField label={T.auth.mobile} type="tel" hint={T.auth.mobileHint} required value={mobile} onChange={(e) => setMobile(e.target.value)} />
      <ErrorBanner error={save.error} />
      {save.done ? <Notice>{T.saved}</Notice> : null}
      <div>
        <Button type="submit" busy={save.busy}>
          {T.save}
        </Button>
      </div>
    </form>
  );
}

function PreferencesCard({ profile }: { profile: ProfileOut }) {
  const [prefs, setPrefs] = useState<PrefsValue>(() => prefsFrom(profile));
  const save = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const out = await save.run(() =>
      api<NotificationPreferences>("/me/notification-preferences", { method: "PUT", body: prefsBody(prefs) }),
    );
    if (out.ok) setPrefs(prefsFrom({ notification_preferences: out.value }));
  }

  return (
    <form className="card stack" onSubmit={submit} aria-label={T.prefs.title}>
      <PreferenceFields value={prefs} onChange={setPrefs} />
      <ErrorBanner error={save.error} />
      {save.done ? <Notice>{T.saved}</Notice> : null}
      <div>
        <Button type="submit" busy={save.busy}>
          {T.save}
        </Button>
      </div>
    </form>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const save = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== repeat) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    const out = await save.run(() => session("password", { current_password: current, new_password: password }));
    if (out.ok) {
      setCurrent("");
      setPassword("");
      setRepeat("");
    }
  }

  return (
    <form className="card stack" onSubmit={submit} aria-label={T.profile.password}>
      <h2>{T.profile.password}</h2>
      <TextField label={T.auth.currentPassword} type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
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
      <ErrorBanner error={save.error} />
      {save.done ? <Notice>{T.profile.passwordChanged}</Notice> : null}
      <div>
        <Button type="submit" busy={save.busy}>
          {T.auth.setPassword}
        </Button>
      </div>
    </form>
  );
}

function DevicesCard() {
  const devices = useQuery({ queryKey: ["me", "devices"], queryFn: () => api<DeviceOut[]>("/me/devices") });
  const action = useAction();

  async function revoke(id: string) {
    const out = await action.run(() => api(`/me/devices/${id}/revoke`, { method: "POST" }));
    if (out.ok) await devices.refetch();
  }

  return (
    <section className="card stack" aria-label={T.profile.devices}>
      <h2>{T.profile.devices}</h2>
      {devices.isPending ? <Loading /> : null}
      <ErrorBanner error={devices.error ?? action.error} onRetry={() => devices.refetch()} />
      {devices.data ? (
        <DataTable
          caption={T.profile.devices}
          rows={devices.data}
          rowKey={(d) => d.id}
          columns={[
            {
              key: "device",
              header: T.profile.devices,
              primary: true,
              cell: (d) => (
                <>
                  {d.label ?? d.user_agent ?? "—"}
                  {d.current ? (
                    <>
                      {" "}
                      <Badge>{T.profile.thisDevice}</Badge>
                    </>
                  ) : null}
                </>
              ),
            },
            { key: "seen", header: T.profile.lastSeen, cell: (d) => formatDateTime(d.last_seen_at) },
            {
              key: "signout",
              header: <span className="visually-hidden">{T.profile.signOutDevice}</span>,
              label: T.profile.signOutDevice,
              cell: (d) =>
                d.revoked_at ? (
                  <span className="muted">{T.profile.revoked}</span>
                ) : (
                  <Button variant="link" busy={action.busy} onClick={() => revoke(d.id)}>
                    {T.profile.signOutDevice}
                  </Button>
                ),
            },
          ]}
        />
      ) : null}
    </section>
  );
}
