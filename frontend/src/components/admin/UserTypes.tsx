"use client";

/**
 * User types on the Settings hub (design case-workspace-admin, decisions 24-27; template A):
 * - the index (`/admin/access`): one card per user type, in `ref_role` order, with its label and description, the
 *   logins of that type in the caller's scope, "n of N functions on" and an amber "n changed from default"
 *   (`GET /admin/access/overview`); a card opens the type's page. Readable with `users.view`.
 * - the type's page (`/admin/access/[role]`): the functions in plain-language groups, in the order the API gives
 *   (`group`, `sort_in_group` on `GET /admin/permissions`, so the portal holds no copy of the mapping), each a switch
 *   with its one-line description and "Changed from default" against the seed's defaults (`GET /admin/access/defaults`);
 *   a search, "Only changed from default" and "Reset to default" (the draft only); the sticky Save bar counting the
 *   unsaved changes against the saved state, with Discard and the one primary "Save changes", which sends one
 *   `PUT /admin/access/types/{role}` with the changed entries only (one transaction; a refusal saves nothing).
 *   Leaving with unsaved changes asks first. The super admin type is all on and locked; `admin.tickets` is reserved;
 *   retired functions are not shown; without `access.manage_types` every switch is disabled. The API decides.
 * - design portal-ui-polish-2, decisions 12-14: the header shows the label, the code as a muted tag and the
 *   description; "Edit Name" (with `access.manage_types`) changes the display name and short description through
 *   `PATCH /admin/access/types/{role}/name` and drops the cached labels and cards so every screen shows the new name;
 *   a "Jump To" list of the function groups sits beside them on laptops and is a select on phones.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useId, useMemo, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CharCounter,
  Chip,
  ConfirmDialog,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  SelectField,
  Switch,
  TextArea,
  TextField,
  usePrefersReducedMotion,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { labelOf, useLabels, useMe } from "@/lib/api/hooks";
import type { PermissionInfo } from "@/lib/api/types";
import { can } from "@/lib/can";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import a from "./admin.module.css";

type Row = Record<string, boolean>;

export interface UserTypeCard {
  code: string;
  users: number;
  functions_on: number;
  functions_total: number;
  changed_from_default: number;
}

export const SUPER_ADMIN = "super_admin";
export const RESERVED = new Set(["admin.tickets"]);

const KEYS = {
  labels: ["reference", "labels"] as const,
  overview: ["admin", "access", "overview"] as const,
  defaults: ["admin", "access", "defaults"] as const,
  permissions: ["admin", "permissions"] as const,
  type: (role: string) => ["admin", "access", "type", role] as const,
};

function useOverview() {
  return useQuery({ queryKey: KEYS.overview, queryFn: () => api<UserTypeCard[]>("/admin/access/overview") });
}

function usePermissions() {
  return useQuery({
    queryKey: KEYS.permissions,
    queryFn: () => api<PermissionInfo[]>("/admin/permissions"),
    staleTime: 10 * 60_000,
  });
}

/** Decision 26: the active functions by their group, in the API's order (group order by first appearance). */
export function groupFunctions(permissions: PermissionInfo[]): { code: string; label: string; items: PermissionInfo[] }[] {
  const shown = permissions.filter((p) => p.is_active && p.group);
  const groups: { code: string; label: string; items: PermissionInfo[]; first: number }[] = [];
  for (const p of shown) {
    let g = groups.find((x) => x.code === p.group);
    if (!g) {
      g = { code: p.group!, label: p.group_label ?? p.group!, items: [], first: groups.length };
      groups.push(g);
    }
    g.items.push(p);
  }
  for (const g of groups) g.items.sort((x, y) => (x.sort_in_group ?? 0) - (y.sort_in_group ?? 0));
  return groups;
}

export function UserTypesIndex() {
  const labels = useLabels();
  const overview = useOverview();
  if (overview.isPending || labels.isPending) return <Loading />;
  if (overview.error || !overview.data) return <ErrorBanner error={overview.error} onRetry={() => overview.refetch()} />;
  const types = labels.data?.user_types ?? [];
  return (
    <section className="stack" aria-label={T.access.indexTitle}>
      <div className={a.groupHead}>
        <div>
          <h2>{T.access.indexTitle}</h2>
          <p className="muted">{T.access.indexSubtitle}</p>
        </div>
      </div>
      <ul className={a.typeCards} aria-label={T.access.cards}>
        {overview.data.map((card) => {
          const type = types.find((t) => t.code === card.code);
          const label = type?.label ?? card.code;
          return (
            <li key={card.code}>
              <Link href={`/admin/access/${card.code}`} className={a.typeCard} aria-label={label}>
                <h3>{label}</h3>
                <p>{type?.description ?? ""}</p>
                <div className={a.typeFoot}>
                  <span>{T.access.users(card.users)}</span>
                  <span>{T.access.functionsOn(card.functions_on, card.functions_total)}</span>
                  {card.changed_from_default > 0 ? <Badge tone="warning">{T.access.changed(card.changed_from_default)}</Badge> : null}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * Asks before leaving with unsaved changes (decision 25): a confirm dialog for in-app links (a click on any link of
 * the page, caught before the router sees it) and the browser's own question when the tab closes or reloads.
 */
export function useLeaveGuard(dirty: boolean) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const link = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
      const href = link.getAttribute("href") ?? "";
      if (!href.startsWith("/") || href.startsWith("//")) return;
      e.preventDefault();
      e.stopPropagation();
      setPending(href);
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty]);
  return {
    pending,
    stay: () => setPending(null),
    leave: () => {
      const href = pending;
      setPending(null);
      if (href) router.push(href);
    },
  };
}

function changesBetween(codes: string[], from: Row, to: Row): { permission: string; enabled: boolean }[] {
  return codes.filter((c) => !!from[c] !== !!to[c]).map((c) => ({ permission: c, enabled: !!to[c] }));
}

export function SaveBar({
  count,
  busy,
  onSave,
  onDiscard,
}: {
  count: number;
  busy: boolean;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const reduced = usePrefersReducedMotion();
  return (
    <div className={a.saveBar} role="region" aria-label={T.access.saveBar} data-count={count}>
      <div className={a.saveText} aria-live="polite">
        {/* the count bumps through the motion tokens; under reduced motion it changes without animation */}
        <span key={reduced ? "n" : count} className={reduced ? a.saveCount : `${a.saveCount} ${a.bump}`} aria-hidden="true">
          {count}
        </span>
        <span>{T.access.unsaved(count)}</span>
      </div>
      <Button variant="ghost" onClick={onDiscard} disabled={count === 0 || busy}>
        {T.access.discard}
      </Button>
      <Button onClick={onSave} disabled={count === 0} busy={busy}>
        {T.access.saveChanges}
      </Button>
    </div>
  );
}

function FunctionRow({
  p,
  on,
  changed,
  disabled,
  note,
  onChange,
}: {
  p: PermissionInfo;
  on: boolean;
  changed: boolean;
  disabled: boolean;
  note?: string;
  onChange: (on: boolean) => void;
}) {
  const descId = useId();
  return (
    <li className={a.fnRow} data-function={p.code}>
      <Switch checked={on} onChange={onChange} label={p.label} describedBy={descId} disabled={disabled} />
      <div className={a.fnText}>
        <div className={a.fnName}>{p.label}</div>
        <div id={descId} className={a.fnDesc}>
          {note ?? p.description}
        </div>
      </div>
      <div className={a.fnMark}>{changed ? <Badge tone="warning">{T.access.changedBadge}</Badge> : null}</div>
    </li>
  );
}

export const NAME_MAX = 80;
export const DESCRIPTION_MAX = 200;

interface NameOut {
  code: string;
  label: string;
  description: string | null;
  changed: boolean;
}

/**
 * Edit Name (decision 13): the display name (required, 80 characters, different from every other type without regard
 * to case: warned in the browser from `/reference/labels`, and the server's 409 shown on the field) and the short
 * description (200 characters). The trimmed values go to `PATCH /admin/access/types/{role}/name`.
 */
function EditNameDialog({
  open,
  role,
  label,
  description,
  others,
  onClose,
  onSaved,
}: {
  open: boolean;
  role: string;
  label: string;
  description: string;
  others: string[];
  onClose: () => void;
  onSaved: (out: NameOut) => void;
}) {
  const [name, setName] = useState(label);
  const [desc, setDesc] = useState(description);
  const [tried, setTried] = useState(false);
  const save = useAction();
  const nameCounter = useId();
  const descCounter = useId();
  const clean = name.trim().replace(/\s+/g, " ");
  const taken = clean !== "" && others.some((o) => o.trim().toLowerCase() === clean.toLowerCase());
  const serverTaken = save.error instanceof ApiError && save.error.status === 409;
  const serverField = save.error instanceof ApiError && save.error.status === 422 ? save.error.message : null;
  const tooLong = clean.length > NAME_MAX;
  const nameError =
    tried && !clean ? T.access.nameRequired : taken || serverTaken ? T.access.nameTaken : (serverField ?? undefined);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTried(true);
    if (!clean || taken || tooLong || desc.trim().length > DESCRIPTION_MAX) return;
    const out = await save.run(() =>
      api<NameOut>(`/admin/access/types/${role}/name`, {
        method: "PATCH",
        body: { label: clean, description: desc.trim() || null },
      }),
    );
    if (out.ok) onSaved(out.value);
  }

  return (
    <Dialog
      open={open}
      title={T.access.editName}
      subtitle={T.access.internalCode(role)}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.busy}>
            {T.cancel}
          </Button>
          <Button type="submit" form={`edit-name-${role}`} busy={save.busy}>
            {T.save}
          </Button>
        </>
      }
    >
      <form id={`edit-name-${role}`} className="stack" onSubmit={submit} noValidate>
        <TextField
          label={T.access.displayName}
          hint={T.access.displayNameHint}
          value={name}
          required
          error={nameError}
          onChange={(e) => {
            save.reset();
            setName(e.target.value);
          }}
        />
        <CharCounter id={nameCounter} value={clean} max={NAME_MAX} />
        <TextArea
          label={T.access.shortDescription}
          value={desc}
          rows={3}
          onChange={(e) => {
            save.reset();
            setDesc(e.target.value);
          }}
        />
        <CharCounter id={descCounter} value={desc.trim()} max={DESCRIPTION_MAX} />
        <Notice>{T.access.codeNotice(role)}</Notice>
        {save.error && !serverTaken && !serverField ? <ErrorBanner error={save.error} /> : null}
      </form>
    </Dialog>
  );
}

/** Decision 14: anchor links to each function group; a select on phones (CSS shows one or the other). */
function JumpTo({ groups }: { groups: { code: string; label: string }[] }) {
  const go = (code: string) => {
    if (!code) return;
    document.getElementById(`group-${code}`)?.scrollIntoView?.({ block: "start" });
    window.history.replaceState(window.history.state, "", `#group-${code}`);
  };
  return (
    <>
      <nav className={a.jumpNav} aria-label={T.access.jumpTo}>
        <p className={a.jumpHead} aria-hidden="true">
          {T.access.jumpTo}
        </p>
        <ul>
          {groups.map((g) => (
            <li key={g.code}>
              <a href={`#group-${g.code}`}>{g.label}</a>
            </li>
          ))}
        </ul>
      </nav>
      <div className={a.jumpSelect}>
        <SelectField
          label={T.access.jumpTo}
          value=""
          onChange={(e) => go(e.target.value)}
          options={[{ value: "", label: T.access.jumpToChoose }, ...groups.map((g) => ({ value: g.code, label: g.label }))]}
        />
      </div>
    </>
  );
}

export function UserTypePage({ role }: { role: string }) {
  const me = useMe();
  const labels = useLabels();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const overview = useOverview();
  const defaults = useQuery({ queryKey: KEYS.defaults, queryFn: () => api<Record<string, Row>>("/admin/access/defaults") });
  const saved = useQuery({ queryKey: KEYS.type(role), queryFn: () => api<Row>(`/admin/access/types/${role}`) });
  const [draft, setDraft] = useState<Row | null>(null);
  const [query, setQuery] = useState("");
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const save = useAction();
  const groups = useMemo(() => groupFunctions(permissions.data ?? []), [permissions.data]);
  const codes = useMemo(() => groups.flatMap((g) => g.items.map((p) => p.code as string)), [groups]);
  const base: Row = saved.data ?? {};
  const current: Row = draft ?? base;
  const unsaved = changesBetween(codes, base, current);
  const guard = useLeaveGuard(unsaved.length > 0);

  if (saved.isPending || permissions.isPending || defaults.isPending || labels.isPending || me.isPending) return <Loading />;
  if (saved.error instanceof ApiError && saved.error.status === 422) return <EmptyState>{T.access.unknownType}</EmptyState>;
  const error = saved.error ?? permissions.error ?? defaults.error;
  if (error || !saved.data || !permissions.data || !defaults.data) {
    return <ErrorBanner error={error} onRetry={() => saved.refetch()} />;
  }

  const type = (labels.data?.user_types ?? []).find((t) => t.code === role);
  const dflt: Row = defaults.data[role] ?? {};
  const isSuper = role === SUPER_ADMIN;
  const canRename = can(me.data, "access.manage_types");
  const editable = canRename && !isSuper;
  const card = overview.data?.find((c) => c.code === role);
  const savedOn = codes.filter((c) => base[c]).length;
  const locked = (code: string) => isSuper || RESERVED.has(code);
  const needle = query.trim().toLowerCase();
  const visible = (p: PermissionInfo) =>
    (!needle || `${p.label} ${p.description ?? ""}`.toLowerCase().includes(needle)) &&
    (!onlyChanged || !!current[p.code] !== !!dflt[p.code]);
  const shownGroups = groups.map((g) => ({ ...g, shown: g.items.filter(visible) })).filter((g) => g.shown.length > 0);

  function set(code: string, on: boolean) {
    setNotice(null);
    save.reset();
    setDraft({ ...current, [code]: on });
  }

  function resetToDefault() {
    setNotice(null);
    const next: Row = { ...current };
    for (const c of codes) if (!locked(c)) next[c] = !!dflt[c];
    setDraft(next);
  }

  async function doSave() {
    if (unsaved.length === 0) return;
    const out = await save.run(() =>
      api<Row>(`/admin/access/types/${role}`, { method: "PUT", body: { changes: unsaved } }),
    );
    if (!out.ok) return;
    queryClient.setQueryData(KEYS.type(role), out.value);
    setDraft(null);
    setNotice(T.access.saved);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: KEYS.overview }),
      queryClient.invalidateQueries({ queryKey: ["admin", "access", "types"] }),
    ]);
  }

  const refusal =
    save.error instanceof ApiError && save.error.status === 400
      ? (() => {
          const message = save.error.message;
          const named = (permissions.data ?? []).find((p) => message.includes(p.code));
          return named ? T.access.refused(named.label, message) : message;
        })()
      : null;

  return (
    <section className="stack" aria-label={type?.label ?? role}>
      <div>
        <Link href="/admin/access">← {T.access.back}</Link>
      </div>
      <div className={a.groupHead}>
        <div>
          <div className={a.typeTitle}>
            <h2>{type ? labelOf(labels.data?.user_types, role) : role}</h2>
            <code className={a.codeTag}>{role}</code>
          </div>
          {type?.description ? <p className="muted">{type.description}</p> : null}
          <p className="muted">{T.access.counts(card?.users ?? 0, savedOn, codes.length)}</p>
        </div>
        {canRename ? (
          <Button variant="secondary" onClick={() => setEditing(true)}>
            {T.access.editName}
          </Button>
        ) : null}
      </div>
      <div className="row" role="search">
        <TextField
          label={T.access.find}
          placeholder={T.access.findPlaceholder}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Chip on={onlyChanged} onClick={() => setOnlyChanged((v) => !v)}>
          {T.access.onlyChanged}
        </Chip>
        {editable ? (
          <Button variant="secondary" onClick={resetToDefault}>
            {T.access.reset}
          </Button>
        ) : null}
      </div>
      {isSuper ? <Notice>{T.access.superAdminLine}</Notice> : null}
      {notice ? <Notice>{notice}</Notice> : null}
      {/* a refusal names the function, and the draft stays for the user to change */}
      <ErrorBanner error={save.error} messages={refusal ? { reserved: () => refusal, retired: () => refusal, bad_request: () => refusal } : undefined} />

      {shownGroups.length === 0 ? <EmptyState>{T.access.noMatch}</EmptyState> : null}
      <div className={a.jumpLayout}>
        {shownGroups.length > 1 ? <JumpTo groups={shownGroups} /> : null}
        <div className={a.jumpGroups}>
          {shownGroups.map((g) => (
            <Card
              key={g.code}
              id={`group-${g.code}`}
              title={g.label}
              actions={<span className="muted">{T.access.groupOn(g.items.filter((p) => !!current[p.code]).length, g.items.length)}</span>}
            >
          <ul className={a.fnList} aria-label={g.label}>
            {g.shown.map((p) => (
              <FunctionRow
                key={p.code}
                p={p}
                on={isSuper ? true : !!current[p.code]}
                changed={!isSuper && !!current[p.code] !== !!dflt[p.code]}
                disabled={!editable || locked(p.code) || save.busy}
                note={RESERVED.has(p.code) ? T.access.reserved : undefined}
                onChange={(on) => set(p.code, on)}
              />
            ))}
          </ul>
            </Card>
          ))}
        </div>
      </div>
      {isSuper ? null : editable ? (
        <SaveBar count={unsaved.length} busy={save.busy} onSave={doSave} onDiscard={() => setDraft(null)} />
      ) : (
        <p className="muted">{T.access.readOnlyLine}</p>
      )}
      <ConfirmDialog
        open={guard.pending !== null}
        title={T.access.leaveTitle}
        onClose={guard.stay}
        onCancel={guard.stay}
        onConfirm={guard.leave}
        confirmLabel={T.access.leave}
        cancelLabel={T.access.stay}
        danger
      >
        <p>{T.access.leaveText(unsaved.length)}</p>
      </ConfirmDialog>
      {editing ? (
        <EditNameDialog
          open={editing}
          role={role}
          label={type?.label ?? role}
          description={type?.description ?? ""}
          others={(labels.data?.user_types ?? []).filter((t) => t.code !== role).map((t) => t.label)}
          onClose={() => setEditing(false)}
          onSaved={async (out) => {
            setEditing(false);
            setNotice(out.changed ? T.access.nameSaved : null);
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: KEYS.labels }),
              queryClient.invalidateQueries({ queryKey: KEYS.overview }),
            ]);
          }}
        />
      ) : null}
    </section>
  );
}
