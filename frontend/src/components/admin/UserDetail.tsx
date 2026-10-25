"use client";

/**
 * The parts of a user's details (design portal-shell, decision 15), recomposed by the User Details modal (design
 * portal-ui-polish-2, decisions 31-38): the login fields (name, e-mail correction, mobile) in Edit Profile, the
 * temporary password, the change of a membership's designation or type, a new membership (its office from the Office
 * Picker), the exit dialog that ends a membership, a membership's functions with grant / deny overrides and the orders
 * linked to it. Each action shows only with its function; the API decides (scope, delegation, reserved functions).
 * Their calls and rules are those of the earlier full page, unchanged.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  CaseLink,
  ConfirmDialog,
  DataTable,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  SelectField,
  TextArea,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { labelOf } from "@/lib/api/hooks";
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
import { can } from "@/lib/can";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import { assignableOptions, DesignationInput, MembershipFields, type MembershipDraft } from "./Users";

export function userKey(id: string) {
  return ["admin", "user", id] as const;
}

export function useRefreshUser(id: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: userKey(id) }),
      // the list behind the modal shows the same person
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] }),
    ]);
}

/** Edit Profile (decision 32): the login fields of the earlier page in a dialog; only changed fields are sent. */
export function EditProfileDialog({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const refresh = useRefreshUser(user.id);
  const [form, setForm] = useState({ full_name: user.full_name, email: user.email, mobile: user.mobile ?? "" });
  const save = useAction();

  async function submit() {
    const body: Record<string, string | null> = {};
    if (form.full_name.trim() !== user.full_name) body.full_name = form.full_name.trim();
    if (form.email.trim().toLowerCase() !== user.email) body.email = form.email.trim();
    if ((form.mobile.trim() || null) !== (user.mobile ?? null)) body.mobile = form.mobile.trim() || null;
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    const out = await save.run(() => api<UserOut>(`/admin/users/${user.id}`, { method: "PATCH", body }));
    if (out.ok) {
      await refresh();
      onClose();
    }
  }

  return (
    <ConfirmDialog
      open
      title={T.userDetails.editProfileButton}
      subtitle={user.full_name}
      onClose={onClose}
      onConfirm={() => void submit()}
      busy={save.busy}
      error={save.error}
      confirmLabel={T.save}
    >
      <TextField label={T.auth.fullName} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
      <TextField label={T.users.email} type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      <TextField label={T.users.mobile} type="tel" value={form.mobile} onChange={(e) => setForm({ ...form, mobile: e.target.value })} />
    </ConfirmDialog>
  );
}

/** Reset Password (decision 32): a temporary password the person must change at the next sign-in. */
export function PasswordDialog({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const reset = useAction();
  return (
    <ConfirmDialog
      open
      title={T.userDetails.resetPassword}
      subtitle={user.full_name}
      onClose={onClose}
      onConfirm={() => {
        void reset.run(() => api(`/admin/users/${user.id}/password`, { method: "POST", body: { password } })).then((out) => {
          if (out.ok) setPassword("");
        });
      }}
      busy={reset.busy}
      error={reset.error}
      confirmLabel={T.save}
    >
      <TextField
        label={T.users.tempPassword}
        type="password"
        autoComplete="new-password"
        hint={T.users.tempPasswordHint}
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {reset.done ? <Notice>{T.users.passwordSet}</Notice> : null}
    </ConfirmDialog>
  );
}

export function ChangeMembership({
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

/** Add Office (decision 34): a new membership, its office chosen from the Office Picker (purpose `membership`). */
export function AddMembershipDialog({
  userId,
  types,
  onClose,
}: {
  userId: string;
  types: UserTypeLabel[] | undefined;
  onClose: () => void;
}) {
  const refresh = useRefreshUser(userId);
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
      onClose();
    }
  }

  return (
    <Dialog open title={T.userDetails.addOfficeButton} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <MembershipFields value={draft} onChange={setDraft} types={types} />
        <ErrorBanner error={save.error} />
        <Button type="submit" busy={save.busy} disabled={!draft.office || !draft.role}>
          {T.userDetails.addOfficeButton}
        </Button>
      </form>
    </Dialog>
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
            <DataTable
              caption={T.exit.title}
              rows={items}
              rowKey={(i) => i.key}
              columns={[
                {
                  key: "item",
                  header: T.exit.item,
                  primary: true,
                  cell: (i) => (
                    <>
                      {i.kind === "file" ? T.exit.file : T.exit.allotment}:{" "}
                      <CaseLink value={{ ref_no: i.case.ref_no, cnr: i.case.cnr, case_no_text: i.case.case_no }} visible={i.case.visible} />
                      {i.pending_action ? <span className="muted"> · {i.pending_action}</span> : null}
                      {i.due_date ? <span className="muted"> · {formatDate(i.due_date)}</span> : null}
                    </>
                  ),
                },
                {
                  key: "successor",
                  header: T.exit.successor,
                  cell: (i) => (
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
                  ),
                },
              ]}
            />
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

export function usePermissions() {
  return useQuery({
    queryKey: ["admin", "permissions"],
    queryFn: () => api<PermissionInfo[]>("/admin/permissions"),
    staleTime: 10 * 60_000,
  });
}

export function functionsKey(userId: string, membershipId: string) {
  return [...userKey(userId), "functions", membershipId] as const;
}

/** The functions of one membership with grant / deny switches (Change Exceptions, decision 35). */
export function MembershipFunctionsPanel({ userId, membershipId, me }: { userId: string; membershipId: string; me: Me }) {
  const queryClient = useQueryClient();
  const key = functionsKey(userId, membershipId);
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
      {mayGrant ? <TextField label={T.users.reason} value={reason} onChange={(e) => setReason(e.target.value)} /> : null}
      <ErrorBanner error={action.error} />
      <DataTable
        caption={T.users.functions}
        rows={(permissions.data ?? []).filter((p) => p.is_active)}
        rowKey={(p) => p.code}
        columns={[
          {
            key: "function",
            header: T.access.function,
            primary: true,
            cell: (p) => (
              <>
                {p.label} <span className="mono muted">{p.code}</span>
              </>
            ),
          },
          { key: "type", header: T.users.typeFunctions, cell: (p) => (data.type_functions.includes(p.code) ? T.yes : T.no) },
          {
            key: "override",
            header: T.users.override,
            cell: (p) => {
              const override = overrides.get(p.code);
              return override ? (
                <>
                  <Badge tone={override.effect === "deny" ? "danger" : "success"}>
                    {override.effect === "deny" ? T.users.deny : T.users.grant}
                  </Badge>
                  {override.reason ? <span className="muted"> {override.reason}</span> : null}
                </>
              ) : (
                "—"
              );
            },
          },
          { key: "effective", header: T.users.effective, cell: (p) => (data.effective.includes(p.code) ? T.yes : T.no) },
          ...(mayGrant
            ? [
                {
                  key: "change",
                  header: <span className="visually-hidden">{T.users.change}</span>,
                  label: T.users.change,
                  cell: (p: PermissionInfo) => {
                    const fromType = data.type_functions.includes(p.code);
                    const override = overrides.get(p.code);
                    // the API refuses functions the caller does not hold and the reserved admin.tickets
                    const offer = p.code !== "admin.tickets" && can(me, p.code);
                    return offer ? (
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
                    ) : null;
                  },
                },
              ]
            : []),
        ]}
      />
    </section>
  );
}

/** The government orders linked to a membership (Government Orders, decision 34). */
export function MembershipDocuments({ userId, membershipId }: { userId: string; membershipId: string }) {
  const documents = useQuery({
    queryKey: [...userKey(userId), "documents", membershipId],
    queryFn: () => api<MembershipDocument[]>(`/admin/users/${userId}/memberships/${membershipId}/documents`),
  });
  if (documents.isPending) return <Loading />;
  if (documents.error) return <ErrorBanner error={documents.error} onRetry={() => documents.refetch()} />;
  if (!documents.data?.length) return <EmptyState>{T.users.noDocuments}</EmptyState>;
  return (
    <DataTable
      caption={T.users.documents}
      rows={documents.data}
      rowKey={(d) => d.id}
      columns={[
        { key: "ref", header: T.tickets.ref, cell: (d) => <span className="mono">{d.ref_no ?? "—"}</span> },
        { key: "date", header: T.tickets.docDate, cell: (d) => formatDate(d.doc_date) },
        {
          key: "description",
          header: T.tickets.description,
          primary: true,
          cell: (d) => (
            <>
              {d.description ?? d.doc_type}
              {d.archived ? <Badge>{T.tickets.archived}</Badge> : null}
            </>
          ),
        },
        {
          key: "ticket",
          header: T.tickets.title,
          cell: (d) =>
            d.ticket_ref ? (
              <a href={`/admin/tickets/${d.ticket_ref.replaceAll("/", "-")}`} className="mono">
                {d.ticket_ref}
              </a>
            ) : (
              "—"
            ),
        },
      ]}
    />
  );
}
