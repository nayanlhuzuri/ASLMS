"use client";

/**
 * User detail (design portal-shell, decision 15): the login (name, e-mail correction, mobile), enable / disable, a
 * temporary password, the memberships (add, change designation or type, make primary, end with the exit dialog,
 * reactivate), each membership's functions with grant / deny overrides and the orders linked to a membership. Each
 * action shows only with its function; the API decides (scope, delegation, reserved functions).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  CaseLink,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  SelectField,
  Table,
  TextArea,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { labelOf, useLabels, useMe } from "@/lib/api/hooks";
import type {
  ExitPreview,
  Me,
  MembershipDocument,
  MembershipFunctions,
  MembershipOut,
  Permission,
  PermissionInfo,
  Role,
  UserOut,
  UserTypeLabel,
} from "@/lib/api/types";
import { can, canAny, readsAudit } from "@/lib/can";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString } from "@/lib/params";
import { useAction } from "@/lib/useAction";

import a from "./admin.module.css";

import { assignableOptions, DesignationInput, MembershipFields, type MembershipDraft } from "./Users";

function userKey(id: string) {
  return ["admin", "user", id] as const;
}

export function UserDetail({ id }: { id: string }) {
  const me = useMe();
  const labels = useLabels();
  const user = useQuery({ queryKey: userKey(id), queryFn: () => api<UserOut>(`/admin/users/${id}`) });
  const memberships = useQuery({
    queryKey: [...userKey(id), "memberships"],
    queryFn: () => api<MembershipOut[]>(`/admin/users/${id}/memberships`, { query: { include_ended: true } }),
  });
  if (user.isPending || me.isPending) return <Loading />;
  if (user.error || !user.data || !me.data) return <ErrorBanner error={user.error ?? me.error} onRetry={() => user.refetch()} />;
  return (
    <div className="stack">
      <LoginCard user={user.data} me={me.data} />
      <section className="card stack" aria-label={T.users.memberships}>
        <h2>{T.users.memberships}</h2>
        {memberships.isPending ? <Loading /> : null}
        <ErrorBanner error={memberships.error} onRetry={() => memberships.refetch()} />
        {memberships.data ? (
          <MembershipTable user={user.data} memberships={memberships.data} me={me.data} types={labels.data?.user_types} />
        ) : null}
        {can(me.data, "users.create") ? <AddMembership userId={id} types={labels.data?.user_types} /> : null}
      </section>
    </div>
  );
}

function useRefreshUser(id: string) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: userKey(id) });
}

function LoginCard({ user, me }: { user: UserOut; me: Me }) {
  const refresh = useRefreshUser(user.id);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ full_name: user.full_name, email: user.email, mobile: user.mobile ?? "" });
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [password, setPassword] = useState("");
  const save = useAction();
  const toggle = useAction();
  const reset = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, string | null> = {};
    if (form.full_name.trim() !== user.full_name) body.full_name = form.full_name.trim();
    if (form.email.trim().toLowerCase() !== user.email) body.email = form.email.trim();
    if ((form.mobile.trim() || null) !== (user.mobile ?? null)) body.mobile = form.mobile.trim() || null;
    const out = await save.run(() => api<UserOut>(`/admin/users/${user.id}`, { method: "PATCH", body }));
    if (out.ok) {
      setEditing(false);
      await refresh();
    }
  }

  async function setEnabled(enabled: boolean) {
    const out = await toggle.run(() =>
      api<UserOut>(`/admin/users/${user.id}/${enabled ? "enable" : "disable"}`, { method: "POST" }),
    );
    if (out.ok) await refresh();
  }

  async function setTemporary(e: FormEvent) {
    e.preventDefault();
    const out = await reset.run(() => api(`/admin/users/${user.id}/password`, { method: "POST", body: { password } }));
    if (out.ok) setPassword("");
  }

  return (
    <section className="card stack" aria-label={T.users.login}>
      <div className={a.groupHead}>
        <h2>{user.full_name}</h2>
        {user.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge tone="danger">{T.users.disabled}</Badge>}
      </div>
      {editing ? (
        <form className="stack" onSubmit={submit}>
          <div className="row">
            <TextField label={T.auth.fullName} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            <TextField label={T.users.email} type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <TextField label={T.users.mobile} type="tel" value={form.mobile} onChange={(e) => setForm({ ...form, mobile: e.target.value })} />
          </div>
          <ErrorBanner error={save.error} />
          <div className="actions">
            <Button type="submit" busy={save.busy}>
              {T.save}
            </Button>
            <Button variant="secondary" onClick={() => setEditing(false)}>
              {T.cancel}
            </Button>
          </div>
        </form>
      ) : (
        <dl className="facts">
          <dt>{T.users.email}</dt>
          <dd>{user.email}</dd>
          <dt>{T.users.mobile}</dt>
          <dd>{user.mobile ?? "—"}</dd>
          <dt>{T.users.lastLogin}</dt>
          <dd>{formatDateTime(user.last_login_at)}</dd>
        </dl>
      )}
      {readsAudit(me) ? (
        // design portal-audit-health, decision 7: audit readers only; the API re-checks
        <nav className="actions" aria-label={T.audit.links}>
          <Link href={`/audit${queryString({ user: user.id })}`}>{T.audit.byUser}</Link>
          <Link href={`/audit${queryString({ about_user: user.id })}`}>{T.audit.aboutThisUser}</Link>
        </nav>
      ) : null}
      <ErrorBanner error={toggle.error} />
      <div className="actions">
        {can(me, "users.edit") && !editing ? (
          <Button variant="secondary" onClick={() => setEditing(true)}>
            {T.edit}
          </Button>
        ) : null}
        {can(me, "users.enable_disable") ? (
          user.is_active ? (
            <Button variant="danger" busy={toggle.busy} onClick={() => setEnabled(false)}>
              {T.users.disable}
            </Button>
          ) : (
            <Button variant="secondary" busy={toggle.busy} onClick={() => setEnabled(true)}>
              {T.users.enable}
            </Button>
          )
        ) : null}
        {can(me, "users.reset_password") ? (
          <Button variant="secondary" onClick={() => setPasswordOpen(true)}>
            {T.users.setPassword}
          </Button>
        ) : null}
      </div>
      <Dialog open={passwordOpen} title={T.users.setPassword} onClose={() => setPasswordOpen(false)}>
        <form className="stack" onSubmit={setTemporary}>
          <TextField
            label={T.users.tempPassword}
            type="password"
            autoComplete="new-password"
            hint={T.users.tempPasswordHint}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <ErrorBanner error={reset.error} />
          {reset.done ? <Notice>{T.users.passwordSet}</Notice> : null}
          <Button type="submit" busy={reset.busy}>
            {T.save}
          </Button>
        </form>
      </Dialog>
    </section>
  );
}

function MembershipTable({
  user,
  memberships,
  me,
  types,
}: {
  user: UserOut;
  memberships: MembershipOut[];
  me: Me;
  types: UserTypeLabel[] | undefined;
}) {
  const refresh = useRefreshUser(user.id);
  const [changing, setChanging] = useState<MembershipOut | null>(null);
  const [ending, setEnding] = useState<MembershipOut | null>(null);
  const [functionsOf, setFunctionsOf] = useState<string | null>(null);
  const [documentsOf, setDocumentsOf] = useState<string | null>(null);
  const action = useAction();
  if (memberships.length === 0) return <EmptyState>{T.users.noMembership}</EmptyState>;

  async function makePrimary(m: MembershipOut) {
    const out = await action.run(() =>
      api(`/admin/users/${user.id}/primary-membership`, { method: "PUT", body: { membership: m.id } }),
    );
    if (out.ok) await refresh();
  }

  async function reactivate(m: MembershipOut) {
    const out = await action.run(() => api(`/admin/users/${user.id}/memberships/${m.id}/reactivate`, { method: "POST" }));
    if (out.ok) await refresh();
  }

  return (
    <>
      <ErrorBanner error={action.error} />
      <Table caption={T.users.memberships}>
        <thead>
          <tr>
            <th scope="col">{T.offices.name}</th>
            <th scope="col">{T.users.designation}</th>
            <th scope="col">{T.users.type}</th>
            <th scope="col">{T.users.status}</th>
            <th scope="col">
              <span className="visually-hidden">{T.users.change}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {memberships.map((m) => {
            const active = m.is_active !== false;
            return (
              <tr key={m.id}>
                <td>
                  {m.office.name} <span className="mono muted">{m.office.code}</span>
                  {m.is_primary ? (
                    <>
                      {" "}
                      <Badge>{T.shell.primary}</Badge>
                    </>
                  ) : null}
                </td>
                <td>{m.designation ?? "—"}</td>
                <td>{labelOf(types, m.role)}</td>
                <td>{active ? T.active : `${T.users.ended} ${formatDate(m.valid_to)}`}</td>
                <td>
                  <div className="actions">
                    {active && canAny(me, ["users.edit", "users.set_type"]) ? (
                      <Button variant="link" onClick={() => setChanging(m)}>
                        {T.users.change}
                      </Button>
                    ) : null}
                    {active && !m.is_primary && can(me, "users.edit") ? (
                      <Button variant="link" busy={action.busy} onClick={() => makePrimary(m)}>
                        {T.users.makePrimary}
                      </Button>
                    ) : null}
                    {active && can(me, "users.enable_disable") ? (
                      <Button variant="link" onClick={() => setEnding(m)}>
                        {T.users.end}
                      </Button>
                    ) : null}
                    {!active && can(me, "users.enable_disable") ? (
                      <Button variant="link" busy={action.busy} onClick={() => reactivate(m)}>
                        {T.users.reactivate}
                      </Button>
                    ) : null}
                    {can(me, "users.view") ? (
                      <Button
                        variant="link"
                        aria-expanded={functionsOf === m.id}
                        onClick={() => setFunctionsOf(functionsOf === m.id ? null : m.id)}
                      >
                        {T.users.showFunctions}
                      </Button>
                    ) : null}
                    {canAny(me, ["users.propose_head", "admin.tickets"]) ? (
                      <Button
                        variant="link"
                        aria-expanded={documentsOf === m.id}
                        onClick={() => setDocumentsOf(documentsOf === m.id ? null : m.id)}
                      >
                        {T.users.documents}
                      </Button>
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </Table>
      {functionsOf ? <MembershipFunctionsPanel userId={user.id} membershipId={functionsOf} me={me} /> : null}
      {documentsOf ? <MembershipDocuments userId={user.id} membershipId={documentsOf} /> : null}
      {changing ? (
        <ChangeMembership userId={user.id} membership={changing} me={me} types={types} onClose={() => setChanging(null)} />
      ) : null}
      {ending ? <ExitDialog userId={user.id} membership={ending} onClose={() => setEnding(null)} /> : null}
    </>
  );
}

function ChangeMembership({
  userId,
  membership,
  me,
  types,
  onClose,
}: {
  userId: string;
  membership: MembershipOut;
  me: Me;
  types: UserTypeLabel[] | undefined;
  onClose: () => void;
}) {
  const refresh = useRefreshUser(userId);
  const [designation, setDesignation] = useState(membership.designation ?? "");
  const [role, setRole] = useState<string>(membership.role);
  const save = useAction();
  const options = assignableOptions(types);
  if (!options.some((o) => o.value === membership.role)) {
    options.unshift({ value: membership.role, label: labelOf(types, membership.role) });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, string | null> = {};
    if (can(me, "users.edit") && designation.trim() !== (membership.designation ?? "")) body.designation = designation.trim() || null;
    if (can(me, "users.set_type") && role !== membership.role) body.role = role;
    const out = await save.run(() => api(`/admin/users/${userId}/memberships/${membership.id}`, { method: "PATCH", body }));
    if (out.ok) {
      await refresh();
      onClose();
    }
  }

  return (
    <Dialog open title={`${T.users.change}: ${membership.office.name}`} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        {can(me, "users.edit") ? <DesignationInput value={designation} onChange={setDesignation} /> : null}
        {can(me, "users.set_type") ? (
          <SelectField label={T.users.type} value={role} options={options} onChange={(e) => setRole(e.target.value)} />
        ) : null}
        <ErrorBanner error={save.error} />
        <Button type="submit" busy={save.busy}>
          {T.save}
        </Button>
      </form>
    </Dialog>
  );
}

function AddMembership({ userId, types }: { userId: string; types: UserTypeLabel[] | undefined }) {
  const refresh = useRefreshUser(userId);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<MembershipDraft>({ office: "", designation: "", role: "" });
  const save = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const out = await save.run(() =>
      api(`/admin/users/${userId}/memberships`, {
        method: "POST",
        body: { office: draft.office.trim(), designation: draft.designation.trim() || null, role: draft.role as Role },
      }),
    );
    if (out.ok) {
      await refresh();
      setOpen(false);
    }
  }

  return (
    <>
      <div>
        <Button variant="secondary" onClick={() => setOpen(true)}>
          {T.users.addMembership}
        </Button>
      </div>
      <Dialog open={open} title={T.users.addMembership} onClose={() => setOpen(false)}>
        <form className="stack" onSubmit={submit}>
          <MembershipFields value={draft} onChange={setDraft} types={types} />
          <ErrorBanner error={save.error} />
          <Button type="submit" busy={save.busy}>
            {T.save}
          </Button>
        </form>
      </Dialog>
    </>
  );
}

/**
 * The exit dialog (user-memberships, decisions 21-22): the API's preview of every allotted case and held file, a
 * successor chosen for each item, then end. Nothing is submitted until every item has a successor.
 */
export function ExitDialog({
  userId,
  membership,
  onClose,
}: {
  userId: string;
  membership: MembershipOut;
  onClose: () => void;
}) {
  const refresh = useRefreshUser(userId);
  const preview = useQuery({
    queryKey: [...userKey(userId), "exit", membership.id],
    queryFn: () => api<ExitPreview>(`/admin/users/${userId}/memberships/${membership.id}/exit-preview`),
    staleTime: 0,
  });
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const save = useAction();
  const items = preview.data?.items ?? [];
  const missing = items.filter((i) => !choice[i.key]).length;
  const ready = !!preview.data && missing === 0 && reason.trim().length >= 3;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || !preview.data) return;
    const out = await save.run(() =>
      api(`/admin/users/${userId}/memberships/${membership.id}/end`, {
        method: "POST",
        body: {
          reason: reason.trim(),
          items_fingerprint: preview.data.items_fingerprint,
          assignments: items.map((i) => ({ key: i.key, to_membership: choice[i.key] })),
        },
      }),
    );
    if (out.ok) {
      await refresh();
      onClose();
    }
  }

  return (
    <Dialog open title={`${T.exit.title}: ${membership.office.name}`} onClose={onClose}>
      {preview.isPending ? <Loading /> : null}
      <ErrorBanner error={preview.error} onRetry={() => preview.refetch()} />
      {preview.data ? (
        <form className="stack" onSubmit={submit}>
          <p>{items.length > 0 ? T.exit.intro : T.exit.nothing}</p>
          <p className="muted">
            {T.exit.counts(
              preview.data.counts.allotments,
              preview.data.counts.files,
              preview.data.counts.drafts,
              preview.data.counts.open_alerts,
            )}
          </p>
          {items.length > 0 ? (
            <Table caption={T.exit.title}>
              <thead>
                <tr>
                  <th scope="col">{T.exit.item}</th>
                  <th scope="col">{T.exit.successor}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.key}>
                    <td>
                      {i.kind === "file" ? T.exit.file : T.exit.allotment}:{" "}
                      <CaseLink value={{ ref_no: i.case.ref_no, cnr: i.case.cnr, case_no_text: i.case.case_no }} visible={i.case.visible} />
                      {i.pending_action ? <span className="muted"> · {i.pending_action}</span> : null}
                      {i.due_date ? <span className="muted"> · {formatDate(i.due_date)}</span> : null}
                    </td>
                    <td>
                      <SelectField
                        label={<span className="visually-hidden">{`${T.exit.successor} ${i.case.ref_no}`}</span>}
                        value={choice[i.key] ?? ""}
                        placeholder={T.exit.choose}
                        options={preview.data.targets.map((t) => ({
                          value: t.membership,
                          label: `${t.name}${t.designation ? `, ${t.designation}` : ""} (${t.office_code})`,
                        }))}
                        onChange={(e) => setChoice({ ...choice, [i.key]: e.target.value })}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}
          <TextArea label={T.exit.reason} required value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
          {missing > 0 ? <p className="muted">{T.exit.missing(missing)}</p> : null}
          <ErrorBanner error={save.error} />
          <Button type="submit" variant="danger" busy={save.busy} disabled={!ready}>
            {T.exit.confirm}
          </Button>
        </form>
      ) : null}
    </Dialog>
  );
}

function usePermissions() {
  return useQuery({
    queryKey: ["admin", "permissions"],
    queryFn: () => api<PermissionInfo[]>("/admin/permissions"),
    staleTime: 10 * 60_000,
  });
}

export function MembershipFunctionsPanel({ userId, membershipId, me }: { userId: string; membershipId: string; me: Me }) {
  const queryClient = useQueryClient();
  const key = [...userKey(userId), "functions", membershipId];
  const functions = useQuery({
    queryKey: key,
    queryFn: () => api<MembershipFunctions>(`/admin/users/${userId}/memberships/${membershipId}/permissions`),
  });
  const permissions = usePermissions();
  const [reason, setReason] = useState("");
  const action = useAction();
  const mayGrant = can(me, "users.grant");

  async function setOverride(permission: Permission, effect: "grant" | "deny" | null) {
    const out = await action.run(() =>
      api<MembershipFunctions>(`/admin/users/${userId}/memberships/${membershipId}/permissions/${permission}`, {
        method: "PUT",
        body: { effect, reason: reason.trim() || null },
      }),
    );
    if (out.ok) queryClient.setQueryData(key, out.value);
  }

  if (functions.isPending || permissions.isPending) return <Loading />;
  if (functions.error || !functions.data) return <ErrorBanner error={functions.error} onRetry={() => functions.refetch()} />;
  const data = functions.data;
  const overrides = new Map(data.overrides.filter((o) => o.is_active).map((o) => [o.permission, o]));
  return (
    <section className="stack" aria-label={T.users.functions}>
      <h3>{T.users.functions}</h3>
      {mayGrant ? <TextField label={T.users.reason} value={reason} onChange={(e) => setReason(e.target.value)} /> : null}
      <ErrorBanner error={action.error} />
      <Table caption={T.users.functions}>
        <thead>
          <tr>
            <th scope="col">{T.access.function}</th>
            <th scope="col">{T.users.typeFunctions}</th>
            <th scope="col">{T.users.override}</th>
            <th scope="col">{T.users.effective}</th>
            {mayGrant ? (
              <th scope="col">
                <span className="visually-hidden">{T.users.change}</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {(permissions.data ?? [])
            .filter((p) => p.is_active)
            .map((p) => {
              const fromType = data.type_functions.includes(p.code);
              const override = overrides.get(p.code);
              const effective = data.effective.includes(p.code);
              // the API refuses functions the caller does not hold and the reserved admin.tickets
              const offer = mayGrant && p.code !== "admin.tickets" && can(me, p.code);
              return (
                <tr key={p.code}>
                  <td>
                    {p.label} <span className="mono muted">{p.code}</span>
                  </td>
                  <td>{fromType ? T.yes : T.no}</td>
                  <td>
                    {override ? (
                      <>
                        <Badge tone={override.effect === "deny" ? "danger" : "success"}>
                          {override.effect === "deny" ? T.users.deny : T.users.grant}
                        </Badge>
                        {override.reason ? <span className="muted"> {override.reason}</span> : null}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{effective ? T.yes : T.no}</td>
                  {mayGrant ? (
                    <td>
                      {offer ? (
                        <div className="actions">
                          {!fromType && override?.effect !== "grant" ? (
                            <Button variant="link" busy={action.busy} onClick={() => setOverride(p.code, "grant")}>
                              {T.users.grant}
                            </Button>
                          ) : null}
                          {fromType && override?.effect !== "deny" ? (
                            <Button variant="link" busy={action.busy} onClick={() => setOverride(p.code, "deny")}>
                              {T.users.deny}
                            </Button>
                          ) : null}
                          {override ? (
                            <Button variant="link" busy={action.busy} onClick={() => setOverride(p.code, null)}>
                              {T.users.clear}
                            </Button>
                          ) : null}
                        </div>
                      ) : null}
                    </td>
                  ) : null}
                </tr>
              );
            })}
        </tbody>
      </Table>
    </section>
  );
}

function MembershipDocuments({ userId, membershipId }: { userId: string; membershipId: string }) {
  const documents = useQuery({
    queryKey: [...userKey(userId), "documents", membershipId],
    queryFn: () => api<MembershipDocument[]>(`/admin/users/${userId}/memberships/${membershipId}/documents`),
  });
  if (documents.isPending) return <Loading />;
  if (documents.error) return <ErrorBanner error={documents.error} onRetry={() => documents.refetch()} />;
  if (!documents.data?.length) return <EmptyState>{T.users.noDocuments}</EmptyState>;
  return (
    <Table caption={T.users.documents}>
      <thead>
        <tr>
          <th scope="col">{T.tickets.ref}</th>
          <th scope="col">{T.tickets.docDate}</th>
          <th scope="col">{T.tickets.description}</th>
          <th scope="col">{T.tickets.title}</th>
        </tr>
      </thead>
      <tbody>
        {documents.data.map((d) => (
          <tr key={d.id}>
            <td className="mono">{d.ref_no ?? "—"}</td>
            <td>{formatDate(d.doc_date)}</td>
            <td>
              {d.description ?? d.doc_type}
              {d.archived ? <Badge>{T.tickets.archived}</Badge> : null}
            </td>
            <td>
              {d.ticket_ref ? (
                <a href={`/admin/tickets/${d.ticket_ref.replaceAll("/", "-")}`} className="mono">
                  {d.ticket_ref}
                </a>
              ) : (
                "—"
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
