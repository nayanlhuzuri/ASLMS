import type { Me } from "./types";

export type Role =
  | "state_oversight"
  | "dept_head"
  | "dept_admin"
  | "dept_officer"
  | "directorate_user"
  | "referral_reviewer"
  | "standing_counsel"
  | "central_operator"
  | "auditor";

export const ROLE_LABELS: Record<string, string> = {
  state_oversight: "State oversight (read-only)",
  dept_head: "Department head",
  dept_admin: "Department administrator",
  dept_officer: "Department officer",
  directorate_user: "Directorate user",
  referral_reviewer: "Referral reviewer",
  standing_counsel: "Standing counsel",
  central_operator: "Central operator",
  auditor: "Auditor (read-only)",
};

export const ALL_ROLES = Object.keys(ROLE_LABELS) as Role[];

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

const has = (me: Me, ...roles: Role[]) => roles.includes(me.role as Role);

export const isStateTier = (me: Me) => has(me, "state_oversight", "auditor", "central_operator");
export const isDeptLead = (me: Me) => has(me, "dept_admin", "dept_head");
export const isOperator = (me: Me) => has(me, "central_operator");

/** Case Inbox: departments act on recommendations; the State tier can see the unclaimed pool. */
export const canSeeInbox = (me: Me) =>
  has(me, "dept_admin", "dept_head", "central_operator", "state_oversight", "auditor");
/** Recommended / Claimed / Transfers need a department to act for. */
export const canUseDeptInbox = (me: Me) => has(me, "dept_admin", "dept_head", "central_operator");
export const canSeeReports = (me: Me) =>
  has(me, "dept_admin", "dept_head", "central_operator", "state_oversight", "auditor");
export const canSeeDataHealth = (me: Me) => has(me, "central_operator", "state_oversight", "auditor", "dept_admin");
export const canSeeAdmin = (me: Me) =>
  has(me, "dept_admin", "central_operator", "dept_head", "state_oversight", "auditor");
export const canSeeAudit = (me: Me) =>
  has(me, "auditor", "central_operator", "state_oversight", "dept_admin", "dept_head");
/** Adding to the department watchlist. */
export const canWatch = (me: Me) => !me.read_only && has(me, "dept_admin", "dept_head", "central_operator");
export const canWrite = (me: Me) => !me.read_only;
