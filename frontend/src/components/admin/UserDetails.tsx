"use client";

/**
 * The User Details modal (design portal-ui-polish-2, decisions 31-38), in place of the user's full page and its offices
 * table. Its address is `/admin/users/<id>` with the tab in `?tab=overview | offices | functions | activity`; the route
 * renders the Users list behind with its filters from the query string. Opening from a row pushes the address and
 * marks the history entry; closing goes back when the modal was opened in the portal, else to the list's address.
 * Escape, the overlay and Back close it; on phones it fills the screen (the kit `Modal`).
 *
 * - **Header** (decision 32): initials, name, "designation · office", e-mail, mobile, status and last sign-in; Edit
 *   Profile (`users.edit`) and More: Reset Password (`users.reset_password`), Turn Sign-in Off / On
 *   (`users.enable_disable`; off still signs the person out everywhere). There is no Sign Out Everywhere (decision 37).
 * - **Overview** (33), **Offices** (34: a card per membership with its Actions menu, Reactivate on an ended card, Add
 *   Office), **Functions** (35: the held functions by group with the overrides marked; Change Exceptions with
 *   `users.grant`) and **Activity** (36: only for audit readers, the latest 20 entries by the person).
 * The APIs are those of the earlier page, unchanged (decision 38).
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Menu,
  Modal,
  Notice,
  SelectField,
  SidePanel,
  Tabs,
  type MenuItem,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { labelOf, useLabels, useMe, useOfficeChoices } from "@/lib/api/hooks";
import type { AuditPage, Me, MembershipFunctions, MembershipOut, UserOut, UserTypeLabel } from "@/lib/api/types";
import { actionName } from "@/lib/audit";
import { can, canAny, readsAudit } from "@/lib/can";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { useAction } from "@/lib/useAction";
import { OVERLAY_MARK } from "@/lib/useUrlOverlay";

import a from "./admin.module.css";
import { groupFunctions } from "./UserTypes";
import {
  AddMembershipDialog,
  ChangeMembership,
  EditProfileDialog,
  ExitDialog,
  functionsKey,
  MembershipDocuments,
  MembershipFunctionsPanel,
  PasswordDialog,
  usePermissions,
  useRefreshUser,
  userKey,
} from "./UserDetail";
import { initials, StatusBadge } from "./Users";

export const USER_TABS = ["overview", "offices", "functions", "activity"] as const;
export type UserTab = (typeof USER_TABS)[number];

const LIST_PATH = "/admin/users";

/** The person this page pushed and has not yet marked (module scope: the route's page remounts on navigation). */
let pendingOpen: string | null = null;

function markOf(id: string): string {
  return `user-details=${id}`;
}

/** Opens a person's User Details over the list: pushes `/admin/users/<id>?<list query>` (or replaces it). */
export function openUserDetails(
  router: { push: (href: string) => void; replace: (href: string) => void },
  id: string,
  listParams: Params,
  { replace = false }: { replace?: boolean } = {},
) {
  pendingOpen = id;
  const href = `${LIST_PATH}/${id}${queryString(listParams)}`;
  if (replace) router.replace(href);
  else router.push(href);
}

function tabOf(value: string | undefined): UserTab {
  return (USER_TABS as readonly string[]).includes(value ?? "") ? (value as UserTab) : "overview";
}

/** The active memberships first, the primary first among them, then the ended ones (decision 34). */
export function membershipOrder(ms: MembershipOut[]): MembershipOut[] {
  const rank = (m: MembershipOut) => (m.is_active === false ? 2 : m.is_primary ? 0 : 1);
  return [...ms].sort((x, y) => rank(x) - rank(y));
}

export function UserDetailsModal({ id, listParams, tab }: { id: string; listParams: Params; tab?: string }) {
  const router = useRouter();
  const me = useMe();
  const labels = useLabels();
  const user = useQuery({ queryKey: userKey(id), queryFn: () => api<UserOut>(`/admin/users/${id}`) });
  const memberships = useQuery({
    queryKey: [...userKey(id), "memberships"],
    queryFn: () => api<MembershipOut[]>(`/admin/users/${id}/memberships`, { query: { include_ended: true } }),
  });
  const [current, setCurrent] = useState<UserTab>(tabOf(tab));
  const [functionsOf, setFunctionsOf] = useState<string | null>(null);
  const types = labels.data?.user_types;
  const showActivity = readsAudit(me.data);
  const shownTab: UserTab = current === "activity" && !showActivity ? "overview" : current;

  // mark the history entry this page pushed, so Close can go back to the list (decision 31)
  useEffect(() => {
    if (pendingOpen !== id) return;
    pendingOpen = null;
    const state = (window.history.state as Record<string, unknown> | null) ?? {};
    window.history.replaceState({ ...state, [OVERLAY_MARK]: markOf(id) }, "", window.location.href);
  }, [id]);

  function close() {
    const state = window.history.state as Record<string, unknown> | null;
    if (state?.[OVERLAY_MARK] === markOf(id)) router.back();
    else router.replace(LIST_PATH + queryString(listParams));
  }

  function hrefOf(t: UserTab): string {
    return `${LIST_PATH}/${id}${queryString({ ...listParams, tab: t === "overview" ? undefined : t })}`;
  }

  function select(t: UserTab) {
    setCurrent(t);
    // the tab lives in the address without a new history entry, so Back still closes the modal
    const state = (window.history.state as Record<string, unknown> | null) ?? {};
    window.history.replaceState(state, "", hrefOf(t));
  }

  const ordered = membershipOrder(memberships.data ?? []);
  const activeCount = ordered.filter((m) => m.is_active !== false).length;
  const primary = ordered.find((m) => m.is_active !== false && m.is_primary) ?? ordered.find((m) => m.is_active !== false);
  const tabs: UserTab[] = showActivity ? [...USER_TABS] : USER_TABS.filter((t) => t !== "activity");

  const title = user.data ? (
    <span className={a.umTitle}>
      <span className={a.avatarXl} aria-hidden="true">
        {initials(user.data.full_name)}
      </span>
      <span>{user.data.full_name}</span>
    </span>
  ) : (
    T.users.title
  );

  return (
    <Modal
      open
      title={title}
      onClose={close}
      header={
        user.data && me.data ? (
          <>
            <UserHeader user={user.data} me={me.data} primary={primary} />
            <Tabs
              label={T.userDetails.tabsAria}
              onSelect={(href) => select(tabOf(new URL(href, "http://x").searchParams.get("tab") ?? undefined))}
              items={tabs.map((t) => ({
                href: hrefOf(t),
                label: T.userDetails.tabs[t]!,
                active: shownTab === t,
                count: t === "offices" && memberships.data ? activeCount : undefined,
              }))}
            />
          </>
        ) : null
      }
    >
      {user.isPending || me.isPending ? <Loading /> : null}
      <ErrorBanner error={user.error ?? me.error} onRetry={() => user.refetch()} />
      {user.data && me.data ? (
        <>
          {shownTab === "overview" ? <Overview user={user.data} primary={primary} activeCount={activeCount} types={types} /> : null}
          {shownTab === "offices" ? (
            <>
              {memberships.isPending ? <Loading /> : null}
              <ErrorBanner error={memberships.error} onRetry={() => memberships.refetch()} />
              {memberships.data ? (
                <OfficeCards
                  user={user.data}
                  memberships={ordered}
                  me={me.data}
                  types={types}
                  onFunctions={(m) => {
                    setFunctionsOf(m.id);
                    select("functions");
                  }}
                />
              ) : null}
            </>
          ) : null}
          {shownTab === "functions" ? (
            <FunctionsTab
              userId={id}
              memberships={ordered.filter((m) => m.is_active !== false)}
              loading={memberships.isPending}
              me={me.data}
              types={types}
              chosen={functionsOf}
              onChoose={setFunctionsOf}
            />
          ) : null}
          {shownTab === "activity" && showActivity ? <Activity userId={id} /> : null}
        </>
      ) : null}
    </Modal>
  );
}

function UserHeader({ user, me, primary }: { user: UserOut; me: Me; primary: MembershipOut | undefined }) {
  const refresh = useRefreshUser(user.id);
  const [editing, setEditing] = useState(false);
  const [password, setPassword] = useState(false);
  const toggle = useAction();

  async function setEnabled(enabled: boolean) {
    const out = await toggle.run(() => api<UserOut>(`/admin/users/${user.id}/${enabled ? "enable" : "disable"}`, { method: "POST" }));
    if (out.ok) await refresh();
  }

  const more: MenuItem[] = [];
  if (can(me, "users.reset_password")) more.push({ key: "reset", label: T.userDetails.resetPassword, onSelect: () => setPassword(true) });
  if (can(me, "users.enable_disable")) {
    more.push(
      user.is_active
        ? { key: "off", label: T.userDetails.signInOff, onSelect: () => void setEnabled(false), danger: true }
        : { key: "on", label: T.userDetails.signInOn, onSelect: () => void setEnabled(true) },
    );
  }
  // design office-head-picker, decision 17: a login that has never held an office says so
  const meta = primary
    ? [primary.designation, primary.office.name].filter(Boolean).join(" · ")
    : user.office === null
      ? T.userDetails.noOfficeYetLine
      : T.userDetails.noOfficeLine;

  return (
    <div className={a.umHead}>
      <div className={a.umFacts}>
        <p className={a.umMeta}>{meta}</p>
        <p className={a.umLine}>
          <span>{user.email}</span>
          {user.mobile ? <span>{user.mobile}</span> : null}
          <StatusBadge user={user} />
          <span>{T.userDetails.lastSignInLine(formatDateTime(user.last_login_at))}</span>
        </p>
        <ErrorBanner error={toggle.error} />
      </div>
      <div className={a.umActions}>
        {can(me, "users.edit") ? (
          <Button variant="secondary" onClick={() => setEditing(true)}>
            {T.userDetails.editProfileButton}
          </Button>
        ) : null}
        {more.length > 0 ? (
          <Menu label={T.userDetails.moreButton} items={more} />
        ) : null}
      </div>
      {editing ? <EditProfileDialog user={user} onClose={() => setEditing(false)} /> : null}
      {password ? <PasswordDialog user={user} onClose={() => setPassword(false)} /> : null}
    </div>
  );
}

function Overview({
  user,
  primary,
  activeCount,
  types,
}: {
  user: UserOut;
  primary: MembershipOut | undefined;
  activeCount: number;
  types: UserTypeLabel[] | undefined;
}) {
  return (
    <div className="stack">
      <div className={a.umOverview}>
        <section aria-label={T.userDetails.personTitle}>
          <h3>{T.userDetails.personTitle}</h3>
          <dl className="facts">
            <dt>{T.userDetails.fullNameLabel}</dt>
            <dd>{user.full_name}</dd>
            <dt>{T.users.email}</dt>
            <dd>{user.email}</dd>
            <dt>{T.users.mobile}</dt>
            <dd>{user.mobile ?? "—"}</dd>
            <dt>{T.userDetails.statusLabel}</dt>
            <dd>
              <StatusBadge user={user} />
            </dd>
            <dt>{T.users.lastLogin}</dt>
            <dd>{formatDateTime(user.last_login_at)}</dd>
          </dl>
        </section>
        <section aria-label={T.userDetails.primaryOfficeTitle}>
          <h3>{T.userDetails.primaryOfficeTitle}</h3>
          <dl className="facts">
            <dt>{T.userDetails.primaryOfficeLabel}</dt>
            <dd>{primary?.office.name ?? "—"}</dd>
            <dt>{T.userDetails.designationLabel}</dt>
            <dd>{primary?.designation ?? "—"}</dd>
            <dt>{T.userDetails.userTypeLabel}</dt>
            <dd>{primary ? <Badge tone="info">{labelOf(types, primary.role)}</Badge> : "—"}</dd>
            <dt>{T.userDetails.officesLabel}</dt>
            <dd>{T.userDetails.officesActive(activeCount)}</dd>
            <dt>{T.userDetails.memberSinceLabel}</dt>
            <dd>{formatDate(user.created_at)}</dd>
          </dl>
        </section>
      </div>
      <Notice>{T.userDetails.signInNotice}</Notice>
    </div>
  );
}

function OfficeCards({
  user,
  memberships,
  me,
  types,
  onFunctions,
}: {
  user: UserOut;
  memberships: MembershipOut[];
  me: Me;
  types: UserTypeLabel[] | undefined;
  onFunctions: (m: MembershipOut) => void;
}) {
  const refresh = useRefreshUser(user.id);
  // the ancestor path of each office, from the offices the caller can see (no extra rule: display only)
  const choices = useOfficeChoices("users", false, can(me, "users.view"));
  const paths = new Map((choices.data?.items ?? []).map((o) => [o.code, o.ancestors]));
  const [changing, setChanging] = useState<MembershipOut | null>(null);
  const [ending, setEnding] = useState<MembershipOut | null>(null);
  const [documentsOf, setDocumentsOf] = useState<MembershipOut | null>(null);
  const [adding, setAdding] = useState(false);
  const action = useAction();

  async function makePrimary(m: MembershipOut) {
    const out = await action.run(() => api(`/admin/users/${user.id}/primary-membership`, { method: "PUT", body: { membership: m.id } }));
    if (out.ok) await refresh();
  }

  async function reactivate(m: MembershipOut) {
    const out = await action.run(() => api(`/admin/users/${user.id}/memberships/${m.id}/reactivate`, { method: "POST" }));
    if (out.ok) await refresh();
  }

  function itemsOf(m: MembershipOut): MenuItem[] {
    const items: MenuItem[] = [];
    if (canAny(me, ["users.edit", "users.set_type"])) items.push({ key: "change", label: T.users.change, onSelect: () => setChanging(m) });
    if (!m.is_primary && can(me, "users.edit")) items.push({ key: "primary", label: T.users.makePrimary, onSelect: () => void makePrimary(m) });
    if (can(me, "users.view")) items.push({ key: "functions", label: T.users.showFunctions, onSelect: () => onFunctions(m) });
    if (canAny(me, ["users.propose_head", "admin.tickets"])) {
      items.push({ key: "orders", label: T.users.documents, onSelect: () => setDocumentsOf(m) });
    }
    if (can(me, "users.enable_disable")) {
      items.push({ key: "end", label: T.users.end, onSelect: () => setEnding(m), danger: true, separator: items.length > 0 });
    }
    return items;
  }

  return (
    <div className="stack">
      <ErrorBanner error={action.error} />
      {memberships.length === 0 ? (
        <EmptyState>{user.office === null ? T.userDetails.noOfficeYetEmpty : T.users.noMembership}</EmptyState>
      ) : null}
      <ul className={a.mcards} aria-label={T.userDetails.tabs.offices}>
        {memberships.map((m) => {
          const active = m.is_active !== false;
          const items = active ? itemsOf(m) : [];
          const path = paths.get(m.office.code);
          return (
            <li key={m.id} className={active ? a.mcard : `${a.mcard} ${a.mcardEnded}`} data-membership={m.id}>
              <div className={a.mcardTop}>
                <div className={a.mcardName}>
                  <span>
                    {m.office.name} <span className={a.codeTag}>{m.office.code}</span>
                  </span>
                  {path && path.length ? <span className="muted">{path.join(" › ")}</span> : null}
                </div>
                <span className={a.types}>
                  {m.is_primary && active ? <Badge tone="info">{T.userDetails.primaryBadge}</Badge> : null}
                  {active ? <Badge tone="success">{T.userDetails.activeBadge}</Badge> : <Badge>{T.userDetails.endedBadge}</Badge>}
                </span>
              </div>
              <dl className="facts">
                <dt>{T.userDetails.designationLabel}</dt>
                <dd>{m.designation ?? "—"}</dd>
                <dt>{T.userDetails.userTypeLabel}</dt>
                <dd>
                  <Badge tone="info">{labelOf(types, m.role)}</Badge>
                </dd>
                <dt>{active ? T.userDetails.sinceLabel : T.userDetails.periodLabel}</dt>
                <dd>{active ? formatDate(m.valid_from) : T.userDetails.period(formatDate(m.valid_from), formatDate(m.valid_to))}</dd>
              </dl>
              <div className={a.mcardFoot}>
                <span className="muted">
                  {!active ? T.userDetails.endedNote : m.is_primary ? T.userDetails.primaryNote : T.userDetails.additionalNote}
                </span>
                {active && items.length > 0 ? (
                  <Menu
                    label={T.userDetails.actionsAria(m.office.name)}
                    trigger={
                      <>
                        {T.userDetails.actionsButton}
                        <span aria-hidden="true"> ▾</span>
                      </>
                    }
                    items={items}
                  />
                ) : null}
                {!active && can(me, "users.enable_disable") ? (
                  <Button variant="secondary" size="sm" busy={action.busy} onClick={() => void reactivate(m)}>
                    {T.users.reactivate}
                  </Button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
      {can(me, "users.create") ? (
        <div>
          <Button variant="secondary" onClick={() => setAdding(true)}>
            {T.userDetails.addOfficeButton}
          </Button>
        </div>
      ) : null}
      {changing ? <ChangeMembership userId={user.id} membership={changing} me={me} types={types} onClose={() => setChanging(null)} /> : null}
      {ending ? <ExitDialog userId={user.id} membership={ending} onClose={() => setEnding(null)} /> : null}
      {adding ? <AddMembershipDialog userId={user.id} types={types} onClose={() => setAdding(false)} /> : null}
      <Dialog
        open={documentsOf !== null}
        title={`${T.users.documents}: ${documentsOf?.office.name ?? ""}`}
        onClose={() => setDocumentsOf(null)}
      >
        {documentsOf ? <MembershipDocuments userId={user.id} membershipId={documentsOf.id} /> : null}
      </Dialog>
    </div>
  );
}

function FunctionsTab({
  userId,
  memberships,
  loading,
  me,
  types,
  chosen,
  onChoose,
}: {
  userId: string;
  memberships: MembershipOut[];
  loading: boolean;
  me: Me;
  types: UserTypeLabel[] | undefined;
  chosen: string | null;
  onChoose: (id: string) => void;
}) {
  const membership = memberships.find((m) => m.id === chosen) ?? memberships[0];
  const functions = useQuery({
    queryKey: functionsKey(userId, membership?.id ?? ""),
    queryFn: () => api<MembershipFunctions>(`/admin/users/${userId}/memberships/${membership!.id}/permissions`),
    enabled: !!membership,
  });
  const permissions = usePermissions();
  const [exceptions, setExceptions] = useState(false);
  if (loading) return <Loading />;
  if (!membership) return <EmptyState>{T.userDetails.noActiveOfficeNote}</EmptyState>;
  const data = functions.data;
  const overrides = new Map((data?.overrides ?? []).filter((o) => o.is_active).map((o) => [o.permission, o.effect]));
  const given = [...overrides].filter(([, e]) => e === "grant").length;
  const taken = [...overrides].filter(([, e]) => e === "deny").length;
  const typeLabel = labelOf(types, membership.role);
  const groups = groupFunctions(permissions.data ?? [])
    .map((g) => ({
      ...g,
      items: g.items.filter((p) => data?.effective.includes(p.code) || overrides.get(p.code) === "deny"),
    }))
    .filter((g) => g.items.length > 0);

  return (
    <div className="stack">
      <div className={a.fnHead}>
        <SelectField
          label={T.userDetails.officeSelectLabel}
          value={membership.id}
          options={memberships.map((m) => ({ value: m.id, label: `${m.office.name} · ${labelOf(types, m.role)}` }))}
          onChange={(e) => onChoose(e.target.value)}
        />
        {data ? <p className="muted">{T.userDetails.holdsLine(data.effective.length, typeLabel, given, taken)}</p> : null}
        {can(me, "users.grant") ? (
          <Button variant="secondary" onClick={() => setExceptions(true)}>
            {T.userDetails.changeExceptionsButton}
          </Button>
        ) : null}
      </div>
      {functions.isPending || permissions.isPending ? <Loading /> : null}
      <ErrorBanner error={functions.error ?? permissions.error} onRetry={() => functions.refetch()} />
      {data
        ? groups.map((g) => (
            <Card key={g.code} title={g.label}>
              <ul className={a.fnList}>
                {g.items.map((p) => {
                  const effect = overrides.get(p.code);
                  return (
                    <li key={p.code} className={a.fnRow} data-taken={effect === "deny" || undefined}>
                      <div className={a.fnText}>
                        <span className={effect === "deny" ? `${a.fnName} ${a.fnTaken}` : a.fnName}>{p.label}</span>
                        {p.description ? <span className={a.fnDesc}>{p.description}</span> : null}
                      </div>
                      <span className={a.fnMark}>
                        {effect === "grant" ? <Badge tone="success">{T.userDetails.givenBadge}</Badge> : null}
                        {effect === "deny" ? <Badge tone="danger">{T.userDetails.takenBadge}</Badge> : null}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </Card>
          ))
        : null}
      <SidePanel
        open={exceptions}
        title={`${T.userDetails.changeExceptionsButton}: ${membership.office.name}`}
        onClose={() => setExceptions(false)}
        wide
      >
        {exceptions ? <MembershipFunctionsPanel userId={userId} membershipId={membership.id} me={me} /> : null}
      </SidePanel>
    </div>
  );
}

function Activity({ userId }: { userId: string }) {
  const rows = useQuery({
    queryKey: ["audit", "user", userId, 20],
    queryFn: () => api<AuditPage>("/audit", { query: { user: userId, limit: 20 } }),
  });
  return (
    <div className="stack">
      {rows.isPending ? <Loading /> : null}
      <ErrorBanner error={rows.error} onRetry={() => rows.refetch()} />
      {rows.data ? (
        rows.data.items.length === 0 ? (
          <EmptyState>{T.userDetails.noActivity}</EmptyState>
        ) : (
          <ol className={a.activity} aria-label={T.userDetails.activityCaption}>
            {rows.data.items.map((r) => (
              <li key={r.id}>
                <span className={a.activityWhen} data-lead="date">
                  {formatDateTime(r.at)}
                </span>
                <span className={a.activityBody}>
                  <Link href={`/audit/${r.id}`}>{actionName(r.action)}</Link>
                  <span className="muted">
                    {r.case?.case_no_text || r.case?.ref_no ? T.userDetails.caseLine(r.case.case_no_text ?? r.case.ref_no ?? "") : r.entity_type}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        )
      ) : null}
      <nav className="actions" aria-label={T.audit.links}>
        <Link href={`/audit${queryString({ user: userId })}`}>{T.userDetails.openInAudit}</Link>
        {/* the earlier page's second link (portal-audit-health, decision 7), kept */}
        <Link href={`/audit${queryString({ about_user: userId })}`}>{T.audit.aboutThisUser}</Link>
      </nav>
    </div>
  );
}
