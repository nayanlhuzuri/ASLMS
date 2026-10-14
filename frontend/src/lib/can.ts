import type { Me, Permission } from "./api/types";

/** Whether the signed-in login holds the function in any active membership (`/me.functions`, the gate only). */
export function can(me: Pick<Me, "functions"> | null | undefined, fn: Permission): boolean {
  return !!me && me.functions.includes(fn);
}

export function canAny(me: Pick<Me, "functions"> | null | undefined, fns: readonly Permission[]): boolean {
  return fns.some((fn) => can(me, fn));
}

/** Display only: the API decides what the super admin may do. */
export function isSuperAdmin(me: Pick<Me, "memberships"> | null | undefined): boolean {
  return !!me?.memberships?.some((m) => m.role === "super_admin" && m.is_active !== false);
}

/**
 * Whether the login's membership in `department` holds the function (`/me.memberships[].functions`): the inbox rows,
 * whose state the tab fixes, show actions by the function of the selected department's membership. Display only;
 * the API decides every call.
 */
export function canIn(
  me: Pick<Me, "memberships"> | null | undefined,
  department: string | null | undefined,
  fn: Permission,
): boolean {
  if (!me || !department) return false;
  return (me.memberships ?? []).some(
    (m) => m.is_active !== false && m.department_code === department && (m.functions ?? []).includes(fn),
  );
}

/** The department codes of the login's active memberships, in `/me` order, once each. */
export function departmentsOf(me: Pick<Me, "memberships"> | null | undefined): string[] {
  const out: string[] = [];
  for (const m of me?.memberships ?? []) {
    if (m.is_active !== false && m.department_code && !out.includes(m.department_code)) out.push(m.department_code);
  }
  return out;
}

/**
 * Whether the login tracks a department's files (design portal-files-alerts, decision 12): an active membership with
 * a `department_code` holding `custody.track` (the API's `_tracked_departments` rule; the super admin's State
 * membership has no department). Display only; the API decides.
 */
export function tracksDepartment(me: Partial<Pick<Me, "memberships">> | null | undefined): boolean {
  return (me?.memberships ?? []).some(
    (m) => m.is_active !== false && !!m.department_code && (m.functions ?? []).includes("custody.track"),
  );
}

/**
 * Whether the login reads the audit log (design portal-audit-health, decision 2; the API's audit-screens decision 2):
 * `audit.view` held in a State-wide membership, that is an active super admin membership, or an active membership
 * holding both `audit.view` and `cases.view_all` (the Auditor type). A department membership granted `audit.view`
 * alone does not read it. Display only; the API decides.
 */
export function readsAudit(me: (Pick<Me, "functions"> & Partial<Pick<Me, "memberships">>) | null | undefined): boolean {
  if (!me || !me.functions.includes("audit.view")) return false;
  return (me.memberships ?? []).some((m) => {
    if (m.is_active === false) return false;
    if (m.role === "super_admin") return true;
    const fns = m.functions ?? [];
    return fns.includes("audit.view") && fns.includes("cases.view_all");
  });
}
