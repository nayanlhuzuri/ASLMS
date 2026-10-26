"use client";

/**
 * Users on the Settings hub (design portal-shell, decision 15; case-workspace-admin, decision 23, template A): the
 * list by name or e-mail (2 or more characters), user type, office subtree and status ("Active", "Not signed in yet",
 * "Off"), 50 at a time (`GET /admin/users` with `X-Total-Count`); the super admin can include logins without an
 * active office. Each row (initials in a fixed lead, the name over the post, the user-type badges, the status) opens
 * a wide side panel on `?user=<id>` with the existing user sections and "Open full page"; "Add user", the page's one
 * primary, opens the new-user flow in the same panel (`?user=new`): an exact e-mail lookup first, which offers "add a
 * membership to this person" instead of a duplicate. Every rule stays on the server.
 *
 * Design office-head-picker (decisions 15 and 17): the super admin's New User has "No Office Yet" (a login with no
 * office, to be named head of a department being created; `?no_office=1` starts it ticked, `?return=` goes back with
 * `?head=<id>`); the list shows such a login with a No Office Yet badge and More Filters has a No Office Yet filter.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";

import { Chevron } from "@/components/inbox/rows";
import {
  Badge,
  Button,
  CheckField,
  DataTable,
  EmptyState,
  ErrorBanner,
  Loading,
  OfficePicker,
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
import { offsetOf, queryString, type Params } from "@/lib/params";
import { safeNext } from "@/lib/safeNext";
import { useAction } from "@/lib/useAction";
import { useUrlOverlay } from "@/lib/useUrlOverlay";

import a from "./admin.module.css";
import { openUserDetails, UserDetailsModal } from "./UserDetails";

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
export function primaryMembership(u: UserOut): MembershipOut | undefined {
  const active = (u.memberships ?? []).filter((m) => m.is_active !== false);
  return active.find((m) => m.is_primary) ?? active[0];
}

/** Decision 23: one badge per active membership's type, at most two and "+n". */
export function TypeBadges({ user, types }: { user: UserOut; types?: UserTypeLabel[] }) {
  const roles = [...new Set((user.memberships ?? []).filter((m) => m.is_active !== false).map((m) => m.role))];
  // design office-head-picker, decision 17: never held an office (the exited login keeps "No Active Office")
  if (roles.length === 0 && user.office === null) return <Badge>{T.users.noOfficeYet}</Badge>;
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

/** The new-user flow in the side panel on `?user=new` (decision 31: it stays a side panel; a person opens the modal). */
function NewUserPanel({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  return (
    <SidePanel open={open} title={T.users.addUser} onClose={onClose} wide>
      {open ? <NewUserForm onDone={onCreated} /> : null}
    </SidePanel>
  );
}

/** The list's own filters in the address (design portal-ui-polish-2, decision 31: the modal keeps the list behind). */
export const USER_LIST_KEYS = ["q", "role", "office", "subtree", "status", "include_ended", "no_office", "offset"] as const;

export function listParamsOf(params: Params): Params {
  const out: Params = {};
  for (const k of USER_LIST_KEYS) if (params[k]) out[k] = params[k];
  return out;
}

interface Filters {
  q: string;
  role: string;
  office: string;
  subtree: boolean;
  status: string;
  includeEnded: boolean;
  noOffice: boolean;
}

function filtersOf(params: Params): Filters {
  return {
    q: params.q ?? "",
    role: params.role ?? "",
    office: params.office ?? "",
    subtree: params.subtree !== "false",
    status: params.status ?? "",
    includeEnded: params.include_ended === "true",
    noOffice: params.no_office === "true",
  };
}

function paramsOf(f: Filters): Params {
  return {
    q: f.q.trim() || undefined,
    role: f.role || undefined,
    office: f.office || undefined,
    subtree: f.office && !f.subtree ? "false" : undefined,
    status: f.status || undefined,
    include_ended: f.includeEnded ? "true" : undefined,
    no_office: f.noOffice ? "true" : undefined,
  };
}

/**
 * The Users list (decision 23) with the one-line toolbar (design portal-ui-polish-2, decision 27): Name or E-mail,
 * User Type, Office (the Office Picker with Include Sub-offices), Status, More Filters (n) and Search on one line,
 * labels kept for screen readers and shown as placeholders; "Include Logins Without an Active Office" (the super
 * admin's) sits inside More Filters. The filters live in the address, so the User Details modal (`userId`, on
 * `/admin/users/<id>`) opens over the same list.
 */
export function UsersList({ params = {}, userId }: { params?: Params; userId?: string }) {
  const me = useMe();
  const labels = useLabels();
  const router = useRouter();
  const listPath = "/admin/users";
  const overlay = useUrlOverlay("user", params, listPath);
  const filters = filtersOf(params);
  const offset = offsetOf(params);
  const users = useQuery({
    queryKey: ["admin", "users", filters, offset],
    queryFn: () =>
      apiPage<UserOut[]>("/admin/users", {
        query: {
          q: filters.q.trim() || undefined,
          // No Office Yet stands alone: the server refuses it with an office or a user type (decision 17)
          office: (!filters.noOffice && filters.office) || undefined,
          subtree: !filters.noOffice && filters.office && !filters.subtree ? false : undefined,
          role: (!filters.noOffice && filters.role) || undefined,
          status: filters.status || undefined,
          include_ended: filters.includeEnded || undefined,
          no_office: filters.noOffice || undefined,
          limit: PAGE_SIZE,
          offset,
        },
      }),
  });
  const types = labels.data?.user_types;
  const list = listParamsOf(params);
  const superAdmin = isSuperAdmin(me.data);

  function go(next: Params) {
    router.push(listPath + queryString(next));
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
      <UsersToolbar
        key={queryString(paramsOf(filters))}
        initial={filters}
        types={types}
        superAdmin={superAdmin}
        onSearch={(f) => go(paramsOf(f))}
      />
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
              onRowClick={(u) => openUserDetails(router, u.id, list)}
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
                  header: <span className="visually-hidden">{T.users.open}</span>,
                  label: T.users.open,
                  hideOnPhone: true,
                  width: "var(--s6)",
                  cell: () => <Chevron />,
                },
              ]}
            />
            <Pagination
              offset={offset}
              limit={PAGE_SIZE}
              total={users.data.total}
              onChange={(next) => go({ ...paramsOf(filters), offset: next ? String(next) : undefined })}
            />
          </>
        )
      ) : null}
      <NewUserPanel
        open={overlay.value === "new"}
        onClose={overlay.close}
        onCreated={(id) => openUserDetails(router, id, list, { replace: true })}
      />
      {userId ? <UserDetailsModal key={userId} id={userId} listParams={list} tab={params.tab} /> : null}
    </section>
  );
}

function UsersToolbar({
  initial,
  types,
  superAdmin,
  onSearch,
}: {
  initial: Filters;
  types: UserTypeLabel[] | undefined;
  superAdmin: boolean;
  onSearch: (f: Filters) => void;
}) {
  const [draft, setDraft] = useState<Filters>(initial);
  const [shortQuery, setShortQuery] = useState(false);
  const moreCount = (draft.includeEnded ? 1 : 0) + (draft.noOffice ? 1 : 0);
  const [moreOpen, setMoreOpen] = useState(moreCount > 0);
  const moreId = useId();

  function submit(e: FormEvent) {
    e.preventDefault();
    if (draft.q.trim().length === 1) {
      setShortQuery(true);
      return;
    }
    setShortQuery(false);
    onSearch(draft);
  }

  return (
    <form className={a.toolbar} onSubmit={submit} role="search" aria-label={T.users.title}>
      <div className={a.toolbarLine}>
        <div className={a.toolbarSearch}>
          <TextField
            label={T.users.search}
            hideLabel
            placeholder={T.users.searchPlaceholder}
            title={T.users.shortQuery}
            value={draft.q}
            error={shortQuery ? T.users.shortQuery : undefined}
            onChange={(e) => setDraft({ ...draft, q: e.target.value })}
          />
        </div>
        <div className={a.toolbarType}>
          <SelectField
            label={T.users.type}
            hideLabel
            value={draft.role}
            placeholder={T.users.anyType}
            options={(types ?? []).map((t) => ({ value: t.code, label: t.label }))}
            onChange={(e) => setDraft({ ...draft, role: e.target.value })}
          />
        </div>
        <div className={a.toolbarOffice}>
          <OfficePicker
            label={T.users.office}
            hideLabel
            placeholder={T.users.officePlaceholder}
            purpose="users"
            value={draft.office || null}
            onChange={(office) => setDraft({ ...draft, office: office ?? "" })}
            subtree={{ value: draft.subtree, onChange: (subtree) => setDraft({ ...draft, subtree }) }}
          />
        </div>
        <div className={a.toolbarStatus}>
          <SelectField
            label={T.users.statusFilter}
            hideLabel
            value={draft.status}
            placeholder={T.users.anyStatus}
            options={(["active", "not_signed_in", "off"] as const).map((s) => ({ value: s, label: T.users.statuses[s]! }))}
            onChange={(e) => setDraft({ ...draft, status: e.target.value })}
          />
        </div>
        {superAdmin ? (
          <Button variant="secondary" aria-expanded={moreOpen} aria-controls={moreId} onClick={() => setMoreOpen(!moreOpen)}>
            {T.users.moreFiltersButton(moreCount)}
          </Button>
        ) : null}
        <Button type="submit" variant="secondary">
          {T.users.apply}
        </Button>
      </div>
      {superAdmin ? (
        <div id={moreId} className={a.toolbarMore} hidden={!moreOpen} role="group" aria-label={T.users.moreFiltersTitle}>
          <CheckField
            label={T.users.includeEnded}
            checked={draft.includeEnded}
            onChange={(e) => setDraft({ ...draft, includeEnded: e.target.checked })}
          />
          <CheckField
            label={T.users.filterNoOffice}
            checked={draft.noOffice}
            onChange={(e) => setDraft({ ...draft, noOffice: e.target.checked })}
          />
        </div>
      ) : null}
    </form>
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
      {/* design portal-ui-polish-2, decision 30: the office from the picker, never typed */}
      <OfficePicker
        label={T.users.office}
        purpose="membership"
        required
        value={value.office || null}
        onChange={(office) => onChange({ ...value, office: office ?? "" })}
      />
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

/** Where New User goes back to with the new person (`?return=`, decision 8): an address in the portal only. */
export function returnWithHead(back: string, id: string): string {
  const path = safeNext(back);
  return `${path}${path.includes("?") ? "&" : "?"}head=${encodeURIComponent(id)}`;
}

/**
 * `onDone` (the side panel): open the person's User Details; without it the person's address. `noOffice` starts the
 * No Office Yet tick on (the super admin's only), `returnTo` is where to go back with `?head=<id>` (decision 8).
 */
export function NewUserForm({ onDone, noOffice: startNoOffice = false, returnTo }: { onDone?: (id: string) => void; noOffice?: boolean; returnTo?: string } = {}) {
  const router = useRouter();
  const me = useMe();
  const labels = useLabels();
  const superAdmin = isSuperAdmin(me.data);
  const [noOffice, setNoOffice] = useState(startNoOffice);
  const withoutOffice = superAdmin && noOffice;
  const [email, setEmail] = useState("");
  const [found, setFound] = useState<UserLookup | null | undefined>(undefined);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [mobile, setMobile] = useState("");
  const [membership, setMembership] = useState<MembershipDraft>({ office: "", designation: "", role: "" });
  const lookup = useAction();
  const save = useAction();
  const done = (id: string) =>
    returnTo ? router.push(returnWithHead(returnTo, id)) : onDone ? onDone(id) : router.push(`/admin/users/${id}`);

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
        body: withoutOffice
          ? { email: email.trim(), full_name: name.trim(), password, role: null, office_code: null, mobile: mobile.trim() || null }
          : {
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
          {superAdmin ? (
            <div>
              <CheckField label={T.users.noOfficeYet} checked={noOffice} onChange={(e) => setNoOffice(e.target.checked)} />
              <p className="muted">{T.users.noOfficeYetHint}</p>
            </div>
          ) : null}
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
          {withoutOffice ? null : <MembershipFields value={membership} onChange={setMembership} types={labels.data?.user_types} />}
          <ErrorBanner error={save.error} />
          <Button type="submit" busy={save.busy}>
            {T.users.create}
          </Button>
        </form>
      ) : null}
    </section>
  );
}
