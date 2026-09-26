"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { PreferencesForm, toPayload, type PrefState } from "@/components/settings/PreferencesForm";
import { initialProfile, OfficeFacts, ProfileFields, type ProfileValues } from "@/components/settings/ProfileForm";
import { useMe } from "@/components/shell/MeContext";
import { Button } from "@/components/ui/Button";
import { Card, CardHead, Notice, PageHeader } from "@/components/ui/Layout";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";

export default function WelcomePage() {
  const { me, setMe } = useMe();
  const router = useRouter();
  const toast = useToast();
  const [profile, setProfile] = useState<ProfileValues>(() => initialProfile(me));
  const [prefs, setPrefs] = useState<PrefState | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.patch<Me>("/me", {
        full_name: profile.full_name.trim(),
        designation: profile.designation.trim() || null,
        mobile: profile.mobile.trim() || null,
      });
      if (prefs) await api.put("/me/preferences", toPayload(prefs));
      const confirmed = await api.post<Me>("/me/confirm-profile");
      setMe(confirmed);
      toast.success("Profile confirmed. Welcome to the portal.");
      router.replace("/");
    } catch (err) {
      toast.error(err);
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 22, maxWidth: 820 }}>
      <PageHeader title={`Welcome, ${me.full_name}`} sub="Confirm your details and choose how you want to be alerted." />
      <Notice>Your department&apos;s cases are already here. The portal collects cause lists, hearings and orders from the High Court every day.</Notice>
      <Card labelledBy="w-profile">
        <CardHead id="w-profile" title="Your details" />
        <ProfileFields values={profile} onChange={setProfile} />
      </Card>
      <Card labelledBy="w-office">
        <CardHead id="w-office" title="Office and role" />
        <OfficeFacts me={me} />
        <p className="muted" style={{ fontSize: 13 }}>
          Your office and role are set by your department administrator. Ask them if either is wrong.
        </p>
      </Card>
      <Card labelledBy="w-alerts">
        <CardHead id="w-alerts" title="Alerts" />
        <PreferencesForm onChange={setPrefs} />
      </Card>
      <div>
        <Button type="submit" variant="primary" busy={busy}>
          Confirm and continue
        </Button>
      </div>
    </form>
  );
}
