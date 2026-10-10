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
