/**
 * The navigation, declared once (design portal-shell, decision 13; portal-ui-redesign, decision 4): three groups
 * (Work, Oversight, Settings). An entry shows when the login holds one of its functions (an empty list: everyone
 * signed in) and its screen is built; unbuilt entries stay hidden until their backlog rows. Showing an entry is
 * convenience only: the API decides every figure and action. Every label comes from `messages.ts`.
 *
 * Design portal-ui-polish-2, decisions 14 and 15: four entries expand one level (Administration, Data Collection,
 * Reports, System Health), their children declared here from `ADMIN_TABS`, `DATA_TABS`, `REPORT_TABS` and
 * `SYSTEM_SECTIONS` and filtered with the same function rule; `NavChild` has no `children`, so no deeper level can be
 * declared. An entry whose children are all hidden is a plain link. Built from routes and functions only, no API call.
 */
import type { Me, Permission } from "./api/types";
import { can, canAny, departmentsOf, readsAudit, tracksDepartment } from "./can";
import { T } from "./messages";
import { REPORT_TABS } from "./reports";

/** What the navigation reads of `/me`: the functions, and the memberships where an entry needs them. */
export type MeLike = Pick<Me, "functions"> & Partial<Pick<Me, "memberships" | "assistant_mode">>;

export type NavGroupKey = "work" | "oversight" | "settings";

/** The server figure shown in an entry's pill (decision 4): Case inbox (`working`) from `/inbox/mine/counts`, Case
 * claim from `/inbox/counts`, Alerts (`unread`) from `/alerts/counts`. */
export type NavCount = "alerts" | "inbox" | "claim";

/** Where the person is: the path, and the hash and query the `/system` sections are told apart by. */
export interface NavLocation {
  pathname: string;
  hash?: string;
  search?: string;
}

/**
 * One row under an expanding entry (decision 15). It has no `children` field: the menu is one level deep by type.
 * A child is active when the path starts with its `href`, or when its `match` says so.
 */
export interface NavChild {
  key: string;
  label: string;
  href: string;
  functions: readonly Permission[];
  show?: (me: MeLike) => boolean;
  match?: (loc: NavLocation) => boolean;
}

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
  /** The rows one level below (decision 14); after `navGroupsFor` only the visible ones, and absent when none is. */
  children?: readonly NavChild[];
}

/**
 * Case claim is read for one department at a time (design portal-cases, decision 3): it shows with `cases.view_all`,
 * or when a membership belongs to a department. The Case inbox no longer needs it (design case-inbox-merge, decision
 * 6): Working on, Sent by me and Disposed are for everyone, standing counsel and logins without a department included.
 */
export function showsInbox(me: MeLike): boolean {
  return can(me, "cases.view_all") || departmentsOf(me as Pick<Me, "memberships">).length > 0;
}

/**
 * The Case Assistant (design assistant, decision 14): the sidebar entry and the case tab show with `assistant.use`
 * while `/me.assistant_mode` is not `off` (SourceTrace chosen but not implemented reads `off`). Display only.
 */
export function showsAssistant(me: MeLike | null | undefined): boolean {
  return !!me && can(me, "assistant.use") && !!me.assistant_mode && me.assistant_mode !== "off";
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

/** Collect Now shows for any function that has a card on it (design data-collection-redesign, decision 1). */
export const COLLECT_FUNCTIONS: readonly Permission[] = ["admin.data_load", "admin.napix_refetch", "admin.masters_sync"];

/**
 * The Data Collection tabs (design data-collection-redesign, decision 1): Overview (where `/data` opens), Collect Now,
 * Automatic Collection and Problems and Fixes. The old Load, Discovery, Health, Queue and Calls and Duplicates tabs
 * redirect (`OLD_DATA_REDIRECTS`, decision 2).
 */
export const DATA_TABS: readonly DataTab[] = [
  { key: "overview", label: T.tabs.data.overview, href: "/data/overview", functions: DATA_READERS },
  { key: "collect", label: T.tabs.data.collect, href: "/data/collect", functions: COLLECT_FUNCTIONS },
  { key: "automatic", label: T.tabs.data.automatic, href: "/data/automatic", functions: DATA_READERS },
  { key: "problems", label: T.tabs.data.problems, href: "/data/problems", functions: DATA_READERS },
];

/**
 * The old Data Collection addresses (decision 2), client redirects keeping the query string (and the target's
 * anchor). Round 1 retired Load and Discovery and the first version's Fetch tab; round 2 Health, Queue and Calls and
 * Duplicates (decision 3 says where each of their pieces went). Every target is a final address.
 */
export const OLD_DATA_REDIRECTS: Record<string, string> = {
  "/data/load": "/data/automatic",
  "/data/discovery": "/data/automatic#department-names",
  "/data/fetch": "/data/collect",
  "/data/health": "/data/overview",
  "/data/queue": "/data/problems",
  "/data/duplicates": "/data/problems#duplicates",
};

/**
 * The functions that read the court-health endpoints (`/admin/data-health`, `/admin/napix/*`): the API's
 * `health_reader`. The failed-fetch rows and the court connection line read them; System Health's Court Calls section
 * needs one of them beside `admin.service_health` (design data-collection-redesign, decision 3).
 */
export const HEALTH_READERS: readonly Permission[] = ["reports.state", "admin.napix_refetch", "admin.masters_sync"];

/** Court Calls on System Health shows with `admin.service_health` and a health-reader function (decision 3). */
export function showsCourtCalls(me: Pick<Me, "functions"> | null | undefined): boolean {
  return can(me, "admin.service_health") && canAny(me, HEALTH_READERS);
}

/** The System Health entry's sections (decision 14): three anchors of `/system` and the Access Token modal. */
export const SYSTEM_SECTIONS: readonly NavChild[] = [
  {
    key: "court",
    label: T.nav.systemSections.court,
    href: "/system#court",
    functions: ["admin.service_health"],
    match: (loc) => loc.pathname === "/system" && loc.hash === "#court" && !apiOf(loc),
  },
  {
    key: "services",
    label: T.nav.systemSections.services,
    href: "/system#services",
    functions: ["admin.service_health"],
    match: (loc) => loc.pathname === "/system" && loc.hash === "#services" && !apiOf(loc),
  },
  // design data-collection-redesign, decision 3: the call log, the recent resets and the e-mail outbox
  {
    key: "calls",
    label: T.nav.systemSections.calls,
    href: "/system#calls",
    functions: ["admin.service_health"],
    show: showsCourtCalls,
    match: (loc) => loc.pathname === "/system" && loc.hash === "#calls" && !apiOf(loc),
  },
  {
    key: "token",
    label: T.nav.systemSections.token,
    href: "/system?api=token&tab=token",
    functions: ["admin.service_health"],
    match: (loc) => loc.pathname === "/system" && apiOf(loc) === "token",
  },
];

function apiOf(loc: NavLocation): string | null {
  return new URLSearchParams(loc.search ?? "").get("api");
}

/** The report children (decision 14): Data Health only with `reports.state`, the rule `GET /reports` applies. */
const REPORT_FUNCTIONS: Record<string, readonly Permission[]> = {
  "data-health": ["reports.state"],
};

export const REPORT_CHILDREN: readonly NavChild[] = REPORT_TABS.map((t) => ({
  key: t.key,
  label: t.label,
  href: t.href,
  functions: REPORT_FUNCTIONS[t.key] ?? ["reports.department", "reports.state"],
}));

const asChildren = (tabs: readonly { key: string; label: string; href: string; functions: readonly Permission[] }[]): NavChild[] =>
  tabs.map((t) => ({ key: t.key, label: t.label, href: t.href, functions: t.functions }));

export const NAV: readonly NavEntry[] = [
  { key: "dashboard", label: T.nav.dashboard, href: "/", group: "work", functions: [], built: true },
  {
    key: "inbox",
    label: T.nav.inbox,
    href: "/inbox",
    group: "work",
    functions: CASE_READERS,
    built: true,
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
  // design portal-ui-redesign, decision 8: My calendar (round 3, row 103); Alerts is its own entry
  { key: "calendar", label: T.nav.calendar, href: "/calendar", group: "work", functions: CASE_READERS, built: true },
  { key: "alerts", label: T.nav.alerts, href: "/alerts", group: "work", functions: CASE_READERS, built: true, count: "alerts" },
  { key: "search", label: T.nav.search, href: "/search", group: "work", functions: CASE_READERS, built: true },
  // design assistant, decision 14: after Search, with `assistant.use` while the assistant is on
  {
    key: "assistant",
    label: T.nav.assistant,
    href: "/assistant",
    group: "work",
    functions: ["assistant.use"],
    built: true,
    show: showsAssistant,
  },
  // design portal-reports, decision 2: the tabs inside come from `GET /reports`; the API decides every report
  {
    key: "reports",
    label: T.nav.reports,
    href: "/reports",
    group: "oversight",
    functions: ["reports.department", "reports.state"],
    built: true,
    children: REPORT_CHILDREN,
  },
  // design portal-audit-health, decision 2: only where the API serves the log (State-wide `audit.view`)
  { key: "audit", label: T.nav.audit, href: "/audit", group: "oversight", functions: ["audit.view"], built: true, show: readsAudit },
  {
    key: "data",
    label: T.nav.data,
    href: "/data/overview",
    group: "settings",
    functions: DATA_READERS,
    built: true,
    children: asChildren(DATA_TABS),
  },
  // design api-health-checker, decision 2: System health, after Data collection, for `admin.service_health` only
  {
    key: "system",
    label: T.nav.system,
    href: "/system",
    group: "settings",
    functions: ["admin.service_health"],
    built: true,
    children: SYSTEM_SECTIONS,
  },
  {
    key: "admin",
    label: T.nav.admin,
    href: "/admin",
    group: "settings",
    functions: ADMIN_FUNCTIONS,
    built: true,
    children: asChildren(ADMIN_TABS),
  },
];

export const NAV_GROUPS: readonly { key: NavGroupKey; label: string }[] = [
  { key: "work", label: T.nav.groups.work },
  { key: "oversight", label: T.nav.groups.oversight },
  { key: "settings", label: T.nav.groups.settings },
];

function visible(me: Pick<Me, "functions"> | null | undefined, functions: readonly Permission[]): boolean {
  return functions.length === 0 ? !!me : canAny(me, functions);
}

function shown(me: MeLike | null | undefined, item: { functions: readonly Permission[]; show?: (me: MeLike) => boolean }): boolean {
  return visible(me, item.functions) && (!item.show || (!!me && item.show(me)));
}

/** The visible entries; an expanding entry keeps only its visible children, and loses `children` when none is. */
export function navFor(me: MeLike | null | undefined): NavEntry[] {
  return filterNav(NAV, me);
}

/** `navFor` over any list of entries (the rule, apart from the declared menu). */
export function filterNav(entries: readonly NavEntry[], me: MeLike | null | undefined): NavEntry[] {
  return entries.filter((entry) => entry.built && shown(me, entry)).map((entry) => {
    if (!entry.children) return entry;
    const children = entry.children.filter((c) => shown(me, c));
    if (children.length > 0) return { ...entry, children };
    const plain: NavEntry = { ...entry };
    delete plain.children;
    return plain;
  });
}

/** A child is active when the path starts with its `href` or when its `match` says so (decision 15). */
export function childActive(child: NavChild, loc: NavLocation): boolean {
  if (child.match) return child.match(loc);
  return loc.pathname === child.href || loc.pathname.startsWith(child.href + "/");
}

/** The section of an entry: `/data/overview` stands for every `/data/...` page. */
export function entryActive(entry: Pick<NavEntry, "href">, pathname: string): boolean {
  if (entry.href === "/") return pathname === "/";
  const section = "/" + (entry.href.split("/")[1] ?? "");
  // design case-inbox-merge, decision 12: the case page sits under the Case inbox, as its crumb says
  if (section === "/inbox" && (pathname === "/cases" || pathname.startsWith("/cases/"))) return true;
  return pathname === section || pathname.startsWith(section + "/");
}

/** The key of the active child of an entry, if any. */
export function activeChild(entry: NavEntry, loc: NavLocation): string | null {
  return entry.children?.find((c) => childActive(c, loc))?.key ?? null;
}

/** An expanding entry is on the path when one of its children is active or the person is on one of its pages. */
export function onPath(entry: NavEntry, loc: NavLocation): boolean {
  return activeChild(entry, loc) !== null || entryActive(entry, loc.pathname);
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

/** The phone bottom bar (decision 18; design case-inbox-merge, decision 14): up to three of the login's entries among
 * Dashboard, Case inbox and Alerts. */
export const BOTTOM_BAR_KEYS: readonly string[] = ["dashboard", "inbox", "alerts"];

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

/**
 * The static segments that once held the Cases list (design case-workspace-admin, decision 3): they now redirect to the
 * Case inbox (design case-inbox-merge, decision 12) and stay static, so no case reference (dash-form ref_no, UUID or
 * CNR) is read as one of them.
 */
export const CASES_LIST_SEGMENTS: readonly string[] = ["with-me", "sent", "pending"];

/**
 * The old Files addresses and where they now live (design case-workspace-admin, decision 3, re-pointed by
 * case-inbox-merge, decision 12; a client redirect keeping the query string, as `OLD_INBOX_REDIRECTS`). Every target is
 * a final address: none is itself in a redirect map.
 */
export const OLD_FILES_REDIRECTS: Record<string, string> = {
  "/files": "/inbox/working",
  "/files/mine": "/inbox/working",
  "/files/offices": "/inbox/working?held=offices",
  "/files/department": "/inbox/pending",
  "/files/sent": "/inbox/sent",
  "/inbox/files": "/inbox/working",
};

/** The old Cases list addresses (design case-inbox-merge, decision 12): the tabs now live in the Case inbox. */
export const OLD_CASES_REDIRECTS: Record<string, string> = {
  "/cases/with-me": "/inbox/working",
  "/cases/sent": "/inbox/sent",
  "/cases/pending": "/inbox/pending",
};

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
  if (/^\/assistant\/orders\/[^/]+$/.test(path)) return T.assistant.courtRecord;
  // design case-workspace-admin, decision 25: one user type's page (its label is the page's own title)
  if (/^\/admin\/access\/[^/]+$/.test(path)) return T.access.typeCrumb;
  const part = path.split("/").filter(Boolean).pop() ?? "";
  return CRUMB_PATHS[path] ?? CRUMBS[part] ?? decodeURIComponent(part);
}

/** The breadcrumb label of a path segment. */
export const CRUMBS: Record<string, string> = T.crumbs;

/**
 * The portal paths that are only a level of the address, with no page of their own: their crumb is plain text, never a
 * link (a link to one answered 404 and its prefetch kept the court-record view from ever settling). Pinned against
 * `src/app` by `routes.test.ts`.
 */
export const CRUMBS_WITHOUT_PAGE: readonly string[] = ["/assistant/orders"];

/**
 * The Case inbox tabs (design portal-ui-redesign, decision 5; case-inbox-merge, decision 7: the Cases list folded in),
 * in the owner's order, each its own route. Which show is `inboxTabsFor`; the API decides every list.
 */
export const INBOX_TABS = [
  { key: "working", label: T.tabs.inbox.working, href: "/inbox/working" },
  { key: "sent", label: T.tabs.inbox.sent, href: "/inbox/sent" },
  { key: "claimed", label: T.tabs.inbox.claimed, href: "/inbox/claimed-by-me" },
  { key: "disposed", label: T.tabs.inbox.disposed, href: "/inbox/disposed" },
  { key: "department", label: T.tabs.inbox.department, href: "/inbox/department" },
  { key: "pending", label: T.tabs.inbox.pending, href: "/inbox/pending" },
] as const;

export type InboxTab = (typeof INBOX_TABS)[number]["key"];
export type InboxTabEntry = (typeof INBOX_TABS)[number];
/** The own-work views of `/inbox/mine` the portal reads (`files` stays in the API, unread by the portal). */
export type MyView = "working" | "claimed" | "disposed";

/**
 * Design case-inbox-merge, decision 7 (display only): Working on and Disposed with `cases.view_scope`; Sent by me with
 * `cases.view_scope` or `cases.view_all`; Claimed by me with `cases.claim`; Department cases with `cases.view_all` or a
 * `/inbox/counts` block read whole (`whole`); Pending action for a department membership holding `custody.track`.
 */
export function inboxTabsFor(me: MeLike | null | undefined, { whole = false }: { whole?: boolean } = {}): InboxTabEntry[] {
  if (!me) return [];
  const show: Record<InboxTab, boolean> = {
    working: can(me, "cases.view_scope"),
    sent: canAny(me, CASE_READERS),
    claimed: can(me, "cases.claim"),
    disposed: can(me, "cases.view_scope"),
    department: can(me, "cases.view_all") || whole,
    pending: tracksDepartment(me),
  };
  return INBOX_TABS.filter((t) => show[t.key]);
}

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
  // design assistant, decision 14: after Timeline, shown only by `showsAssistant`
  { key: "assistant", label: T.tabs.case.assistant, count: null, more: false },
  { key: "parties", label: T.tabs.case.parties, count: null, more: true },
  { key: "links", label: T.tabs.case.links, count: "links", more: true },
  { key: "custody", label: T.tabs.case.custody, count: null, more: true },
  { key: "alerts", label: T.tabs.case.alerts, count: null, more: true },
  { key: "details", label: T.tabs.case.details, count: null, more: true },
] as const;
