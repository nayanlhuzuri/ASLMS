"use client";

/**
 * Offices (design portal-shell, decision 15): the tree with active-user counts; create (kind and parent as the
 * placement rules allow, the API refuses the rest; a department-tier office with its head), edit, deactivate (the
 * API's dependency counts shown on 409), reactivate; the department admin and head; the first department admin
 * and the admin swap (super admin, `users.create`).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  CheckField,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  SelectField,
  TextArea,
  TextField,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { labelOf, useLabels, useMe } from "@/lib/api/hooks";
import type { OfficeDetail, OfficeKind, OfficeNode, UserLookup, UserOut } from "@/lib/api/types";
import { can, isSuperAdmin, readsAudit } from "@/lib/can";
import { formatDate, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString } from "@/lib/params";
import { useAction } from "@/lib/useAction";

import { DesignationInput } from "./Users";

export const DEPARTMENT_TIER: readonly string[] = ["department", "central", "advocate_general"];

function TreeItems({ nodes, kinds }: { nodes: OfficeNode[]; kinds: { code: string; label: string }[] | undefined }) {
  return (
    <ul className="tree">
      {nodes.map((n) => (
        <li key={n.id}>
          <Link href={`/admin/offices/${encodeURIComponent(n.code)}`}>{n.name}</Link>{" "}
          <span className="mono muted">{n.code}</span> · {labelOf(kinds, n.kind)} · {T.offices.users(n.users_active)}
          {n.is_active === false ? (
            <>
              {" "}
              <Badge tone="warning">{T.inactive}</Badge>
            </>
          ) : null}
          {n.children && n.children.length > 0 ? <TreeItems nodes={n.children} kinds={kinds} /> : null}
        </li>
      ))}
    </ul>
  );
}

export function OfficesTree() {
  const me = useMe();
  const labels = useLabels();
  const [inactive, setInactive] = useState(false);
  const tree = useQuery({
    queryKey: ["admin", "offices", "tree", inactive],
    queryFn: () => api<OfficeNode[]>("/admin/offices/tree", { query: { include_inactive: inactive || undefined } }),
  });
  return (
    <section className="stack" aria-label={T.offices.title}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>{T.offices.title}</h2>
        {can(me.data, "offices.manage") ? (
          <Link href="/admin/offices/new" className="button-link">
            {T.offices.newOffice}
          </Link>
        ) : null}
      </div>
      <CheckField label={T.offices.includeInactive} checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
      {tree.isPending ? <Loading /> : null}
      <ErrorBanner error={tree.error} onRetry={() => tree.refetch()} />
      {tree.data ? (
        tree.data.length ? (
          <nav aria-label={T.offices.tree} className="card">
            <TreeItems nodes={tree.data} kinds={labels.data?.office_kinds} />
          </nav>
        ) : (
          <EmptyState>{T.none}</EmptyState>
        )
      ) : null}
    </section>
  );
}

interface HeadDraft {
  email: string;
  full_name: string;
  password: string;
  designation: string;
  mobile: string;
}

const EMPTY_HEAD: HeadDraft = { email: "", full_name: "", password: "", designation: "", mobile: "" };

function headBody(h: HeadDraft) {
  return {
    email: h.email.trim(),
    full_name: h.full_name.trim() || null,
    password: h.password || null,
    designation: h.designation.trim() || null,
    mobile: h.mobile.trim() || null,
  };
}

function HeadFields({ value, onChange }: { value: HeadDraft; onChange: (v: HeadDraft) => void }) {
  return (
    <fieldset className="stack" style={{ border: "1px solid var(--line)", borderRadius: 6, padding: 16 }}>
      <legend>{T.offices.headSection}</legend>
      <div className="row">
        <TextField label={T.users.email} type="email" required value={value.email} onChange={(e) => onChange({ ...value, email: e.target.value })} />
        <TextField label={T.auth.fullName} value={value.full_name} onChange={(e) => onChange({ ...value, full_name: e.target.value })} />
        <TextField
          label={T.users.tempPassword}
          type="password"
          autoComplete="new-password"
          hint={T.users.tempPasswordHint}
          value={value.password}
          onChange={(e) => onChange({ ...value, password: e.target.value })}
        />
        <DesignationInput value={value.designation} onChange={(designation) => onChange({ ...value, designation })} />
        <TextField label={T.users.mobile} type="tel" value={value.mobile} onChange={(e) => onChange({ ...value, mobile: e.target.value })} />
      </div>
    </fieldset>
  );
}

export function NewOfficeForm() {
  const router = useRouter();
  const params = useSearchParams();
  const labels = useLabels();
  const [form, setForm] = useState({ code: "", name: "", kind: "", parent: params.get("parent") ?? "", notes: "", validFrom: "" });
  const [head, setHead] = useState<HeadDraft>(EMPTY_HEAD);
  const save = useAction();
  const needsHead = DEPARTMENT_TIER.includes(form.kind);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const out = await save.run(() =>
      api<OfficeDetail>("/admin/offices", {
        method: "POST",
        body: {
          code: form.code.trim().toUpperCase(),
          name: form.name.trim(),
          kind: form.kind as OfficeKind,
          parent_code: form.parent.trim().toUpperCase(),
          notes: form.notes.trim() || null,
          valid_from: form.validFrom || null,
          head: needsHead ? headBody(head) : null,
        },
      }),
    );
    if (out.ok) router.push(`/admin/offices/${encodeURIComponent(out.value.code)}`);
  }

  return (
    <form className="card stack" onSubmit={submit} aria-label={T.offices.newOffice}>
      <h2>{T.offices.newOffice}</h2>
      <div className="row">
        <TextField label={T.offices.code} required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
        <TextField label={T.offices.name} required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <SelectField
          label={T.offices.kind}
          required
          value={form.kind}
          placeholder=""
          options={(labels.data?.office_kinds ?? []).filter((k) => k.code !== "state").map((k) => ({ value: k.code, label: k.label }))}
          onChange={(e) => setForm({ ...form, kind: e.target.value })}
        />
        <TextField label={T.offices.parent} required value={form.parent} onChange={(e) => setForm({ ...form, parent: e.target.value })} />
        <TextField label={T.offices.validFrom} type="date" value={form.validFrom} onChange={(e) => setForm({ ...form, validFrom: e.target.value })} />
      </div>
      <TextArea label={T.offices.notes} rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      {needsHead ? <HeadFields value={head} onChange={setHead} /> : null}
      <ErrorBanner error={save.error} />
      <div>
        <Button type="submit" busy={save.busy}>
          {T.offices.create}
        </Button>
      </div>
    </form>
  );
}

function InUseCounts({ error }: { error: unknown }) {
  if (!(error instanceof ApiError) || error.status !== 409 || !error.extra.counts) return null;
  const counts = error.extra.counts as Record<string, number>;
  return (
    <div role="alert">
      <p>{T.offices.inUse}</p>
      <ul>
        {Object.entries(counts).map(([k, v]) => (
          <li key={k}>
            {k}: {formatNumber(v)}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function OfficeDetailView({ code }: { code: string }) {
  const me = useMe();
  const labels = useLabels();
  const queryClient = useQueryClient();
  const key = ["admin", "office", code];
  const office = useQuery({ queryKey: key, queryFn: () => api<OfficeDetail>(`/admin/offices/${encodeURIComponent(code)}`) });
  const isDept = !!office.data && DEPARTMENT_TIER.includes(office.data.kind) && office.data.tier === "department";
  const admins = useQuery({
    queryKey: [...key, "admins"],
    queryFn: () => api<UserOut[]>(`/admin/offices/${encodeURIComponent(code)}/admins`),
    enabled: isDept,
  });
  const heads = useQuery({
    queryKey: [...key, "heads"],
    queryFn: () => api<UserOut[]>("/admin/users", { query: { office: code, role: "dept_head" } }),
    enabled: isDept,
  });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: "", notes: "" });
  const [reactivating, setReactivating] = useState(false);
  const [head, setHead] = useState<HeadDraft>(EMPTY_HEAD);
  const action = useAction();
  const manage = can(me.data, "offices.manage");

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin"] });

  if (office.isPending) return <Loading />;
  if (office.error || !office.data) return <ErrorBanner error={office.error} onRetry={() => office.refetch()} />;
  const o = office.data;

  async function saveEdit(e: FormEvent) {
    e.preventDefault();
    const out = await action.run(() =>
      api<OfficeDetail>(`/admin/offices/${encodeURIComponent(code)}`, {
        method: "PATCH",
        body: { name: form.name.trim(), notes: form.notes.trim() || null },
      }),
    );
    if (out.ok) {
      setEditing(false);
      await refresh();
    }
  }

  async function deactivate() {
    const out = await action.run(() => api(`/admin/offices/${encodeURIComponent(code)}/deactivate`, { method: "POST" }));
    if (out.ok) await refresh();
  }

  async function reactivate(e?: FormEvent) {
    e?.preventDefault();
    const out = await action.run(() =>
      api(`/admin/offices/${encodeURIComponent(code)}/reactivate`, {
        method: "POST",
        body: isDept ? { head: headBody(head) } : null,
      }),
    );
    if (out.ok) {
      setReactivating(false);
      await refresh();
    }
  }

  return (
    <div className="stack">
      <section className="card stack" aria-label={T.offices.detail}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>
            {o.name} <span className="mono muted">{o.code}</span>
          </h2>
          {o.is_active === false ? <Badge tone="warning">{T.inactive}</Badge> : <Badge tone="success">{T.active}</Badge>}
        </div>
        {editing ? (
          <form className="stack" onSubmit={saveEdit}>
            <TextField label={T.offices.name} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <TextArea label={T.offices.notes} rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            <div className="actions">
              <Button type="submit" busy={action.busy}>
                {T.save}
              </Button>
              <Button variant="secondary" onClick={() => setEditing(false)}>
                {T.cancel}
              </Button>
            </div>
          </form>
        ) : (
          <dl className="facts">
            <dt>{T.offices.kind}</dt>
            <dd>{labelOf(labels.data?.office_kinds, o.kind)}</dd>
            <dt>{T.offices.parent}</dt>
            <dd className="mono">{o.parent_code ?? "—"}</dd>
            <dt>{T.offices.validFrom}</dt>
            <dd>{formatDate(o.valid_from)}</dd>
            <dt>{T.offices.counts}</dt>
            <dd>
              {formatNumber(o.counts.children)} / {formatNumber(o.counts.users)} / {formatNumber(o.counts.ownership)} /{" "}
              {formatNumber(o.counts.custody)}
            </dd>
            {o.notes ? (
              <>
                <dt>{T.offices.notes}</dt>
                <dd>{o.notes}</dd>
              </>
            ) : null}
          </dl>
        )}
        {readsAudit(me.data) ? (
          // design portal-audit-health, decision 7: audit readers only; the API re-checks
          <p>
            <Link href={`/audit${queryString({ office: o.code })}`}>{T.audit.byOffice}</Link>
          </p>
        ) : null}
        <ErrorBanner error={action.error} />
        <InUseCounts error={action.error} />
        {manage ? (
          <div className="actions">
            {!editing ? (
              <Button
                variant="secondary"
                onClick={() => {
                  setForm({ name: o.name, notes: o.notes ?? "" });
                  setEditing(true);
                }}
              >
                {T.edit}
              </Button>
            ) : null}
            <Link href={`/admin/offices/new?parent=${encodeURIComponent(o.code)}`} className="button-link">
              {T.offices.newOffice}
            </Link>
            {o.is_active !== false ? (
              <Button variant="danger" busy={action.busy} onClick={deactivate}>
                {T.offices.deactivate}
              </Button>
            ) : isDept ? (
              <Button onClick={() => setReactivating(true)}>{T.offices.reactivate}</Button>
            ) : (
              <Button busy={action.busy} onClick={() => reactivate()}>
                {T.offices.reactivate}
              </Button>
            )}
          </div>
        ) : null}
      </section>
      {isDept ? (
        <DepartmentPeople
          code={code}
          admins={admins.data}
          heads={heads.data}
          superAdmin={isSuperAdmin(me.data) && can(me.data, "users.create")}
          onChanged={refresh}
        />
      ) : null}
      <Dialog open={reactivating} title={T.offices.reactivate} onClose={() => setReactivating(false)}>
        <form className="stack" onSubmit={reactivate}>
          <HeadFields value={head} onChange={setHead} />
          <ErrorBanner error={action.error} />
          <Button type="submit" busy={action.busy}>
            {T.offices.reactivate}
          </Button>
        </form>
      </Dialog>
    </div>
  );
}

function DepartmentPeople({
  code,
  admins,
  heads,
  superAdmin,
  onChanged,
}: {
  code: string;
  admins: UserOut[] | undefined;
  heads: UserOut[] | undefined;
  superAdmin: boolean;
  onChanged: () => unknown;
}) {
  const [adding, setAdding] = useState(false);
  const [swapping, setSwapping] = useState(false);
  const [person, setPerson] = useState({ email: "", full_name: "", password: "", designation: "", mobile: "" });
  const [outgoing, setOutgoing] = useState<"dept_officer" | "end">("dept_officer");
  const [reason, setReason] = useState("");
  const action = useAction();
  const admin = admins?.[0];

  async function addAdmin(e: FormEvent) {
    e.preventDefault();
    const out = await action.run(() =>
      api(`/admin/offices/${encodeURIComponent(code)}/admins`, {
        method: "POST",
        body: {
          email: person.email.trim(),
          full_name: person.full_name.trim(),
          password: person.password,
          designation: person.designation.trim() || null,
          mobile: person.mobile.trim() || null,
        },
      }),
    );
    if (out.ok) {
      setAdding(false);
      await onChanged();
    }
  }

  async function swap(e: FormEvent) {
    e.preventDefault();
    const out = await action.run(async () => {
      let incoming: Record<string, unknown>;
      try {
        const found = await api<UserLookup>("/admin/users/lookup", { query: { email: person.email.trim() } });
        incoming = { user: found.id, designation: person.designation.trim() || undefined };
      } catch (err) {
        if (!(err instanceof ApiError) || err.status !== 404) throw err;
        incoming = {
          email: person.email.trim(),
          password: person.password,
          full_name: person.full_name.trim(),
          designation: person.designation.trim() || undefined,
          mobile: person.mobile.trim() || undefined,
        };
      }
      return api(`/admin/offices/${encodeURIComponent(code)}/admin`, {
        method: "PUT",
        body: { incoming, outgoing, reason: reason.trim() },
      });
    });
    if (out.ok) {
      setSwapping(false);
      await onChanged();
    }
  }

  const personFields = (
    <div className="row">
      <TextField label={T.offices.incomingEmail} type="email" required value={person.email} onChange={(e) => setPerson({ ...person, email: e.target.value })} />
      <TextField label={T.auth.fullName} value={person.full_name} onChange={(e) => setPerson({ ...person, full_name: e.target.value })} />
      <TextField
        label={T.users.tempPassword}
        type="password"
        autoComplete="new-password"
        hint={T.users.tempPasswordHint}
        value={person.password}
        onChange={(e) => setPerson({ ...person, password: e.target.value })}
      />
      <DesignationInput value={person.designation} onChange={(designation) => setPerson({ ...person, designation })} />
      <TextField label={T.users.mobile} type="tel" value={person.mobile} onChange={(e) => setPerson({ ...person, mobile: e.target.value })} />
    </div>
  );

  return (
    <section className="card stack" aria-label={T.offices.admin}>
      <h2>{T.offices.admin}</h2>
      {admin ? (
        <p>
          <Link href={`/admin/users/${admin.id}`}>{admin.full_name}</Link> · {admin.email}
        </p>
      ) : (
        <p className="muted">{T.offices.noAdmin}</p>
      )}
      <h3>{T.offices.head}</h3>
      {heads && heads.length > 0 ? (
        heads.map((h) => (
          <p key={h.id}>
            <Link href={`/admin/users/${h.id}`}>{h.full_name}</Link> · {h.email}
          </p>
        ))
      ) : (
        <p className="muted">{T.none}</p>
      )}
      {superAdmin ? (
        <div className="actions">
          {!admin ? <Button onClick={() => setAdding(true)}>{T.offices.addAdmin}</Button> : null}
          {admin ? (
            <Button variant="secondary" onClick={() => setSwapping(true)}>
              {T.offices.swapAdmin}
            </Button>
          ) : null}
        </div>
      ) : null}
      <Dialog open={adding} title={T.offices.addAdmin} onClose={() => setAdding(false)}>
        <form className="stack" onSubmit={addAdmin}>
          {personFields}
          <ErrorBanner error={action.error} />
          <Button type="submit" busy={action.busy}>
            {T.save}
          </Button>
        </form>
      </Dialog>
      <Dialog open={swapping} title={T.offices.swapAdmin} onClose={() => setSwapping(false)}>
        <form className="stack" onSubmit={swap}>
          {personFields}
          <SelectField
            label={T.offices.outgoing}
            value={outgoing}
            options={[
              { value: "dept_officer", label: T.offices.outgoingOfficer },
              { value: "end", label: T.offices.outgoingEnd },
            ]}
            onChange={(e) => setOutgoing(e.target.value as "dept_officer" | "end")}
          />
          <TextArea label={T.offices.reason} required rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          <ErrorBanner error={action.error} />
          <Button type="submit" busy={action.busy} disabled={reason.trim().length < 3}>
            {T.save}
          </Button>
        </form>
      </Dialog>
    </section>
  );
}
