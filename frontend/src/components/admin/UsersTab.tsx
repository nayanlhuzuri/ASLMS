"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { ALL_ROLES, isOperator, roleLabel, type Role } from "@/lib/roles";
import type { Me, Office, Page, User } from "@/lib/types";
import { useOffices } from "../shell/MeContext";
import { Button } from "../ui/Button";
import { Dialog, DialogButtons } from "../ui/Dialog";
import { Check, Field, FormRow, Select, TextInput } from "../ui/Field";
import { Pagination } from "../ui/Pagination";
import { Pill } from "../ui/Pill";
import { Async, Empty } from "../ui/States";
import { DataTable } from "../ui/Table";
import { useToast } from "../ui/Toast";
import { OfficeSelect, officeName } from "./common";

/** Roles a department administrator may grant; the central operator may grant any. */
const DEPT_ROLES: Role[] = ["dept_head", "dept_admin", "dept_officer", "directorate_user", "referral_reviewer", "standing_counsel"];

function scopeOffices(me: Me, offices: Office[]): Office[] {
  const active = offices.filter((o) => o.is_active);
  if (isOperator(me)) return active;
  const d = me.department;
  return d ? active.filter((o) => o.path === d.path || o.path.startsWith(`${d.path}/`)) : [];
}

function RoleSelect({ value, onChange, roles }: { value: string; onChange: (v: string) => void; roles: Role[] }) {
  return (
    <Field label="Role">
      <Select value={value} onChange={(e) => onChange(e.target.value)} required>
        <option value="">Choose a role</option>
        {roles.map((r) => (
          <option key={r} value={r}>
            {roleLabel(r)}
          </option>
        ))}
      </Select>
    </Field>
  );
}

function CreateUserDialog({ open, me, onClose, onDone }: { open: boolean; me: Me; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const { offices } = useOffices();
  const roles = isOperator(me) ? ALL_ROLES : DEPT_ROLES;
  const blank = { email: "", full_name: "", designation: "", mobile: "", office_id: me.department?.id ?? "", role: "", password: "" };
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/users", {
        email: f.email.trim(),
        full_name: f.full_name.trim(),
        office_id: f.office_id,
        role: f.role,
        password: f.password,
        designation: f.designation.trim() || null,
        mobile: f.mobile.trim() || null,
      });
      toast.success(`Account created for ${f.full_name.trim()}. They confirm their profile at first sign-in.`);
      setF(blank);
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Create an account" wide onSubmit={submit} footer={<DialogButtons submitLabel="Create account" busy={busy} onCancel={onClose} />}>
      <FormRow>
        <Field label="Full name">
          <TextInput required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
        </Field>
        <Field label="E-mail">
          <TextInput type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        </Field>
      </FormRow>
      <FormRow>
        <Field label="Designation">
          <TextInput value={f.designation} onChange={(e) => setF({ ...f, designation: e.target.value })} />
        </Field>
        <Field label="Mobile">
          <TextInput type="tel" value={f.mobile} onChange={(e) => setF({ ...f, mobile: e.target.value })} />
        </Field>
      </FormRow>
      <FormRow>
        <OfficeSelect label="Office" value={f.office_id} onChange={(v) => setF({ ...f, office_id: v })} offices={scopeOffices(me, offices)} required />
        <RoleSelect value={f.role} onChange={(v) => setF({ ...f, role: v })} roles={roles} />
      </FormRow>
      <Field label="Initial password" hint="At least 10 characters, with letters and digits. Share it securely; the user can change it in Settings.">
        <TextInput type="password" autoComplete="new-password" required minLength={10} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
      </Field>
    </Dialog>
  );
}

function EditUserDialog({ user, me, onClose, onDone }: { user: User | null; me: Me; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const { offices } = useOffices();
  const roles = isOperator(me) ? ALL_ROLES : DEPT_ROLES;
  const [f, setF] = useState<{ full_name: string; designation: string; mobile: string; office_id: string; role: string; is_active: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastId, setLastId] = useState<string | null>(null);

  if (user && user.id !== lastId) {
    setLastId(user.id);
    setF({
      full_name: user.full_name,
      designation: user.designation ?? "",
      mobile: user.mobile ?? "",
      office_id: user.office_id,
      role: user.role,
      is_active: user.is_active,
    });
  }

  const submit = async () => {
    if (!user || !f) return;
    setBusy(true);
    try {
      await api.patch(`/users/${user.id}`, {
        full_name: f.full_name.trim(),
        designation: f.designation.trim() || null,
        mobile: f.mobile.trim() || null,
        office_id: f.office_id,
        role: f.role,
        is_active: f.is_active,
      });
      toast.success("Account updated.");
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    setLastId(null);
    onClose();
  };

  return (
    <Dialog open={user !== null} onClose={close} title="Edit account" description={user?.email} wide onSubmit={submit} footer={<DialogButtons submitLabel="Save" busy={busy} onCancel={close} />}>
      {f ? (
        <>
          <FormRow>
            <Field label="Full name">
              <TextInput required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
            </Field>
            <Field label="Designation">
              <TextInput value={f.designation} onChange={(e) => setF({ ...f, designation: e.target.value })} />
            </Field>
          </FormRow>
          <FormRow>
            <OfficeSelect label="Office" value={f.office_id} onChange={(v) => setF({ ...f, office_id: v })} offices={scopeOffices(me, offices)} required />
            <RoleSelect value={f.role} onChange={(v) => setF({ ...f, role: v })} roles={roles.includes(f.role as Role) ? roles : [...roles, f.role as Role]} />
          </FormRow>
          <Field label="Mobile">
            <TextInput type="tel" value={f.mobile} onChange={(e) => setF({ ...f, mobile: e.target.value })} style={{ maxWidth: 280 }} />
          </Field>
          <Check label="Account is active" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />
        </>
      ) : null}
    </Dialog>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: User | null; onClose: () => void }) {
  const toast = useToast();
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const close = () => {
    setPw("");
    onClose();
  };
  const submit = async () => {
    if (!user) return;
    setBusy(true);
    try {
      await api.patch(`/users/${user.id}`, { password: pw });
      toast.success(`Password reset for ${user.full_name}.`);
      close();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={user !== null}
      onClose={close}
      title="Reset password"
      description={user ? `Set a new password for ${user.full_name}. Share it securely.` : undefined}
      onSubmit={submit}
      footer={<DialogButtons submitLabel="Reset password" busy={busy} onCancel={close} />}
    >
      <Field label="New password" hint="At least 10 characters, with letters and digits.">
        <TextInput type="password" autoComplete="new-password" required minLength={10} value={pw} onChange={(e) => setPw(e.target.value)} />
      </Field>
    </Dialog>
  );
}

export function UsersTab({ me }: { me: Me }) {
  const { offices, byId } = useOffices();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("");
  const [office, setOffice] = useState("");
  const [page, setPage] = useState(1);
  const list = useApi<Page<User>>("/users", { q: query || undefined, role: role || undefined, office_id: office || undefined, page, size: 25 });
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [resetting, setResetting] = useState<User | null>(null);
  const writable = me.can_admin;

  const search = (e: FormEvent) => {
    e.preventDefault();
    setQuery(q.trim());
    setPage(1);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <form role="search" onSubmit={search} style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
          <Field label="Name or e-mail">
            <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} />
          </Field>
          <Button type="submit" icon="search">
            Search
          </Button>
        </form>
        <Field label="Role">
          <Select
            value={role}
            onChange={(e) => {
              setRole(e.target.value);
              setPage(1);
            }}
          >
            <option value="">Any role</option>
            {ALL_ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </Select>
        </Field>
        <OfficeSelect
          label="Office"
          value={office}
          onChange={(v) => {
            setOffice(v);
            setPage(1);
          }}
          offices={scopeOffices(me, offices)}
          placeholder="Any office"
        />
        <div style={{ flexGrow: 1 }} />
        {writable ? (
          <Button variant="primary" icon="user" onClick={() => setCreating(true)}>
            Create account
          </Button>
        ) : null}
      </div>
      <Async state={list} loadingLabel="Loading accounts">
        {(p) =>
          p.items.length === 0 ? (
            <Empty title="No accounts match" center />
          ) : (
            <>
              <DataTable
                caption="Accounts"
                rows={p.items}
                rowKey={(u) => u.id}
                columns={[
                  {
                    key: "name",
                    header: "Name",
                    render: (u) => (
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <strong>{u.full_name}</strong>
                        <span className="muted" style={{ fontSize: 13 }}>
                          {u.email}
                        </span>
                      </div>
                    ),
                  },
                  { key: "designation", header: "Designation", render: (u) => u.designation || "-" },
                  { key: "office", header: "Office", render: (u) => officeName(byId, u.office_id) },
                  { key: "role", header: "Role", render: (u) => roleLabel(u.role) },
                  {
                    key: "status",
                    header: "Status",
                    render: (u) =>
                      !u.is_active ? <Pill tone="muted">Disabled</Pill> : u.must_confirm_profile ? <Pill tone="warning">Not yet confirmed</Pill> : <Pill tone="success">Active</Pill>,
                  },
                  { key: "last", header: "Last sign-in", render: (u) => fmtDateTime(u.last_login_at, "Never") },
                  {
                    key: "act",
                    header: "",
                    actions: true,
                    render: (u) =>
                      writable ? (
                        <span style={{ display: "inline-flex", gap: 4 }}>
                          <Button variant="link" small onClick={() => setEditing(u)}>
                            Edit<span className="sr-only"> {u.full_name}</span>
                          </Button>
                          <Button variant="link" small onClick={() => setResetting(u)}>
                            Reset password<span className="sr-only"> for {u.full_name}</span>
                          </Button>
                        </span>
                      ) : null,
                  },
                ]}
              />
              <Pagination page={p.page} size={p.size} total={p.total} onPage={setPage} noun="accounts" />
            </>
          )
        }
      </Async>
      {writable ? (
        <>
          <CreateUserDialog
            open={creating}
            me={me}
            onClose={() => setCreating(false)}
            onDone={() => {
              setCreating(false);
              list.reload();
            }}
          />
          <EditUserDialog
            user={editing}
            me={me}
            onClose={() => setEditing(null)}
            onDone={() => {
              setEditing(null);
              list.reload();
            }}
          />
          <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
        </>
      ) : null}
    </div>
  );
}
