"use client";

/**
 * Users (design portal-shell, decision 15): the list by name or e-mail, office subtree and user type, 50 at a time
 * (`GET /admin/users` with `X-Total-Count`); the super admin can include logins without an active office. New
 * user: an exact e-mail lookup first, which offers "add a membership to this person" instead of a duplicate.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  CheckField,
  EmptyState,
  ErrorBanner,
  Loading,
  Pagination,
  SelectField,
  Table,
  TextField,
} from "@/components/ui";
import { api, apiPage, ApiError } from "@/lib/api/client";
import { labelOf, useLabels, useMe } from "@/lib/api/hooks";
import type { Designation, MembershipOut, Role, UserLookup, UserOut, UserTypeLabel } from "@/lib/api/types";
import { can, isSuperAdmin } from "@/lib/can";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

export const PAGE_SIZE = 50;

export function assignableOptions(types: UserTypeLabel[] | undefined) {
  return (types ?? []).filter((t) => t.assignable).map((t) => ({ value: t.code, label: t.label }));
}

export function MembershipSummary({ memberships, types }: { memberships: MembershipOut[]; types?: UserTypeLabel[] }) {
  if (memberships.length === 0) return <span className="muted">{T.users.noMembership}</span>;
  return (
    <ul style={{ margin: 0, paddingLeft: 18 }}>
      {memberships.map((m) => (
        <li key={m.id}>
          <span className="mono">{m.office.code}</span> · {labelOf(types, m.role)}
          {m.designation ? `, ${m.designation}` : ""}
        </li>
      ))}
    </ul>
  );
}

export function UsersList() {
  const me = useMe();
  const labels = useLabels();
  const [draft, setDraft] = useState({ q: "", office: "", role: "", includeEnded: false });
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
          include_ended: filters.includeEnded || undefined,
          limit: PAGE_SIZE,
          offset,
        },
      }),
  });

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
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>{T.users.title}</h2>
        {can(me.data, "users.create") ? (
          <Link href="/admin/users/new" className="button-link">
            {T.users.newUser}
          </Link>
        ) : null}
      </div>
      <form className="row" onSubmit={apply} role="search">
        <TextField
          label={T.users.search}
          value={draft.q}
          error={shortQuery ? T.users.shortQuery : undefined}
          onChange={(e) => setDraft({ ...draft, q: e.target.value })}
        />
        <TextField label={T.users.office} value={draft.office} onChange={(e) => setDraft({ ...draft, office: e.target.value })} />
        <SelectField
          label={T.users.type}
          value={draft.role}
          placeholder={T.users.anyType}
          options={(labels.data?.user_types ?? []).map((t) => ({ value: t.code, label: t.label }))}
          onChange={(e) => setDraft({ ...draft, role: e.target.value })}
        />
        {isSuperAdmin(me.data) ? (
          <CheckField
            label={T.users.includeEnded}
            checked={draft.includeEnded}
            onChange={(e) => setDraft({ ...draft, includeEnded: e.target.checked })}
          />
        ) : null}
        <Button type="submit">{T.users.apply}</Button>
      </form>
      {users.isPending ? <Loading /> : null}
      <ErrorBanner error={users.error} onRetry={() => users.refetch()} />
      {users.data ? (
        users.data.items.length === 0 ? (
          <EmptyState>{T.users.empty}</EmptyState>
        ) : (
          <>
            <Table caption={T.users.title}>
              <thead>
                <tr>
                  <th scope="col">{T.users.name}</th>
                  <th scope="col">{T.users.email}</th>
                  <th scope="col">{T.users.offices}</th>
                  <th scope="col">{T.users.status}</th>
                </tr>
              </thead>
              <tbody>
                {users.data.items.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <Link href={`/admin/users/${u.id}`}>{u.full_name}</Link>
                    </td>
                    <td>{u.email}</td>
                    <td>
                      <MembershipSummary memberships={u.memberships ?? []} types={labels.data?.user_types} />
                    </td>
                    <td>{u.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge tone="danger">{T.users.disabled}</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination offset={offset} limit={PAGE_SIZE} total={users.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
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

export function NewUserForm() {
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
    if (out.ok) router.push(`/admin/users/${found.id}`);
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
    if (out.ok) router.push(`/admin/users/${out.value.id}`);
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
