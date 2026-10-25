"use client";

/**
 * Users on the Settings hub (design portal-shell, decision 15; case-workspace-admin, decision 23, template A): the
 * list by name or e-mail (2 or more characters), user type, office subtree and status ("Active", "Not signed in yet",
 * "Off"), 50 at a time (`GET /admin/users` with `X-Total-Count`); the super admin can include logins without an
 * active office. Each row (initials in a fixed lead, the name over the post, the user-type badges, the status) opens
 * a wide side panel on `?user=<id>` with the existing user sections and "Open full page"; "Add user", the page's one
 * primary, opens the new-user flow in the same panel (`?user=new`): an exact e-mail lookup first, which offers "add a
 * membership to this person" instead of a duplicate. Every rule stays on the server.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Chevron } from "@/components/inbox/rows";
import {
  Badge,
  Button,
  buttonClass,
  CheckField,
  DataTable,
  EmptyState,
  ErrorBanner,
  Loading,
  Pagination,
  SelectField,
  SidePanel,
  TextField,
} from "@/components/ui";
import { api, apiPage, ApiError } from "@/lib/api/client";
import { labelOf, useLabels, useMe } from "@/lib/api/hooks";
import type { Designation, MembershipOut, Role, UserLookup, UserOut, UserTypeLabel } from "@/lib/api/types";
import { can, isSuperAdmin } from "@/lib/can";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";
import { useAction } from "@/lib/useAction";
import { useUrlOverlay } from "@/lib/useUrlOverlay";

import a from "./admin.module.css";
import { UserDetail } from "./UserDetail";

export const PAGE_SIZE = 50;

export function assignableOptions(types: UserTypeLabel[] | undefined) {
  return (types ?? []).filter((t) => t.assignable).map((t) => ({ value: t.code, label: t.label }));
}

export function MembershipSummary({ memberships, types }: { memberships: MembershipOut[]; types?: UserTypeLabel[] }) {
  if (memberships.length === 0) return <span className="muted">{T.users.noMembership}</span>;
  return (
    <ul className={a.memberList}>
      {memberships.map((m) => (
        <li key={m.id}>
          <span className="mono">{m.office.code}</span> · {labelOf(types, m.role)}
          {m.designation ? `, ${m.designation}` : ""}
        </li>
      ))}
    </ul>
  );
}

export type UserStatus = "active" | "not_signed_in" | "off";

/** Decision 23: "Active" (on and signed in), "Not signed in yet" (on, never signed in) or "Off" (sign-in turned off). */
export function userStatus(u: Pick<UserOut, "is_active" | "last_login_at">): UserStatus {
  if (!u.is_active) return "off";
  return u.last_login_at ? "active" : "not_signed_in";
}

const STATUS_TONE: Record<UserStatus, "success" | "danger" | undefined> = { active: "success", not_signed_in: undefined, off: "danger" };

export function StatusBadge({ user }: { user: Pick<UserOut, "is_active" | "last_login_at"> }) {
  const status = userStatus(user);
  return <Badge tone={STATUS_TONE[status]}>{T.users.statuses[status]}</Badge>;
}

/** The initials of a name, at most two letters. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "")).toUpperCase() || "?";
}

/** The primary active membership, else the first active one. */
function primaryMembership(u: UserOut): MembershipOut | undefined {
  const active = (u.memberships ?? []).filter((m) => m.is_active !== false);
  return active.find((m) => m.is_primary) ?? active[0];
}

/** Decision 23: one badge per active membership's type, at most two and "+n". */
export function TypeBadges({ user, types }: { user: UserOut; types?: UserTypeLabel[] }) {
  const roles = [...new Set((user.memberships ?? []).filter((m) => m.is_active !== false).map((m) => m.role))];
  if (roles.length === 0) return <span className="muted">{T.users.noMembership}</span>;
  return (
    <span className={a.types}>
      {roles.slice(0, 2).map((r) => (
        <Badge key={r} tone="info">
          {labelOf(types, r)}
        </Badge>
      ))}
      {roles.length > 2 ? <Badge>{T.users.moreTypes(roles.length - 2)}</Badge> : null}
    </span>
  );
}

/**
 * The user's side panel on `?user=<id>` (decision 23): the existing `UserDetail` sections, unchanged, with "Open full
 * page" in the footer; `?user=new` holds the new-user flow (e-mail lookup first).
 */
function UserPanel({
  value,
  onClose,
  onCreated,
}: {
  value: string | null;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const isNew = value === "new";
  const user = useQuery({
    queryKey: ["admin", "user", value ?? ""],
    queryFn: () => api<UserOut>(`/admin/users/${value}`),
    enabled: !!value && !isNew,
  });
  const title = isNew ? T.users.addUser : (user.data?.full_name ?? T.users.title);
  return (
    <SidePanel
      open={value !== null}
      title={title}
      onClose={onClose}
      wide
      footer={
        value && !isNew ? (
          <Link href={`/admin/users/${value}`} className={buttonClass("secondary")} data-variant="secondary">
            {T.users.openFullPage}
          </Link>
        ) : null
      }
    >
      {isNew ? <NewUserForm onDone={onCreated} /> : value ? <UserDetail id={value} /> : null}
    </SidePanel>
  );
}

export function UsersList({ params = {} }: { params?: Params }) {
  const me = useMe();
  const labels = useLabels();
  const pathname = usePathname() ?? "/admin/users";
  const overlay = useUrlOverlay("user", params, pathname);
  const [draft, setDraft] = useState({ q: "", office: "", role: "", status: "", includeEnded: false });
  const [filters, setFilters] = useState(draft);
  const [offset, setOffset] = useState(0);
  const [shortQuery, setShortQuery] = useState(false);
  const users = useQuery({
    queryKey: ["admin", "users", filters, offset],
    queryFn: () =>
      apiPage<UserOut[]>("/admin/users", {
        query: {
          q: filters.q.trim() || undefined,
          office: filters.office.trim() || undefined,
          role: filters.role || undefined,
          status: filters.status || undefined,
          include_ended: filters.includeEnded || undefined,
          limit: PAGE_SIZE,
          offset,
        },
      }),
  });
  const types = labels.data?.user_types;

  function apply(e: FormEvent) {
    e.preventDefault();
    if (draft.q.trim().length === 1) {
      setShortQuery(true);
      return;
    }
    setShortQuery(false);
    setOffset(0);
    setFilters(draft);
  }

  return (
    <section className="stack" aria-label={T.users.title}>
      <div className={a.groupHead}>
        <div>
          <h2>{T.users.title}</h2>
          <p className="muted">{T.users.subtitle}</p>
        </div>
        {/* the page's one primary (decision 28) */}
        {can(me.data, "users.create") ? <Button onClick={() => overlay.open("new")}>{T.users.addUser}</Button> : null}
      </div>
      <form className="row" onSubmit={apply} role="search">
        <TextField
          label={T.users.search}
          value={draft.q}
          error={shortQuery ? T.users.shortQuery : undefined}
          onChange={(e) => setDraft({ ...draft, q: e.target.value })}
        />
        <SelectField
          label={T.users.type}
          value={draft.role}
          placeholder={T.users.anyType}
          options={(types ?? []).map((t) => ({ value: t.code, label: t.label }))}
          onChange={(e) => setDraft({ ...draft, role: e.target.value })}
        />
        <TextField label={T.users.office} value={draft.office} onChange={(e) => setDraft({ ...draft, office: e.target.value })} />
        <SelectField
          label={T.users.statusFilter}
          value={draft.status}
          placeholder={T.users.anyStatus}
          options={(["active", "not_signed_in", "off"] as const).map((s) => ({ value: s, label: T.users.statuses[s]! }))}
          onChange={(e) => setDraft({ ...draft, status: e.target.value })}
        />
        {isSuperAdmin(me.data) ? (
          <CheckField
            inline
            label={T.users.includeEnded}
            checked={draft.includeEnded}
            onChange={(e) => setDraft({ ...draft, includeEnded: e.target.checked })}
          />
        ) : null}
        <Button type="submit" variant="secondary">
          {T.users.apply}
        </Button>
      </form>
      {users.isPending ? <Loading /> : null}
      <ErrorBanner error={users.error} onRetry={() => users.refetch()} />
      {users.data ? (
        users.data.items.length === 0 ? (
          <EmptyState>{T.users.empty}</EmptyState>
        ) : (
          <>
            <DataTable
              caption={T.users.title}
              rows={users.data.items}
              rowKey={(u) => u.id}
              rowLabel={(u) => T.users.openUser(u.full_name)}
              onRowClick={(u) => overlay.open(u.id)}
              columns={[
                {
                  key: "avatar",
                  header: <span className="visually-hidden">{T.users.avatar}</span>,
                  label: T.users.avatar,
                  width: "var(--s7)",
                  cell: (u) => (
                    <span className={a.avatar} data-lead="avatar" aria-hidden="true">
                      {initials(u.full_name)}
                    </span>
                  ),
                },
                {
                  key: "person",
                  header: T.users.person,
                  primary: true,
                  cell: (u) => {
                    const m = primaryMembership(u);
                    const post = [m?.designation ?? u.designation, m?.office.name ?? u.office?.name].filter(Boolean).join(", ");
                    return (
                      <span className={a.person}>
                        <span>{u.full_name}</span>
                        <span className="muted">{post || u.email}</span>
                      </span>
                    );
                  },
                },
                { key: "types", header: T.users.types, cell: (u) => <TypeBadges user={u} types={types} /> },
                { key: "status", header: T.users.status, width: "var(--lead-w)", cell: (u) => <StatusBadge user={u} /> },
                {
                  key: "open",
                  header: <span className="visually-hidden">{T.users.openFullPage}</span>,
                  label: T.users.openFullPage,
                  hideOnPhone: true,
                  width: "var(--s6)",
                  cell: () => <Chevron />,
                },
              ]}
            />
            <Pagination offset={offset} limit={PAGE_SIZE} total={users.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
      <UserPanel value={overlay.value} onClose={overlay.close} onCreated={(id) => overlay.open(id)} />
    </section>
  );
}

export function useDesignations() {
  return useQuery({
    queryKey: ["admin", "designations", "active"],
    queryFn: () => api<Designation[]>("/admin/designations"),
    staleTime: 5 * 60_000,
  });
}

export function DesignationInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const designations = useDesignations();
  return (
    <>
      <TextField label={T.users.designation} list="aslms-designations" value={value} onChange={(e) => onChange(e.target.value)} />
      <datalist id="aslms-designations">
        {(designations.data ?? []).map((d) => (
          <option key={d.id} value={d.name} />
        ))}
      </datalist>
    </>
  );
}

export interface MembershipDraft {
  office: string;
  designation: string;
  role: string;
}

export function MembershipFields({
  value,
  onChange,
  types,
}: {
  value: MembershipDraft;
  onChange: (v: MembershipDraft) => void;
  types: UserTypeLabel[] | undefined;
}) {
  return (
    <div className="row">
      <TextField label={T.users.officeCode} required value={value.office} onChange={(e) => onChange({ ...value, office: e.target.value })} />
      <DesignationInput value={value.designation} onChange={(designation) => onChange({ ...value, designation })} />
      <SelectField
        label={T.users.type}
        required
        value={value.role}
        placeholder=""
        options={assignableOptions(types)}
        onChange={(e) => onChange({ ...value, role: e.target.value })}
      />
    </div>
  );
}

/** `onDone` (the side panel): open the person's panel; without it the full page, as before. */
export function NewUserForm({ onDone }: { onDone?: (id: string) => void } = {}) {
  const router = useRouter();
  const labels = useLabels();
  const [email, setEmail] = useState("");
  const [found, setFound] = useState<UserLookup | null | undefined>(undefined);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [mobile, setMobile] = useState("");
  const [membership, setMembership] = useState<MembershipDraft>({ office: "", designation: "", role: "" });
  const lookup = useAction();
  const save = useAction();
  const done = (id: string) => (onDone ? onDone(id) : router.push(`/admin/users/${id}`));

  async function check(e: FormEvent) {
    e.preventDefault();
    setFound(undefined);
    await lookup.run(async () => {
      try {
        setFound(await api<UserLookup>("/admin/users/lookup", { query: { email: email.trim() } }));
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) setFound(null);
        else throw err;
      }
    });
  }

  async function addMembership(e: FormEvent) {
    e.preventDefault();
    if (!found) return;
    const out = await save.run(() =>
      api<MembershipOut>(`/admin/users/${found.id}/memberships`, {
        method: "POST",
        body: {
          office: membership.office.trim(),
          designation: membership.designation.trim() || null,
          role: membership.role as Role,
        },
      }),
    );
    if (out.ok) done(found.id);
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    const out = await save.run(() =>
      api<UserOut>("/admin/users", {
        method: "POST",
        body: {
          email: email.trim(),
          full_name: name.trim(),
          password,
          role: membership.role as Role,
          office_code: membership.office.trim(),
          designation: membership.designation.trim() || null,
          mobile: mobile.trim() || null,
        },
      }),
    );
    if (out.ok) done(out.value.id);
  }

  return (
    <section className="stack card" aria-label={T.users.createTitle}>
      <h2>{T.users.createTitle}</h2>
      <form className="row" onSubmit={check}>
        <TextField
          label={T.users.email}
          type="email"
          required
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            setFound(undefined);
          }}
        />
        <Button type="submit" variant="secondary" busy={lookup.busy}>
          {T.users.checkEmail}
        </Button>
      </form>
      <ErrorBanner error={lookup.error} />
      {found ? (
        <form className="stack" onSubmit={addMembership}>
          <p>{T.users.exists(found.full_name)}</p>
          <ul>
            {found.memberships.map((m) => (
              <li key={`${m.office_code}-${m.role}`}>
                <span className="mono">{m.office_code}</span> · {labelOf(labels.data?.user_types, m.role)}
                {m.designation ? `, ${m.designation}` : ""}
              </li>
            ))}
          </ul>
          <MembershipFields value={membership} onChange={setMembership} types={labels.data?.user_types} />
          <ErrorBanner error={save.error} />
          <Button type="submit" busy={save.busy}>
            {T.users.addMembershipInstead}
          </Button>
        </form>
      ) : null}
      {found === null ? (
        <form className="stack" onSubmit={create}>
          <p className="muted">{T.users.noSuchPerson}</p>
          <div className="row">
            <TextField label={T.auth.fullName} required value={name} onChange={(e) => setName(e.target.value)} />
            <TextField
              label={T.users.tempPassword}
              type="password"
              autoComplete="new-password"
              hint={T.users.tempPasswordHint}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <TextField label={T.users.mobile} type="tel" value={mobile} onChange={(e) => setMobile(e.target.value)} />
          </div>
          <MembershipFields value={membership} onChange={setMembership} types={labels.data?.user_types} />
          <ErrorBanner error={save.error} />
          <Button type="submit" busy={save.busy}>
            {T.users.create}
          </Button>
        </form>
      ) : null}
    </section>
  );
}
