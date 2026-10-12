/**
 * The navigation, declared once (design portal-shell, decision 13). An entry shows when the login holds one of
 * its functions (an empty list: everyone signed in) and its screen is built; unbuilt entries stay hidden until
 * their backlog rows. Showing an entry is convenience only: the API decides every figure and action.
 */
import type { Me, Permission } from "./api/types";
import { can, canAny, departmentsOf } from "./can";

/** What the navigation reads of `/me`: the functions, and the memberships where an entry needs them. */
export type MeLike = Pick<Me, "functions"> & Partial<Pick<Me, "memberships">>;

export interface NavEntry {
  key: string;
  label: string;
  href: string;
  functions: readonly Permission[];
  built: boolean;
  /** A further condition on `/me` (besides the functions). */
  show?: (me: MeLike) => boolean;
}

/**
 * The case inbox is read for one department at a time (design portal-cases, decision 3): it shows with
 * `cases.view_all`, or when a membership belongs to a department; standing counsel and other logins without a
 * department use Search, whose default list is their visible cases.
 */
export function showsInbox(me: MeLike): boolean {
  return can(me, "cases.view_all") || departmentsOf(me as Pick<Me, "memberships">).length > 0;
}

export const CASE_READERS: readonly Permission[] = ["cases.view_scope", "cases.view_all"];

export const ADMIN_FUNCTIONS: readonly Permission[] = [
  "users.view",
  "offices.manage",
  "admin.designations",
  "access.manage_types",
  "users.propose_head",
  "admin.tickets",
];

/** Reading the data-collection screens (design data-load-console, decision 17); every action has its own function. */
export const DATA_READERS: readonly Permission[] = [
  "admin.data_load",
  "reports.state",
  "admin.napix_refetch",
  "admin.masters_sync",
];

export const NAV: readonly NavEntry[] = [
  { key: "dashboard", label: "Dashboard", href: "/", functions: [], built: true },
  { key: "inbox", label: "Case inbox", href: "/inbox", functions: CASE_READERS, built: true, show: showsInbox },
  { key: "search", label: "Search", href: "/search", functions: CASE_READERS, built: true },
  { key: "alerts", label: "Alerts & calendar", href: "/alerts", functions: CASE_READERS, built: false },
  { key: "reports", label: "Reports", href: "/reports", functions: ["reports.department", "reports.state"], built: false },
  { key: "audit", label: "Audit log", href: "/audit", functions: ["audit.view"], built: false },
  { key: "data", label: "Data collection", href: "/data/load", functions: DATA_READERS, built: true },
  { key: "admin", label: "Administration", href: "/admin", functions: ADMIN_FUNCTIONS, built: true },
];

export interface AdminTab {
  key: string;
  label: string;
  href: string;
  functions: readonly Permission[];
}

export const ADMIN_TABS: readonly AdminTab[] = [
  { key: "users", label: "Users", href: "/admin/users", functions: ["users.view"] },
  { key: "access", label: "User types", href: "/admin/access", functions: ["users.view", "access.manage_types"] },
  { key: "offices", label: "Offices", href: "/admin/offices", functions: ["users.view", "offices.manage"] },
  { key: "designations", label: "Designations", href: "/admin/designations", functions: ADMIN_FUNCTIONS },
  { key: "tickets", label: "Tickets", href: "/admin/tickets", functions: ["users.propose_head", "admin.tickets"] },
];

export interface DataTab {
  key: string;
  label: string;
  href: string;
  functions: readonly Permission[];
}

export const DATA_TABS: readonly DataTab[] = [
  { key: "load", label: "Load", href: "/data/load", functions: DATA_READERS },
  { key: "health", label: "Health", href: "/data/health", functions: DATA_READERS },
  { key: "queue", label: "Queue and calls", href: "/data/queue", functions: DATA_READERS },
  { key: "duplicates", label: "Duplicates", href: "/data/duplicates", functions: DATA_READERS },
];

function visible(me: Pick<Me, "functions"> | null | undefined, functions: readonly Permission[]): boolean {
  return functions.length === 0 ? !!me : canAny(me, functions);
}

export function navFor(me: MeLike | null | undefined): NavEntry[] {
  return NAV.filter(
    (entry) => entry.built && visible(me, entry.functions) && (!entry.show || (!!me && entry.show(me))),
  );
}

export function dataTabsFor(me: Pick<Me, "functions"> | null | undefined): DataTab[] {
  return DATA_TABS.filter((tab) => visible(me, tab.functions));
}

export function adminTabsFor(me: Pick<Me, "functions"> | null | undefined): AdminTab[] {
  return ADMIN_TABS.filter((tab) => visible(me, tab.functions));
}

/** The breadcrumb label of a path segment. */
export const CRUMBS: Record<string, string> = {
  admin: "Administration",
  users: "Users",
  new: "New",
  access: "User types",
  offices: "Offices",
  designations: "Designations",
  tickets: "Tickets",
  profile: "My profile",
  data: "Data collection",
  load: "Load",
  health: "Health",
  queue: "Queue and calls",
  duplicates: "Duplicates",
  inbox: "Case inbox",
  recommended: "Recommended",
  claimed: "Claimed",
  pool: "Unclaimed pool",
  transfers: "Transfers",
  search: "Search",
  cases: "Cases",
  hearings: "Hearings",
  orders: "Orders",
  parties: "Parties",
  documents: "Documents",
  links: "Linked cases",
  notes: "Notes",
  timeline: "Timeline",
  details: "Details",
};

/** The inbox tabs (design portal-cases, decisions 4-6), in order; which show comes from `/inbox/counts`. */
export const INBOX_TABS = [
  { key: "recommended", label: "Recommended", href: "/inbox/recommended" },
  { key: "claimed", label: "Claimed", href: "/inbox/claimed" },
  { key: "pool", label: "Unclaimed pool", href: "/inbox/pool" },
  { key: "transfers", label: "Transfers", href: "/inbox/transfers" },
] as const;

export type InboxTab = (typeof INBOX_TABS)[number]["key"];

/** The case page tabs (design portal-cases, decision 10), each its own route under `/cases/[ref]`. */
export const CASE_TABS = [
  { key: "", label: "Overview", count: null },
  { key: "hearings", label: "Hearings", count: "hearings" },
  { key: "orders", label: "Orders", count: "orders" },
  { key: "parties", label: "Parties", count: null },
  { key: "documents", label: "Documents", count: "documents" },
  { key: "links", label: "Linked cases", count: "links" },
  { key: "notes", label: "Notes", count: "notes" },
  { key: "timeline", label: "Timeline", count: "timeline" },
  { key: "details", label: "Details", count: null },
] as const;
