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
