"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "@/lib/api";
import { roleLabel } from "@/lib/roles";
import type { Me } from "@/lib/types";
import { useMe } from "../shell/MeContext";
import { Button } from "../ui/Button";
import { Field, FormRow, TextInput } from "../ui/Field";
import { KV } from "../ui/Layout";
import { useToast } from "../ui/Toast";

export interface ProfileValues {
  full_name: string;
  designation: string;
  mobile: string;
}

export function ProfileFields({ values, onChange }: { values: ProfileValues; onChange: (v: ProfileValues) => void }) {
  return (
    <>
      <FormRow>
        <Field label="Full name">
          <TextInput required autoComplete="name" value={values.full_name} onChange={(e) => onChange({ ...values, full_name: e.target.value })} />
        </Field>
        <Field label="Designation">
          <TextInput autoComplete="organization-title" value={values.designation} onChange={(e) => onChange({ ...values, designation: e.target.value })} />
        </Field>
      </FormRow>
      <Field label="Mobile number" hint="Used for SMS alerts on critical hearings.">
        <TextInput
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          value={values.mobile}
          onChange={(e) => onChange({ ...values, mobile: e.target.value })}
          style={{ maxWidth: 280 }}
        />
      </Field>
    </>
  );
}

export function OfficeFacts({ me }: { me: Me }) {
  return (
    <KV
      items={[
        { label: "E-mail", value: me.email },
        { label: "Office", value: me.office.name },
        { label: "Department", value: me.department?.name ?? "-" },
        { label: "Role", value: roleLabel(me.role) },
      ]}
    />
  );
}

export function initialProfile(me: Me): ProfileValues {
  return { full_name: me.full_name, designation: me.designation ?? "", mobile: me.mobile ?? "" };
}

export function ProfileForm({ footer }: { footer?: ReactNode }) {
  const { me, setMe } = useMe();
  const [values, setValues] = useState<ProfileValues>(() => initialProfile(me));
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const updated = await api.patch<Me>("/me", {
        full_name: values.full_name.trim(),
        designation: values.designation.trim() || null,
        mobile: values.mobile.trim() || null,
      });
      setMe(updated);
      toast.success("Profile saved.");
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <ProfileFields values={values} onChange={setValues} />
      <div>
        <Button type="submit" variant="primary" busy={busy}>
          Save profile
        </Button>
      </div>
      {footer}
    </form>
  );
}
