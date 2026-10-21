/**
 * The navigation, declared once (design portal-shell, decision 13; portal-ui-redesign, decision 4): three groups
 * (Work, Oversight, Settings). An entry shows when the login holds one of its functions (an empty list: everyone
 * signed in) and its screen is built; unbuilt entries stay hidden until their backlog rows. Showing an entry is
 * convenience only: the API decides every figure and action. Every label comes from `messages.ts`.
 */
import type { Me, Permission } from "./api/types";
import { can, canAny, departmentsOf, readsAudit, tracksDepartment } from "./can";
import { T } from "./messages";

/** What the navigation reads of `/me`: the functions, and the memberships where an entry needs them. */
export type MeLike = Pick<Me, "functions"> & Partial<Pick<Me, "memberships">>;

export type NavGroupKey = "work" | "oversight" | "settings";

/** The server figure shown in an entry's pill (decision 4): Case inbox (`working`) and Files (`files`) from
 * `/inbox/mine/counts`, Case claim from `/inbox/counts`, Alerts (`unread`) from `/alerts/counts`. */
export type NavCount = "alerts" | "inbox" | "claim" | "files";

export interface NavEntry {
  key: string;
  label: string;
  href: string;
  group: NavGroupKey;
  functions: readonly Permission[];
  built: boolean;
  /** A further condition on `/me` (besides the functions). */
  show?: (me: MeLike) => boolean;
  count?: NavCount;
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

/** The functions that open Case claim (decision 4); its tabs come from `/inbox/counts`. */
export const CLAIM_FUNCTIONS: readonly Permission[] = [
  "cases.claim",
  "cases.view_all",
  "cases.transfer_request",
  "cases.transfer_decide",
];

export const NAV: readonly NavEntry[] = [
  { key: "dashboard", label: T.nav.dashboard, href: "/", group: "work", functions: [], built: true },
  {
    key: "inbox",
    label: T.nav.inbox,
    href: "/inbox",
    group: "work",
    functions: CASE_READERS,
    built: true,
    show: showsInbox,
    count: "inbox",
  },
  // design portal-ui-redesign, decision 6: Case claim, built in round 2 (row 102)
  {
    key: "claim",
    label: T.nav.claim,
    href: "/claim",
    group: "work",
    functions: CLAIM_FUNCTIONS,
    built: true,
    show: showsInbox,
    count: "claim",
  },
  // design portal-causelist, decision 11: the published lists are court-public, read by every reader of cases
  { key: "causelist", label: T.nav.causelist, href: "/causelist", group: "work", functions: CASE_READERS, built: true },
  // design portal-files-alerts, decision 2: anyone may be sent a file, so Files shows with `cases.view_scope`
  { key: "files", label: T.nav.files, href: "/files", group: "work", functions: ["cases.view_scope"], built: true, count: "files" },
  // design portal-ui-redesign, decision 8: My calendar (round 3, row 103); Alerts is its own entry
  { key: "calendar", label: T.nav.calendar, href: "/calendar", group: "work", functions: CASE_READERS, built: true },
  { key: "alerts", label: T.nav.alerts, href: "/alerts", group: "work", functions: CASE_READERS, built: true, count: "alerts" },
  { key: "search", label: T.nav.search, href: "/search", group: "work", functions: CASE_READERS, built: true },
  // design portal-reports, decision 2: the tabs inside come from `GET /reports`; the API decides every report
  {
    key: "reports",
    label: T.nav.reports,
    href: "/reports",
    group: "oversight",
    functions: ["reports.department", "reports.state"],
    built: true,
  },
  // design portal-audit-health, decision 2: only where the API serves the log (State-wide `audit.view`)
  { key: "audit", label: T.nav.audit, href: "/audit", group: "oversight", functions: ["audit.view"], built: true, show: readsAudit },
  { key: "data", label: T.nav.data, href: "/data/load", group: "settings", functions: DATA_READERS, built: true },
  // design api-health-checker, decision 2: System health, after Data collection, for `admin.service_health` only
  { key: "system", label: T.nav.system, href: "/system", group: "settings", functions: ["admin.service_health"], built: true },
  { key: "admin", label: T.nav.admin, href: "/admin", group: "settings", functions: ADMIN_FUNCTIONS, built: true },
];

export const NAV_GROUPS: readonly { key: NavGroupKey; label: string }[] = [
  { key: "work", label: T.nav.groups.work },
  { key: "oversight", label: T.nav.groups.oversight },
  { key: "settings", label: T.nav.groups.settings },
];

export interface AdminTab {
  key: string;
  label: string;
  href: string;
  functions: readonly Permission[];
}

export const ADMIN_TABS: readonly AdminTab[] = [
  { key: "users", label: T.tabs.admin.users, href: "/admin/users", functions: ["users.view"] },
  { key: "access", label: T.tabs.admin.access, href: "/admin/access", functions: ["users.view", "access.manage_types"] },
  { key: "offices", label: T.tabs.admin.offices, href: "/admin/offices", functions: ["users.view", "offices.manage"] },
  { key: "designations", label: T.tabs.admin.designations, href: "/admin/designations", functions: PEOPLE_ADMIN_FUNCTIONS },
  { key: "mapping", label: T.tabs.admin.mapping, href: "/admin/mapping", functions: MAPPING_FUNCTIONS },
  { key: "tickets", label: T.tabs.admin.tickets, href: "/admin/tickets", functions: ["users.propose_head", "admin.tickets"] },
];

/**
 * The department mapping tabs (design portal-mapping, decision 2), each its own route. Scoring shows with the API's
 * read rule (`admin.scoring`, `admin.counsel_codes` or `admin.keywords`); only `admin.scoring` may change it.
 */
export const MAPPING_TABS: readonly AdminTab[] = [
  { key: "codes", label: T.tabs.mapping.codes, href: "/admin/mapping/codes", functions: ["admin.counsel_codes"] },
  { key: "keywords", label: T.tabs.mapping.keywords, href: "/admin/mapping/keywords", functions: ["admin.keywords"] },
  // design department-discovery, decision 13 (b): the department's names searched at the court and what they found
  { key: "discovery", label: T.tabs.mapping.discovery, href: "/admin/mapping/discovery", functions: ["admin.keywords"] },
  { key: "watchlist", label: T.tabs.mapping.watchlist, href: "/admin/mapping/watchlist", functions: ["admin.watchlist"] },
  {
    key: "scoring",
    label: T.tabs.mapping.scoring,
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
  { key: "load", label: T.tabs.data.load, href: "/data/load", functions: DATA_READERS },
  { key: "health", label: T.tabs.data.health, href: "/data/health", functions: DATA_READERS },
  { key: "queue", label: T.tabs.data.queue, href: "/data/queue", functions: DATA_READERS },
  { key: "duplicates", label: T.tabs.data.duplicates, href: "/data/duplicates", functions: DATA_READERS },
  // design department-discovery, decision 13 (d): the discovery share, queue and finds (system figures only)
  { key: "discovery", label: T.tabs.data.discovery, href: "/data/discovery", functions: DATA_READERS },
];

function visible(me: Pick<Me, "functions"> | null | undefined, functions: readonly Permission[]): boolean {
  return functions.length === 0 ? !!me : canAny(me, functions);
}

export function navFor(me: MeLike | null | undefined): NavEntry[] {
  return NAV.filter(
    (entry) => entry.built && visible(me, entry.functions) && (!entry.show || (!!me && entry.show(me))),
  );
}

export interface NavGroup {
  key: NavGroupKey;
  label: string;
  entries: NavEntry[];
}

/** The visible entries by group, in order; a group with no visible entry is left out (decision 4). */
export function navGroupsFor(me: MeLike | null | undefined): NavGroup[] {
  const entries = navFor(me);
  return NAV_GROUPS.map((g) => ({ ...g, entries: entries.filter((e) => e.group === g.key) })).filter(
    (g) => g.entries.length > 0,
  );
}

/** The phone bottom bar (decision 18): up to three of the login's entries among Dashboard, Case inbox and Files. */
export const BOTTOM_BAR_KEYS: readonly string[] = ["dashboard", "inbox", "files"];

export function bottomBarFor(me: MeLike | null | undefined): NavEntry[] {
  return navFor(me)
    .filter((e) => BOTTOM_BAR_KEYS.includes(e.key))
    .slice(0, 3);
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
  { key: "mine", label: T.tabs.files.mine, href: "/files/mine", functions: CASE_READERS },
  { key: "offices", label: T.tabs.files.offices, href: "/files/offices", functions: CASE_READERS },
  { key: "department", label: T.tabs.files.department, href: "/files/department", functions: [], show: tracksDepartment },
  { key: "sent", label: T.tabs.files.sent, href: "/files/sent", functions: CASE_READERS },
];

export function filesTabsFor(me: MeLike | null | undefined): FilesTab[] {
  if (!me) return [];
  return FILES_TABS.filter((tab) => (tab.show ? tab.show(me) : visible(me, tab.functions)));
}

/**
 * The Alerts tabs (design portal-ui-redesign, decision 8: the calendar moved to My calendar): the alerts show to case
 * readers; "Next dates to confirm" (design portal-next-dates, decision 1) with `next_dates.review`, the review API's
 * gate. `/alerts/calendar` is a redirect to `/calendar`.
 */
export const ALERTS_TABS: readonly DataTab[] = [
  { key: "list", label: T.tabs.alerts.list, href: "/alerts", functions: CASE_READERS },
  { key: "next-dates", label: T.tabs.alerts.nextDates, href: "/alerts/next-dates", functions: ["next_dates.review"] },
];

export function alertsTabsFor(me: Pick<Me, "functions"> | null | undefined): DataTab[] {
  return ALERTS_TABS.filter((tab) => visible(me, tab.functions));
}

/**
 * Breadcrumb labels by full path, read before the segment labels (design portal-files-alerts, decision 3): the
 * segment `offices` means Administration → Offices and `alerts` the case tab, so the Files and Alerts screens are
 * named by path.
 */
export const CRUMB_PATHS: Record<string, string> = T.crumbPaths;

/** The last crumb of one audit entry (`/audit/<id>`): the id is not a label. */
export const AUDIT_ENTRY_CRUMB = T.crumbEntry;

/** The breadcrumb label of a path (`CRUMB_PATHS` first, then the segment's label, else the segment itself). */
export function crumbLabel(path: string): string {
  if (/^\/audit\/[^/]+$/.test(path)) return AUDIT_ENTRY_CRUMB;
  const part = path.split("/").filter(Boolean).pop() ?? "";
  return CRUMB_PATHS[path] ?? CRUMBS[part] ?? decodeURIComponent(part);
}

/** The breadcrumb label of a path segment. */
export const CRUMBS: Record<string, string> = T.crumbs;

/**
 * The Case inbox tabs (design portal-ui-redesign, decision 5): the user's own work, each its own route; Department
 * cases only where `/inbox/counts` says `whole_department` for the selected department.
 */
export const INBOX_TABS = [
  { key: "working", label: T.tabs.inbox.working, href: "/inbox/working" },
  { key: "files", label: T.tabs.inbox.files, href: "/inbox/files" },
  { key: "claimed", label: T.tabs.inbox.claimed, href: "/inbox/claimed-by-me" },
  { key: "disposed", label: T.tabs.inbox.disposed, href: "/inbox/disposed" },
  { key: "department", label: T.tabs.inbox.department, href: "/inbox/department" },
] as const;

export type InboxTab = (typeof INBOX_TABS)[number]["key"];
export type MyView = Exclude<InboxTab, "department">;

/** Case claim (decision 6): the suggestions to decide on; which tabs show comes from `/inbox/counts`. */
export const CLAIM_TABS = [
  { key: "recommended", label: T.tabs.claim.recommended, href: "/claim/recommended" },
  { key: "pool", label: T.tabs.claim.pool, href: "/claim/pool" },
  { key: "transfers", label: T.tabs.claim.transfers, href: "/claim/transfers" },
] as const;

export type ClaimTab = (typeof CLAIM_TABS)[number]["key"];

/**
 * Decision 10.4: the old inbox URLs and where they now live (a client redirect keeping the query string).
 * `/inbox/claimed` goes to Department cases when the API says `whole_department`, else to Working on.
 */
export const OLD_INBOX_REDIRECTS: Record<string, string> = {
  "/inbox/recommended": "/claim/recommended",
  "/inbox/pool": "/claim/pool",
  "/inbox/transfers": "/claim/transfers",
};

/**
 * The case page tabs (design portal-cases, decision 10), each its own route under `/cases/[ref]`; "Custody and stage"
 * and "Alerts" come with portal-workflow (decision 2). Design portal-ui-redesign, decision 10.9: six tabs, and Parties,
 * Linked cases, Custody and stage, Alerts and Details under "More" (`more: true`); the routes are unchanged. The
 * Alerts tab has no count (the overview carries none).
 */
export const CASE_TABS = [
  { key: "", label: T.tabs.case.overview, count: null, more: false },
  { key: "hearings", label: T.tabs.case.hearings, count: "hearings", more: false },
  { key: "orders", label: T.tabs.case.orders, count: "orders", more: false },
  { key: "documents", label: T.tabs.case.documents, count: "documents", more: false },
  { key: "notes", label: T.tabs.case.notes, count: "notes", more: false },
  { key: "timeline", label: T.tabs.case.timeline, count: "timeline", more: false },
  { key: "parties", label: T.tabs.case.parties, count: null, more: true },
  { key: "links", label: T.tabs.case.links, count: "links", more: true },
  { key: "custody", label: T.tabs.case.custody, count: null, more: true },
  { key: "alerts", label: T.tabs.case.alerts, count: null, more: true },
  { key: "details", label: T.tabs.case.details, count: null, more: true },
] as const;
