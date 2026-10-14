/**
 * The navigation, declared once (design portal-shell, decision 13). An entry shows when the login holds one of
 * its functions (an empty list: everyone signed in) and its screen is built; unbuilt entries stay hidden until
 * their backlog rows. Showing an entry is convenience only: the API decides every figure and action.
 */
import type { Me, Permission } from "./api/types";
import { can, canAny, departmentsOf, tracksDepartment } from "./can";

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

/** The people and offices functions of Administration (the Designations tab shows with any of them). */
export const PEOPLE_ADMIN_FUNCTIONS: readonly Permission[] = [
  "users.view",
  "offices.manage",
  "admin.designations",
  "access.manage_types",
  "users.propose_head",
  "admin.tickets",
];

/** The department mapping functions (design portal-mapping, decision 2). */
export const MAPPING_FUNCTIONS: readonly Permission[] = [
  "admin.counsel_codes",
  "admin.keywords",
  "admin.watchlist",
  "admin.scoring",
];

/** The Administration entry of the sidebar: any people, offices or mapping function. */
export const ADMIN_FUNCTIONS: readonly Permission[] = [...PEOPLE_ADMIN_FUNCTIONS, ...MAPPING_FUNCTIONS];

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
  // design portal-causelist, decision 11: the published lists are court-public, read by every reader of cases
  { key: "causelist", label: "Cause list", href: "/causelist", functions: CASE_READERS, built: true },
  // design portal-files-alerts, decision 2: anyone may be sent a file, so Files shows with `cases.view_scope`
  { key: "files", label: "Files", href: "/files", functions: ["cases.view_scope"], built: true },
  { key: "alerts", label: "Alerts & calendar", href: "/alerts", functions: CASE_READERS, built: true },
  // design portal-reports, decision 2: the tabs inside come from `GET /reports`; the API decides every report
  { key: "reports", label: "Reports", href: "/reports", functions: ["reports.department", "reports.state"], built: true },
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
  { key: "designations", label: "Designations", href: "/admin/designations", functions: PEOPLE_ADMIN_FUNCTIONS },
  { key: "mapping", label: "Department mapping", href: "/admin/mapping", functions: MAPPING_FUNCTIONS },
  { key: "tickets", label: "Tickets", href: "/admin/tickets", functions: ["users.propose_head", "admin.tickets"] },
];

/**
 * The department mapping tabs (design portal-mapping, decision 2), each its own route. Scoring shows with the API's
 * read rule (`admin.scoring`, `admin.counsel_codes` or `admin.keywords`); only `admin.scoring` may change it.
 */
export const MAPPING_TABS: readonly AdminTab[] = [
  { key: "codes", label: "Counsel codes", href: "/admin/mapping/codes", functions: ["admin.counsel_codes"] },
  { key: "keywords", label: "Keywords and name patterns", href: "/admin/mapping/keywords", functions: ["admin.keywords"] },
  // design department-discovery, decision 13 (b): the department's names searched at the court and what they found
  { key: "discovery", label: "Court search", href: "/admin/mapping/discovery", functions: ["admin.keywords"] },
  { key: "watchlist", label: "Watchlist", href: "/admin/mapping/watchlist", functions: ["admin.watchlist"] },
  {
    key: "scoring",
    label: "Scoring",
    href: "/admin/mapping/scoring",
    functions: ["admin.scoring", "admin.counsel_codes", "admin.keywords"],
  },
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
  // design department-discovery, decision 13 (d): the discovery share, queue and finds (system figures only)
  { key: "discovery", label: "Discovery", href: "/data/discovery", functions: DATA_READERS },
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

export function mappingTabsFor(me: Pick<Me, "functions"> | null | undefined): AdminTab[] {
  return MAPPING_TABS.filter((tab) => visible(me, tab.functions));
}

export interface FilesTab {
  key: "mine" | "offices" | "department" | "sent";
  label: string;
  href: string;
  functions: readonly Permission[];
  show?: (me: MeLike) => boolean;
}

/**
 * The Files tabs (design portal-files-alerts, decisions 12 and 13), each its own route. "Department files" shows only
 * with a department membership holding `custody.track` (the API's tracked-departments rule).
 */
export const FILES_TABS: readonly FilesTab[] = [
  { key: "mine", label: "With me", href: "/files/mine", functions: CASE_READERS },
  { key: "offices", label: "My offices", href: "/files/offices", functions: CASE_READERS },
  { key: "department", label: "Department files", href: "/files/department", functions: [], show: tracksDepartment },
  { key: "sent", label: "Sent", href: "/files/sent", functions: CASE_READERS },
];

export function filesTabsFor(me: MeLike | null | undefined): FilesTab[] {
  if (!me) return [];
  return FILES_TABS.filter((tab) => (tab.show ? tab.show(me) : visible(me, tab.functions)));
}

/** The Alerts & calendar tabs (decision 1); both show to case readers. */
export const ALERTS_TABS: readonly DataTab[] = [
  { key: "list", label: "Alerts", href: "/alerts", functions: CASE_READERS },
  { key: "calendar", label: "Hearing calendar", href: "/alerts/calendar", functions: CASE_READERS },
];

export function alertsTabsFor(me: Pick<Me, "functions"> | null | undefined): DataTab[] {
  return ALERTS_TABS.filter((tab) => visible(me, tab.functions));
}

/**
 * Breadcrumb labels by full path, read before the segment labels (design portal-files-alerts, decision 3): the
 * segment `offices` means Administration → Offices and `alerts` the case tab, so the Files and Alerts screens are
 * named by path.
 */
export const CRUMB_PATHS: Record<string, string> = {
  "/causelist": "Cause list",
  "/files": "Files",
  "/files/mine": "With me",
  "/files/offices": "My offices",
  "/files/department": "Department files",
  "/files/sent": "Sent",
  "/alerts": "Alerts & calendar",
  "/alerts/calendar": "Hearing calendar",
  "/admin/mapping/discovery": "Court search",
  "/data/discovery": "Discovery",
  "/reports/pending-cases": "Pending cases",
  "/reports/hearings-disposals": "Hearings and disposals",
  "/reports/pending-actions": "Pending actions",
  "/reports/data-health": "Data collection health",
};

/** The breadcrumb label of a path (`CRUMB_PATHS` first, then the segment's label, else the segment itself). */
export function crumbLabel(path: string): string {
  const part = path.split("/").filter(Boolean).pop() ?? "";
  return CRUMB_PATHS[path] ?? CRUMBS[part] ?? decodeURIComponent(part);
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
  reports: "Reports",
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
  custody: "Custody and stage",
  alerts: "Alerts",
  mapping: "Department mapping",
  codes: "Counsel codes",
  keywords: "Keywords and name patterns",
  watchlist: "Watchlist",
  scoring: "Scoring",
};

/** The inbox tabs (design portal-cases, decisions 4-6), in order; which show comes from `/inbox/counts`. */
export const INBOX_TABS = [
  { key: "recommended", label: "Recommended", href: "/inbox/recommended" },
  { key: "claimed", label: "Claimed", href: "/inbox/claimed" },
  { key: "pool", label: "Unclaimed pool", href: "/inbox/pool" },
  { key: "transfers", label: "Transfers", href: "/inbox/transfers" },
] as const;

export type InboxTab = (typeof INBOX_TABS)[number]["key"];

/**
 * The case page tabs (design portal-cases, decision 10), each its own route under `/cases/[ref]`; "Custody and stage"
 * and "Alerts" come with portal-workflow (decision 2). The Alerts tab has no count (the overview carries none).
 */
export const CASE_TABS = [
  { key: "", label: "Overview", count: null },
  { key: "custody", label: "Custody and stage", count: null },
  { key: "hearings", label: "Hearings", count: "hearings" },
  { key: "orders", label: "Orders", count: "orders" },
  { key: "parties", label: "Parties", count: null },
  { key: "documents", label: "Documents", count: "documents" },
  { key: "links", label: "Linked cases", count: "links" },
  { key: "notes", label: "Notes", count: "notes" },
  { key: "alerts", label: "Alerts", count: null },
  { key: "timeline", label: "Timeline", count: "timeline" },
  { key: "details", label: "Details", count: null },
] as const;
