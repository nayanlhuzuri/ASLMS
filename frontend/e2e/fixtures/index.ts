/**
 * The answers to the portal's API calls during the browser check (design portal-ui-polish, decisions 18 and 20). Every
 * `/api/backend/**` request is answered in the browser: a `GET` from a typed override below, else from the synthetic
 * answer built from the API's OpenAPI document (`synth.ts`); a `GET` the API does not have is answered 404 and is a
 * finding, and any other method is answered 405 and is a finding too (the check never acts), apart from the session
 * watch's ping `POST /me/activity`, which records nothing and is answered with the default limits (design
 * session-timeout, "Tests"). The overrides are typed
 * against the generated `schema.d.ts`, so a fixture that no longer matches the API breaks the image build.
 */
import type { components } from "@/lib/api/schema";
import type {
  AlertList,
  AssistantThread,
  AuditPage,
  CounselCodeList,
  CustodyBrief,
  CustodyHistory,
  CustodyLeg,
  DashboardIndex,
  DashboardMe,
  HeldList,
  InboxCounts,
  Me,
  MembershipOut,
  MyCaseList,
  Note,
  NoteList,
  OfficeChoices,
  OfficeDetail,
  Permission,
  PermissionInfo,
  Report,
  ReportCatalogue,
  SentList,
  SystemHealth,
  UnmappedCode,
  UserOut,
} from "@/lib/api/types";

import { SAMPLE, STRESS, synth, synthFor } from "./synth";

type S = components["schemas"];

export { SAMPLE } from "./synth";

export interface Answer {
  status: number;
  body: unknown;
  /** A finding: the request had no fixture, or was not a `GET`. */
  problem?: string;
}

function schemaEnum(name: string): string[] {
  // the Permission enum, read through the synthesiser so the login holds every function the API knows
  const values = new Set<string>();
  for (let i = 0; i < 400; i += 1) {
    const v = synth({ $ref: `#/components/schemas/${name}` }, "", "", i) as string;
    if (values.has(v)) break;
    values.add(v);
  }
  return [...values];
}

const ALL_FUNCTIONS = schemaEnum("Permission") as Permission[];

const MEMBERSHIPS: MembershipOut[] = [
  {
    id: "0192a3b4-0000-7000-8000-0000000000m1",
    office: { code: "EDU", name: "Department of School Education, Government of Assam, Dispur", kind: "department" },
    department_code: "EDU",
    designation: STRESS.designation,
    role: "super_admin",
    is_primary: true,
    is_active: true,
    functions: ALL_FUNCTIONS,
  },
  {
    id: "0192a3b4-0000-7000-8000-0000000000m2",
    office: { code: "EDU-DSE", name: STRESS.office, kind: "directorate" },
    department_code: "EDU",
    designation: "Deputy Director (Administration and Law)",
    role: "directorate_user",
    is_primary: false,
    is_active: true,
    functions: ALL_FUNCTIONS,
  },
];

function me(): Me {
  const base = synth({ $ref: "#/components/schemas/MeOut" }) as Me;
  return {
    ...base,
    user: { ...base.user, id: SAMPLE.userId, full_name: "Anita Sharma Baruah", role: "super_admin", is_active: true, must_change_password: false, must_confirm_profile: false, memberships: MEMBERSHIPS },
    functions: ALL_FUNCTIONS,
    memberships: MEMBERSHIPS,
    // the Case Assistant shows only while it is on (design assistant, decision 14); the local model's state, its
    // banner, scope notes and the case tab's switch (design assistant-ollama, decision 14)
    assistant_mode: "ollama",
  };
}

const DASHBOARD: DashboardIndex = {
  me: true,
  state: true,
  departments: [
    { code: "EDU", name: "Department of School Education, Government of Assam, Dispur" },
    { code: "HEALTH", name: "Health and Family Welfare" },
  ],
};

/**
 * The run's IST day plus `days`, as `YYYY-MM-DD` (design next-hearing-highlight): the hearing bands are counted from
 * the IST day, so dates relative to it draw the same bands whenever the check runs. A copy of `istDay` and `addDays`
 * (lib/format.ts), since the fixtures import only types from the portal's source.
 */
function istDayPlus(days: number): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const d = new Date(`${get("year")}-${get("month")}-${get("day")}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** My Work's Upcoming Hearings (design next-hearing-highlight): rows today, tomorrow and in 4 days. */
function dashboardMe(): DashboardMe {
  const base = synthFor("/dashboard/me")!.body as DashboardMe;
  const first = base.upcoming[0]!;
  const upcoming = [0, 1, 4].map((days, i) => ({
    ...first,
    case: { ...first.case, id: `0192a3b4-0000-7000-8000-00000000060${i}` },
    date: istDayPlus(days),
    critical: days <= 1,
    this_week: true,
  }));
  return { ...base, upcoming };
}

function inboxCounts(): S["InboxCountsListOut"] {
  const block = (code: string): InboxCounts => ({
    office_code: code,
    recommended_high: STRESS.count,
    recommended_medium: 48,
    claimed_active: STRESS.count + 1,
    claimed_disposed: 310,
    transfers_in_open: 3,
    pool_with_hearing_7d: 27,
    whole_department: true,
  });
  const base = synth({ $ref: "#/components/schemas/InboxCountsListOut" }) as S["InboxCountsListOut"];
  return { ...base, departments: [block("EDU"), block("HEALTH")] } as S["InboxCountsListOut"];
}

const SYSTEM_GROUPS: [string, string[]][] = [
  ["masters", ["overview", "state", "district", "bench_master", "case_type", "act"]],
  ["causelists", ["causelist_bench", "causelist_details", "show_causelist"]],
  ["cases", ["cnr", "current_status", "order", "show_business"]],
  ["searches", ["case_search", "filing", "party_name", "advocate_name"]],
];

function systemHealth(): SystemHealth {
  const base = synth({ $ref: "#/components/schemas/SystemHealthOut" }) as SystemHealth;
  const card = base.groups[0]!.cards[0]!;
  return {
    ...base,
    napix_enabled: false,
    groups: SYSTEM_GROUPS.map(([key, keys]) => ({
      key,
      label: key,
      cards: keys.map((k, i) => ({ ...card, key: k, label_key: k, label: `Court API: ${k.replace(/_/g, " ")}`, group: key, status: (["ok", "warn", "down", "unknown"] as const)[i % 4]! })),
    })),
  };
}

/**
 * System health's Access token card and the request console of Case details by CNR (design followups-oct, decision
 * 13): typed from `openapi.json`, synthetic and non-secret values only (no token, a CNR in the synthesiser's made-up
 * pattern, never a real one).
 */
const SYNTH_CNR = `ASHC01${String(12345).padStart(6, "0")}2025`;
const NAPIX_URL = "https://delhigw.napix.gov.in/nic/ecourts";

function napixToken(): S["NapixTokenOut"] {
  return {
    status: "ok",
    napix_enabled: false,
    shared_store: true,
    held: true,
    ttl_seconds: 2520,
    renewing_soon: false,
    valid_until: "2026-10-21T15:20:00+05:30",
    expires_at: "2026-10-21T15:20:00+05:30",
    obtained_at: "2026-10-21T14:25:00+05:30",
    token_type: "Bearer",
    scope: "napix",
    accepted_since: { at: "2026-10-21T14:31:00+05:30", api_label: "Case Details by CNR", http_status: 200 },
    rejected_since: 0,
    last_request: { at: "2026-10-21T14:25:00+05:30", ok: true, outcome: "obtained", http_status: 200, duration_ms: 310, rate_limit: { limit: null, remaining: null } },
    last_failure: null,
    requests_today: 3,
    endpoint: {
      method: "POST",
      url: `${NAPIX_URL.replace("/nic/ecourts", "")}/token`,
      body: "grant_type=client_credentials&scope=napix",
      content_type: "application/x-www-form-urlencoded",
      auth_note: "Basic authentication with the client key and secret from .env, not shown",
    },
    curl_token: `curl -X POST '${NAPIX_URL.replace("/nic/ecourts", "")}/token' -u '<CLIENT_KEY>:<CLIENT_SECRET>' -d 'grant_type=client_credentials&scope=napix'`,
    check: { allowed: false, reason: "Court calls are switched off on this server", next_allowed_at: null },
  };
}

function napixConsole(api: string): S["ConsoleOut"] {
  const url = `${NAPIX_URL}/hc-cnr-api/CNR`;
  const plain = `cino=${SYNTH_CNR}`;
  const structure: S["StructureOut"] = {
    paths: [
      { path: "cino", type: "string", count: 1 },
      { path: "case_no", type: "string", count: 1 },
      { path: "pet_name", type: "string", count: 1 },
      { path: "date_next_list", type: "string", count: 1 },
    ],
    total: 4,
    more: 0,
    depth_limited: false,
  };
  return {
    api,
    label: "Case Details by CNR",
    method: "GET",
    method_note: null,
    url,
    plain,
    plain_sha256: "a".repeat(64),
    plain_complete: true,
    no_input_note: null,
    envelope: [
      { name: "dept_id", shown: "AS…", note: "Department ID from .env (NAPIX_DEPT_ID), masked", length: null },
      { name: "request_str", shown: "encrypted, 44 characters, not shown", note: "AES-128-CBC of the plain string", length: 44 },
      { name: "request_token", shown: "f".repeat(64), note: "HMAC-SHA256 of the plain string", length: null },
      { name: "version", shown: "v1.0", note: "from NAPIX_VERSION", length: null },
    ],
    headers: [
      { name: "Authorization", shown: "Bearer ‹access token, not shown›" },
      { name: "Accept", shown: "application/json, application/pdf" },
    ],
    request_token: "f".repeat(64),
    templates: { curl: `# plain string: ${plain}\ncurl -G '${url}' -H 'Authorization: Bearer <ACCESS_TOKEN>'`, note: "These do not run as they are." },
    fields: [
      {
        name: "cino",
        value: SYNTH_CNR,
        prefilled: true,
        source: "held",
        editable: true,
        mandatory: true,
        required: true,
        format: "16 letters and digits",
        meaning: "The case's CNR.",
        hint: null,
      },
    ],
    sample: { available: true, label: `${STRESS.caseNo} (CNR ${SYNTH_CNR})`, reason: null },
    send: { available: false, reason: "Court calls are switched off on this server", cost: 1, next_allowed_at: null },
    last_send: {
      at: "2026-10-21T14:33:00+05:30",
      by: "person",
      recorded: true,
      edited: false,
      ok: true,
      answered: true,
      status: "ok",
      reason: "The court answered",
      method: "GET",
      url,
      plain,
      params_sha256: "a".repeat(64),
      http_status: 200,
      http_meaning: "Everything is normal",
      napix_status: null,
      napix_meaning: null,
      error_family: null,
      duration_ms: 800,
      attempts: 1,
      remaining: 800,
      rate_limit: { limit: 1000, remaining: 800 },
      window_reset_at: "2026-10-21T14:34:00+05:30",
      token_verified: true,
      summary: null,
      structure,
      inventory_diff: null,
      response_id: "0192a3b4-0000-7000-8000-0000000000r1",
      response_available: true,
      same_plain_as_form: true,
    },
    latest_answer: {
      at: "2026-10-21T14:33:00+05:30",
      by: "background",
      structure,
      inventory_diff: null,
      response_id: "0192a3b4-0000-7000-8000-0000000000r1",
      response_available: true,
      response_too_large: false,
    },
    doc: { doc: "hc_spec", page: 12, section: "6.1 Search by CNR API", available: true },
    full_answer_allowed: true,
    not_saved_note: "Shown, not saved to cases. Use Search to add a case.",
    full_answer_note: null,
  };
}

const REPORT_KEYS = ["pending-cases", "hearings-disposals", "pending-actions", "data-health"] as const;

function catalogue(): ReportCatalogue {
  const base = synth({ $ref: "#/components/schemas/ReportCatalogueOut" }) as ReportCatalogue;
  const item = base.reports[0]!;
  return {
    reports: REPORT_KEYS.map((key) => ({ ...item, key, title: key.replace(/-/g, " "), departments: key === "data-health" ? [] : ["EDU", "HEALTH"] })),
    departments: [
      { code: "EDU", name: "Department of School Education, Government of Assam, Dispur", is_active: true },
      { code: "HEALTH", name: "Health and Family Welfare", is_active: true },
    ],
  } as ReportCatalogue;
}

function report(key: string): Report {
  const columns = [
    { key: "case", label: "Case", kind: "text" },
    { key: "ref_no", label: "Reference", kind: "text" },
    { key: "petitioner", label: "Petitioner", kind: "text" },
    { key: "department", label: "Holding department", kind: "text" },
    { key: "filed", label: "Filed", kind: "date" },
    { key: "next", label: "Next Hearing", kind: "date" },
    { key: "stage", label: "Stage", kind: "text" },
    { key: "held", label: "Files held", kind: "int" },
    { key: "pending", label: "Days pending", kind: "days" },
  ];
  const row = (i: number) => ({
    case: i === 0 ? STRESS.caseNo : `WA/${55 + i}/2026`,
    ref_no: i === 0 ? SAMPLE.caseRef : `ASLMS/GHC/CASE/2026/00000${2 + i}`,
    petitioner: i === 0 ? STRESS.party : "RAM KUMAR DAS",
    department: i === 0 ? STRESS.office : "Education",
    filed: "2025-01-10",
    next: "2026-10-23",
    stage: "Reply due",
    held: STRESS.count + i,
    pending: 400 + i,
  });
  return {
    key,
    title: key.replace(/-/g, " "),
    scope: "state",
    department_code: null,
    params: {},
    generated_at: "2026-10-21T05:30:00Z",
    generated_by: { name: "Anita Sharma Baruah", designation: STRESS.designation, office_code: "GOA" },
    as_of_note: "As it stands today.",
    sections: [
      { key: "main", title: "Pending cases by department", columns, rows: [row(0), row(1), row(2)], totals: { held: STRESS.count * 3 }, note: null, total_rows: 3, truncated: false },
    ],
  } as Report;
}

/**
 * The ten user types (decision 20's stress for the type x function matrix: one column per type, as in the database),
 * with the full names of design portal-ui-polish-2 (decision 7); the sample type carries an 80-character custom name
 * (Edit Name's limit), so badges, cards and the page title are measured at their longest.
 */
export const LONG_TYPE_NAME = "Department Officers for Litigation, Contempt Proceedings and Compliance Tracking";
const USER_TYPES: [string, string][] = [
  ["super_admin", "Super Administrator"],
  ["state_oversight", "State Oversight Officer"],
  ["dept_head", "Head of Department"],
  ["dept_admin", "Department Administrator"],
  ["dept_officer", LONG_TYPE_NAME],
  ["directorate_user", "Directorate Officer"],
  ["referral_reviewer", "Referral Reviewer"],
  ["standing_counsel", "Standing Counsel"],
  ["central_operator", "Central Operator"],
  ["auditor", "Auditor"],
];

function labels(): S["ReferenceLabelsOut"] {
  const base = synth({ $ref: "#/components/schemas/ReferenceLabelsOut" }) as S["ReferenceLabelsOut"];
  return {
    ...base,
    user_types: USER_TYPES.map(([code, label]) => ({ code, label, description: `${label}: functions by module`, assignable: code !== "super_admin" })),
    // design office-head-picker: the kinds New Office offers, so the Department head section can be drawn
    office_kinds: [
      { code: "state", label: "State" },
      { code: "department", label: "Department" },
      { code: "central", label: "Central Agency" },
      { code: "advocate_general", label: "Advocate General" },
      { code: "directorate", label: "Directorate" },
      { code: "unit", label: "Unit" },
    ],
  };
}

/**
 * The functions with their plain-language groups (design case-workspace-admin, decision 26), as `GET /admin/permissions`
 * answers: every function the API knows, grouped as the server's `PERMISSION_GROUPS` does, the retired requests
 * functions without a group; the first description is a long one (the stress row).
 */
const GROUPS: [string, string, RegExp][] = [
  ["people", "People and access", /^(users|access|offices)\.|^admin\.designations$/],
  ["cases", "Cases and ownership", /^cases\./],
  ["case_work", "Case Work", /^(custody|stages|notes|assistant)\./],
  ["documents", "Documents", /^documents\./],
  ["alerts", "Alerts", /^(alerts|next_dates)\./],
  ["reports", "Reports", /^(reports|dashboard|audit)\./],
  ["administration", "Administration", /^admin\./],
];

function permissions(): PermissionInfo[] {
  const counters = new Map<string, number>();
  return ALL_FUNCTIONS.map((code, i) => {
    const group = code.startsWith("requests.") ? null : (GROUPS.find(([, , re]) => re.test(code)) ?? null);
    const sort = group ? (counters.get(group[0]) ?? 0) + 1 : null;
    if (group) counters.set(group[0], sort!);
    const words = code.split(".")[1]!.replace(/_/g, " ");
    return {
      code,
      module: code.split(".")[0]!,
      label: words.charAt(0).toUpperCase() + words.slice(1),
      description: i === 0 ? "See the people of the offices you look after, with their posts, user types and sign-in state." : "Switch this on for the type.",
      is_active: group !== null,
      group: group ? group[0] : null,
      group_label: group ? group[1] : null,
      sort_in_group: sort,
    } as PermissionInfo;
  });
}

function accessMatrix(): Record<string, Record<string, boolean>> {
  const perms = permissions().filter((p) => p.is_active);
  return Object.fromEntries(
    USER_TYPES.map(([code], i) => [code, Object.fromEntries(perms.map((p, j) => [p.code, code === "super_admin" || (i + j) % 2 === 0]))]),
  );
}

/** The seed's defaults: the matrix with a few functions flipped, so "Changed from default" shows. */
function accessDefaults(): Record<string, Record<string, boolean>> {
  const m = accessMatrix();
  return Object.fromEntries(
    Object.entries(m).map(([role, row]) => [
      role,
      Object.fromEntries(Object.entries(row).map(([code, on], j) => [code, role !== "super_admin" && j % 7 === 0 ? !on : on])),
    ]),
  );
}

function accessOverview(): S["UserTypeCardOut"][] {
  const m = accessMatrix();
  const d = accessDefaults();
  return USER_TYPES.map(([code], i) => {
    const row = m[code]!;
    const codes = Object.keys(row);
    return {
      code,
      users: i === 4 ? STRESS.count : i + 1,
      functions_on: codes.filter((c) => row[c]).length,
      functions_total: codes.length,
      changed_from_default: codes.filter((c) => row[c] !== d[code]![c]).length,
    };
  });
}

/** The Users list with each status (design case-workspace-admin, decision 23): active, not signed in yet, off. */
function users(): UserOut[] {
  const base = (synthFor("/admin/users")!.body as UserOut[])[0]!;
  const membership = MEMBERSHIPS[0]!;
  const row = (i: number, extra: Partial<UserOut>): UserOut => ({
    ...base,
    id: i === 0 ? SAMPLE.userId : `0192a3b4-0000-7000-8000-00000000010${i}`,
    full_name: i === 0 ? "Anita Sharma Baruah" : `Rina Das ${i}`,
    email: `officer${i}@assam.gov.in`,
    memberships: i === 0 ? MEMBERSHIPS : [{ ...membership, id: `m-${i}`, role: "dept_officer", designation: "Section Officer" }],
    ...extra,
  });
  return [
    row(0, { is_active: true, last_login_at: "2026-10-21T05:30:00Z" }),
    row(1, { is_active: true, last_login_at: null }),
    row(2, { is_active: false, last_login_at: "2026-09-01T05:30:00Z" }),
    // design office-head-picker, decisions 15-17: a login with no office yet (the User Picker's No Office Yet option)
    row(3, { is_active: true, last_login_at: null, office: null, role: null, designation: null, memberships: [], full_name: "Rupam Jyoti Kalita" }),
  ];
}

/**
 * The Office Picker's offices (design portal-ui-polish-2, decisions 28-29): the tree to depth 3 with long names, and one
 * inactive office (shown with its badge where the purpose allows it).
 */
function officeChoices(url: URL): OfficeChoices {
  const purpose = (url.searchParams.get("purpose") ?? "users") as OfficeChoices["purpose"];
  const goa = "Government of Assam";
  const edu = "Department of School Education, Government of Assam, Dispur";
  const items: OfficeChoices["items"] = [
    { code: "GOA", name: goa, kind: "state", tier: "state", depth: 0, parent_code: null, ancestors: [], is_active: true },
    { code: "EDU", name: edu, kind: "department", tier: "department", depth: 1, parent_code: "GOA", ancestors: [goa], is_active: true },
    { code: "EDU-DSE", name: STRESS.office, kind: "directorate", tier: "directorate", depth: 2, parent_code: "EDU", ancestors: [goa, edu], is_active: true },
    {
      code: "EDU-DSE-LEGAL-CELL",
      name: "Legal Cell of the Directorate of Secondary Education, Kahilipara",
      kind: "unit",
      tier: "directorate",
      depth: 3,
      parent_code: "EDU-DSE",
      ancestors: [goa, edu, STRESS.office],
      is_active: true,
    },
    { code: "EDU-OLD", name: "Old Examination Cell (merged)", kind: "unit", tier: "directorate", depth: 2, parent_code: "EDU", ancestors: [goa, edu], is_active: false },
    { code: "HEALTH", name: "Health and Family Welfare", kind: "department", tier: "department", depth: 1, parent_code: "GOA", ancestors: [goa], is_active: true },
  ];
  return { purpose, items: items.filter((o) => o.is_active || purpose === "audit") };
}

/** The sample office's page (design office-head-picker-followups, decision 7): an inactive Department-tier office. */
function officeDetail(): OfficeDetail {
  const base = synth({ $ref: "#/components/schemas/OfficeDetailOut" }) as OfficeDetail;
  return { ...base, code: SAMPLE.officeCode, kind: "department", tier: "department", parent_code: "GOA", is_active: false };
}

/** A person with two active offices and one ended (decision 34), as `GET /admin/users/{id}/memberships` answers. */
function userMemberships(): MembershipOut[] {
  return [
    { ...MEMBERSHIPS[0]!, role: "dept_officer", valid_from: "2026-01-05" },
    { ...MEMBERSHIPS[1]!, valid_from: "2026-03-01" },
    {
      id: "0192a3b4-0000-7000-8000-0000000000m3",
      office: { code: "HEALTH", name: "Health and Family Welfare", kind: "department" },
      department_code: "HEALTH",
      designation: "Section Officer",
      role: "dept_officer",
      is_primary: false,
      is_active: false,
      valid_from: "2025-01-01",
      valid_to: "2025-12-31",
    },
  ];
}

/** One membership's functions with one function given and one taken (decision 35). */
function membershipFunctions(url: URL): S["MembershipFunctionsOut"] {
  const active = permissions().filter((p) => p.is_active).map((p) => p.code);
  const typeFns = active.filter((_, i) => i % 2 === 0);
  const given = active.find((c) => !typeFns.includes(c))!;
  const taken = typeFns[1]!;
  const at = (permission: Permission, effect: "grant" | "deny") => ({
    permission,
    effect,
    granted_by_user_id: null,
    is_active: true,
    reason: effect === "grant" ? "Covers the legal cell while the post is vacant" : null,
    valid_to: null,
  });
  return {
    membership_id: url.pathname.split("/").at(-2)!,
    role: "dept_officer",
    type_functions: typeFns,
    overrides: [at(given, "grant"), at(taken, "deny")],
    effective: [...typeFns.filter((c) => c !== taken), given],
  };
}

/**
 * One cause-list day (design portal-ui-polish-2, decisions 23-25): a held day with a bench of two lists (daily with its
 * PDF, supplementary without), a bench with the longest label and a court-wide file, so the date navigator, the More
 * Filters panel (two list types, three courts) and the View Cause List modal on `SAMPLE.benchId` are drawn. The
 * entries come from the synthetic answer.
 */
function causelistDay(url: URL): S["CauselistDayOut"] {
  const date = url.pathname.split("/").pop()!;
  const list = (id: string, list_type: string, has_pdf: boolean, entries: number): S["CauselistOut"] => ({
    id,
    list_type,
    list_type_text: list_type.toUpperCase(),
    label: null,
    napix_causelist_id: 11,
    source: "napix",
    entry_count: entries,
    entries_stored: entries,
    fetch_status: has_pdf ? "fetched" : "not_available",
    parse_status: "parsed",
    has_pdf,
    version: 1,
    superseded: false,
  });
  const benches: S["CauselistBenchOut"][] = [
    {
      bench_id: Number(SAMPLE.benchId),
      label: "HONOURABLE THE CHIEF JUSTICE, HONOURABLE MR. JUSTICE SOUMITRA SAIKIA",
      court_nos: ["1"],
      source: "napix",
      entries: 58,
      lists: [list(SAMPLE.causelistId, "daily", true, 51), list("0192a3b4-0000-7000-8000-0000000000c2", "supplementary", false, 7)],
    },
    {
      bench_id: 777,
      label: "HONOURABLE MRS. JUSTICE MALASRI NANDI",
      court_nos: ["3"],
      source: "napix",
      entries: STRESS.count,
      lists: [list("0192a3b4-0000-7000-8000-0000000000c3", "daily", true, 40)],
    },
    { bench_id: null, label: null, court_nos: ["5"], source: "ghc_website", entries: 2, lists: [list("0192a3b4-0000-7000-8000-0000000000c4", "daily", false, 2)] },
  ];
  return {
    date,
    state: "held",
    queue_status: "done",
    queue_finished_at: null,
    previous_date: "2026-10-22",
    next_date: "2026-10-26",
    totals: { benches: benches.length, lists: 4, entries: 58 + STRESS.count + 2 },
    benches,
  };
}

/** The person's latest audit entries (decision 36). */
function auditPage(): AuditPage {
  const base = synthFor("/audit")!.body as AuditPage;
  const row = base.items[0]!;
  const actions = ["ownership.claim", "custody.sent", "notes.added"];
  const items = actions.map((action, i) => ({ ...row, id: `0192a3b4-0000-7000-8000-00000000060${i}`, action }));
  return { ...base, items, next_cursor: null };
}

/** Three codes seen in cause lists with no mapping (decision 42). */
function unmapped(): UnmappedCode[] {
  return [
    {
      code: "SC, SEBA, SECONDARY EDUCATION AND MADRASSA BOARD, ASSAM",
      entries: STRESS.count,
      last_listed: "2026-10-23",
      example_case_ref: SAMPLE.caseRef,
      // design partial-code-match (`partial_relation` in services/matching.py): the department's code `SC, SEBA` has
      // parts {SC, SEBA}, all inside the printed code's parts, so the printed code partly matches it as "contained"
      partial_matches: [{ code: "SC, SEBA", office_code: "EDU", relation: "contained" }],
    },
    { code: "SC, PWD", entries: 48, last_listed: "2026-10-20", example_case_ref: null, partial_matches: [] },
    { code: "GA, ASSAM", entries: 3, last_listed: "2026-09-30", example_case_ref: SAMPLE.caseRef, partial_matches: [] },
  ];
}

/**
 * Every unmapped code (design list-search, decisions 9-12 and 39): the three codes above, then 1,063 synthetic ones,
 * 1,066 in all, paged by 100 with the cursor as the index of the next page; `q` keeps the codes whose compact form
 * holds the compact query; `sort=code` orders them A to Z (Z to A with `dir=desc`).
 */
const UNMAPPED_ALL: UnmappedCode[] = [
  ...unmapped(),
  ...Array.from({ length: 1063 }, (_, i) => ({
    code: `SC, DEPT ${String(i + 1).padStart(4, "0")}`,
    entries: Math.max(1, 40 - Math.floor(i / 30)),
    last_listed: i % 9 === 0 ? null : "2026-10-15",
    example_case_ref: null,
    partial_matches: [],
  })),
];

function compactCode(text: string): string {
  return text.toUpperCase().replace(/[^0-9A-Z]/g, "");
}

function unmappedPage(url: URL): S["UnmappedCodePageOut"] {
  const q = compactCode(url.searchParams.get("q") ?? "");
  const kept = q ? UNMAPPED_ALL.filter((c) => compactCode(c.code).includes(q)) : UNMAPPED_ALL;
  const sort = url.searchParams.get("sort");
  const desc = url.searchParams.get("dir") === "desc";
  const ordered = sort === "code" ? [...kept].sort((a, b) => (a.code < b.code ? -1 : 1) * (desc ? -1 : 1)) : kept;
  const start = Number(url.searchParams.get("cursor") ?? 0) || 0;
  const limit = Number(url.searchParams.get("limit") ?? 100) || 100;
  return {
    items: ordered.slice(start, start + limit),
    total: UNMAPPED_ALL.length,
    matched: kept.length,
    next_cursor: start + limit < ordered.length ? String(start + limit) : null,
  };
}

/** The counsel codes with one rule carrying its own weight (decision 40). */
function counselCodes(): CounselCodeList {
  const base = synthFor("/admin/counsel-codes")!.body as CounselCodeList;
  const row = base.items[0]!;
  const items = [
    { ...row, weight_override: 0.7, effective_weight: 0.7 },
    { ...row, id: "0192a3b4-0000-7000-8000-000000000701", code: "SC, HEALTH", weight_override: null },
  ];
  return { ...base, items, total: items.length };
}

/** Cases with me and Pending action (design case-workspace-admin, decision 19): one row per lead badge. */
function held(): HeldList {
  const base = synthFor("/custody/held")!.body as HeldList;
  const first = base.items[0]!;
  const card = first.card!;
  const recent = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
  const variants: Partial<NonNullable<typeof card>>[] = [
    { overdue: true, overdue_days: 12, due_soon: false },
    { overdue: false, overdue_days: 0, due_soon: true },
    { overdue: false, overdue_days: 0, due_soon: false, since: recent },
    { overdue: false, overdue_days: 0, due_soon: false, due_date: null },
  ];
  const items = variants.map((v, i) => {
    const item = base.items[i % base.items.length]!;
    return { ...item, case: { ...item.case, id: `0192a3b4-0000-7000-8000-00000000020${i}` }, card: { ...card, ...v } };
  });
  return { ...base, items, total: items.length };
}

/**
 * Working on (design case-inbox-merge, decision 8): one row per lead badge on a case with me (Overdue, Due soon, New),
 * then a case allotted to me but with someone else (no badge, "—" for action, due and From). The Next Hearing column
 * draws every band (design next-hearing-highlight): today, tomorrow, in 3 days and in 20 days on those four rows, then
 * three cases allotted to me with no custody: a date 5 days past, no date, and a disposed case; then (design
 * next-date-direct, decisions 5 and 8) a date counted from an order ("Around") and a court date whose order differs
 * ("Order Differs").
 */
function courtNext(date: string | null): S["NextHearingOut"] | null {
  if (!date) return null;
  return { date, basis: "court", approximate: false, basis_words: null, order: null, rule: null, differs: null };
}

const ORDER_REF = { id: "0192a3b4-0000-7000-8000-000000000901", order_no: "4", order_date: "2026-10-12", document_id: null };

function working(): MyCaseList {
  const base = synthFor("/inbox/mine")!.body as MyCaseList;
  const first = base.items[0]!;
  const recent = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
  const brief: CustodyBrief = {
    holder_office: { code: "EDU-DSE", name: STRESS.office },
    holder_user: { full_name: "Anita Sharma Baruah", designation: STRESS.designation },
    with_me: true,
    pending_action: "parawise_comments",
    pending_action_label: "Parawise comments",
    since: "2026-10-01T05:30:00Z",
    due_date: "2026-10-12",
    overdue: false,
    overdue_days: 0,
    due_soon: false,
    sent_by: { name: "Rina Das", designation: "Joint Secretary", office_code: "EDU" },
  };
  const variants: Partial<CustodyBrief>[] = [
    { overdue: true, overdue_days: 12 },
    { due_date: "2099-01-01", due_soon: true },
    { due_date: null, since: recent },
    { with_me: false, holder_user: { full_name: "Rina Das 1", designation: "Section Officer" }, overdue: true, overdue_days: 3 },
  ];
  const dates = [0, 1, 3, 20];
  const items: MyCaseList["items"] = variants.map((v, i) => ({
    ...first,
    case: { ...first.case, id: `0192a3b4-0000-7000-8000-00000000050${i}`, status: "pending", next_hearing: courtNext(istDayPlus(dates[i]!)) },
    reasons: v.with_me === false ? ["allotted"] : ["allotted", "file"],
    custody: { ...brief, ...v },
  }));
  const bare: [string | null, string][] = [
    [istDayPlus(-5), "pending"],
    [null, "pending"],
    [istDayPlus(1), "disposed"],
  ];
  bare.forEach(([date, status], i) => {
    items.push({
      ...first,
      case: { ...first.case, id: `0192a3b4-0000-7000-8000-00000000050${4 + i}`, status, next_hearing: courtNext(date) },
      reasons: ["allotted"],
      custody: null,
    });
  });
  const extra: S["NextHearingOut"][] = [
    {
      date: istDayPlus(9),
      basis: "around",
      approximate: true,
      basis_words: "after 3 weeks",
      order: ORDER_REF,
      rule: "list_after_period",
      differs: null,
    },
    { ...courtNext(istDayPlus(12))!, differs: { date: istDayPlus(10), order: ORDER_REF } },
  ];
  extra.forEach((next, i) => {
    items.push({
      ...first,
      case: { ...first.case, id: `0192a3b4-0000-7000-8000-00000000060${i}`, status: "pending", next_hearing: next },
      reasons: ["allotted"],
      custody: null,
    });
  });
  return { ...base, items, total: items.length };
}

/** Sent by me (decision 20): the current leg, a past leg (muted) and a case the sender can no longer open. */
function sent(): SentList {
  const base = synthFor("/custody/sent")!.body as SentList;
  const item = base.items[0]!;
  const rows: Partial<typeof item>[] = [
    { visible: true, current: true },
    { visible: true, current: false, leg: { ...item.leg, reason: "recalled", reason_label: "Recalled" } },
    { visible: false, current: null },
  ];
  const items = rows.map((r, i) => ({ ...item, ...r, case: { ...item.case, id: `0192a3b4-0000-7000-8000-00000000030${i}` } }));
  return { ...base, items, total: items.length };
}

/** The journey and the remarks history (decisions 14 and 15): five movements, newest first, with remarks shown. */
function custodyHistory(url: URL): CustodyHistory {
  const base = synthFor(url.pathname.replace(/^\/api\/backend/, ""))!.body as CustodyHistory;
  const leg = base.legs[0]!;
  const reasons: [string, string][] = [
    ["sent", "Sent"],
    ["recalled", "Recalled"],
    ["sent", "Sent"],
    ["allotted", "Assigned"],
    ["claimed", "Claimed"],
  ];
  const legs: CustodyLeg[] = reasons.map(([reason, label], i) => ({
    ...leg,
    seq_no: 5 - i,
    reason,
    reason_label: label,
    remark: i === 0 ? `${STRESS.sentence}\n${STRESS.sentence}\n${STRESS.sentence}` : i === 3 ? null : "Seen; put up with the counsel's opinion.",
    started_at: new Date(Date.UTC(2026, 9, 21 - i * 3, 5, 30)).toISOString().replace(".000Z", "Z"),
  }));
  const limit = Number(url.searchParams.get("limit") ?? 50);
  return { ...base, legs: url.searchParams.get("order") === "desc" ? legs.slice(0, limit) : [...legs].reverse().slice(0, limit), total: legs.length, remarks_shown: true };
}

/** The notes trail with a correction and the note it corrects (decision 15). */
function notes(): NoteList {
  const base = synthFor("/cases/x/notes")!.body as NoteList;
  const n = base.items[0]!;
  const ref = (seq: number) => `ASLMS/EDU/NOTE/2026/00000${seq}`;
  const note = (seq: number, extra: Partial<Note>): Note => ({ ...n, id: `0192a3b4-0000-7000-8000-00000000040${seq}`, seq_no: seq, ref_no: ref(seq), draft: false, ...extra });
  const items = [
    note(1, { body: STRESS.sentence, superseded_by: { ref_no: ref(3), seq_no: 3 }, supersedes: null }),
    note(2, { body: "Seen; put up with the counsel's opinion.", supersedes: null, superseded_by: null }),
    note(3, { body: `${STRESS.sentence} (corrected)`, supersedes: { ref_no: ref(1), seq_no: 1 }, superseded_by: null }),
  ];
  return { ...base, items, total: items.length };
}

/** Lists seen empty, so the empty states are checked too (decision 20). */
function emptyList<T extends { items: unknown[]; total?: number }>(schema: string): T {
  const base = synth({ $ref: `#/components/schemas/${schema}` }) as T;
  return { ...base, items: [], total: 0 } as T;
}

/**
 * A conversation's thread (design assistant-ollama, decision 8): each citation's `label` is its source number, `S1`,
 * `S2`, …, which the source list shows in its number badge; the synthetic sentence there made the badge 176 px wide.
 * Design assistant-polish, decisions 15 and 16: a local-model answer whose text holds its `[S#]` markers (each a button
 * opening its source), then a quick fact from the case record (engine `case_record`, one Case Details source `S1`).
 */
function assistantThread(): AssistantThread {
  const base = synthFor("/assistant/conversations/x")!.body as AssistantThread;
  const labelled = base.messages.map((m) => ({ ...m, citations: m.citations.map((c, i) => ({ ...c, label: `S${i + 1}` })) }));
  const asked = labelled.find((m) => m.role === "user") ?? labelled[0]!;
  const said = labelled.find((m) => m.role === "assistant") ?? labelled[0]!;
  const cites = said.citations.length ? said.citations : (labelled.find((m) => m.citations.length)?.citations ?? []);
  const local = {
    ...said,
    id: `${said.id.slice(0, -2)}a1`,
    role: "assistant" as const,
    mode: "ollama" as const,
    outcome: "answered" as const,
    error: null,
    hidden_reason: null,
    engine: { kind: "ollama" as const, model: "qwen3.5:4b" },
    checks: { invalid_markers: 0, cut_short: false },
    content: `${STRESS.sentence} [S1]. The respondents were given four weeks to file the affidavit [S2].`,
    citations: cites.map((c, i) => ({ ...c, label: `S${i + 1}`, cited: i < 2, available: true })),
  };
  const details = cites[0]
    ? {
        ...cites[0],
        source_kind: "case_details" as const,
        label: "S1",
        cited: true,
        available: true,
        passage: null,
        page: null,
        context: "Case number: WP(C)/12345/2025; Status: pending\nNext date (court): 23 Oct 2026",
      }
    : null;
  const fact = {
    ...local,
    id: `${said.id.slice(0, -2)}a2`,
    engine: { kind: "case_record" as const, model: null },
    checks: null,
    content: `${STRESS.party} [S1].`,
    citations: details ? [details] : [],
  };
  return {
    ...base,
    messages: [
      { ...asked, id: `${asked.id.slice(0, -2)}q1`, role: "user" as const, citations: [] },
      { ...local, reply_to_id: `${asked.id.slice(0, -2)}q1` },
      { ...asked, id: `${asked.id.slice(0, -2)}q2`, role: "user" as const, citations: [], content: "Who are the parties?" },
      { ...fact, reply_to_id: `${asked.id.slice(0, -2)}q2` },
    ],
  };
}

type Override = (url: URL) => unknown;

/** Overrides by API path (exact) or pattern. */
const OVERRIDES: [RegExp, Override][] = [
  [/^\/me$/, () => me()],
  // design assistant-ollama, decision 14: the Assistant screens in the local model's state, the model ready
  [
    /^\/assistant\/status$/,
    () => ({
      ...(synthFor("/assistant/status")!.body as Record<string, unknown>),
      mode: "ollama",
      state: "ready",
      banner: null,
      internal_records: "switch",
      engine: { kind: "ollama", model: "qwen3.5:4b", readiness: "ready", reason: null },
    }),
  ],
  [/^\/assistant\/conversations\/[^/]+$/, () => assistantThread()],
  // design data-collection-redesign, decision 41: no department name is registered yet (the dev database today)
  [
    /^\/admin\/discovery$/,
    () => ({ ...(synthFor("/admin/discovery")!.body as Record<string, unknown>), terms: { active: 0, inactive: 0 } }),
  ],
  [/^\/dashboard$/, () => DASHBOARD],
  [/^\/dashboard\/me$/, () => dashboardMe()],
  [/^\/inbox\/counts$/, () => inboxCounts()],
  [/^\/admin\/system-health$/, () => systemHealth()],
  [/^\/admin\/system-health\/token$/, () => napixToken()],
  [/^\/admin\/system-health\/napix\/[^/]+\/console$/, (url) => napixConsole(url.pathname.split("/").at(-2)!)],
  [/^\/reference\/labels$/, () => labels()],
  [/^\/admin\/access\/types$/, () => accessMatrix()],
  [/^\/admin\/access\/types\/[^/]+$/, (url) => accessMatrix()[url.pathname.split("/").pop()!] ?? {}],
  [/^\/admin\/access\/defaults$/, () => accessDefaults()],
  [/^\/admin\/access\/overview$/, () => accessOverview()],
  [/^\/admin\/permissions$/, () => permissions()],
  [/^\/admin\/users$/, () => users()],
  // design portal-ui-polish-2, decisions 28-42: the Office Picker, the User Details modal and Department Mapping
  [/^\/admin\/offices\/choices$/, (url) => officeChoices(url)],
  // design office-head-picker-followups, decision 7: the sample office is an inactive department, so `?reactivate=1`
  // opens the Reactivate dialog for the Super Administrator
  [/^\/admin\/offices\/(?!tree$|choices$)[^/]+$/, () => officeDetail()],
  [/^\/admin\/users\/[^/]+$/, () => users()[0]],
  [/^\/admin\/users\/[^/]+\/memberships$/, () => userMemberships()],
  [/^\/admin\/users\/[^/]+\/memberships\/[^/]+\/permissions$/, (url) => membershipFunctions(url)],
  [/^\/audit$/, () => auditPage()],
  // design portal-ui-polish-2, decisions 23-25: the cause-list day and the list PDF the View Cause List modal shows
  [/^\/causelists\/\d{4}-\d{2}-\d{2}$/, (url) => causelistDay(url)],
  [/^\/causelists\/lists\/[^/]+\/file$/, () => ({ note: "the browser check stands in for the court's PDF" })],
  [/^\/admin\/counsel-codes\/unmapped$/, () => unmapped()],
  [/^\/admin\/counsel-codes\/unmapped\/page$/, (url) => unmappedPage(url)],
  [/^\/admin\/counsel-codes$/, () => counselCodes()],
  [/^\/custody\/held$/, () => held()],
  [/^\/cases\/[^/]+\/custody$/, (url) => custodyHistory(url)],
  [/^\/cases\/[^/]+\/notes$/, () => notes()],
  [/^\/reports$/, () => catalogue()],
  [/^\/reports\/[^/]+$/, (url) => report(url.pathname.split("/").pop()!)],
  [/^\/alerts$/, () => emptyList<AlertList>("AlertListOut")],
  [/^\/custody\/sent$/, () => sent()],
  // design case-inbox-merge: the matcher reads `view` (the API's parameter); Disposed is seen empty
  [
    /^\/inbox\/mine$/,
    (url) => {
      const view = url.searchParams.get("view");
      if (view === "working") return working();
      return view === "disposed" ? emptyList<S["MyCaseListOut"]>("MyCaseListOut") : synthFor("/inbox/mine")!.body;
    },
  ],
];

/** Fields that must be absent for the ordinary screen to show (a merged case shows a link instead of its tabs). */
function tidy(path: string, body: unknown): unknown {
  if (/^\/cases\/[^/]+$/.test(path) && body && typeof body === "object") {
    const c = body as S["CaseDetailOut"];
    // design next-hearing-highlight and next-date-direct: the court's date tomorrow (header and rail), with an exact order
    // date that differs ("Order Differs"), and a period read from the latest order in 3 days shown directly ("Around")
    // on the Overview card
    const suggestion = synth({ $ref: "#/components/schemas/NextDateOut" }) as S["NextDateOut"];
    return {
      ...c,
      merged_into_ref_no: null,
      ref_no: SAMPLE.caseRef,
      identity: { ...c.identity, case_no_text: STRESS.caseNo },
      portal: { ...c.portal, merged_into_case_id: null, is_provisional: false },
      status: { ...c.status, status: "pending", next_hearing_date: istDayPlus(1) },
      next_hearing: {
        ...courtNext(istDayPlus(1))!,
        differs: { date: istDayPlus(4), order: ORDER_REF },
        phrase: "List this matter on the date fixed.",
        court_date: istDayPlus(1),
        reported_at: null,
      },
      next_date_from_orders: { ...suggestion, next_date: istDayPlus(3), review_status: "not_needed", needs_review: false, source: "order_period" },
    };
  }
  return body;
}

/** The answer to one request of the page to `/api/backend/…` (the API path after that prefix). */
/**
 * The Start dialog's check (design data-collection-redesign, decision 36): `POST /admin/data-load/preview` writes nothing
 * and calls no court (design data-load-console, decision 9), so it is the one POST the checker answers. Dates in January
 * 2025 are all held ("Nothing new to fetch"); any other dates have new days.
 */
function loadPreview(body: string | null): unknown {
  let from = "";
  try {
    from = String((JSON.parse(body ?? "{}") as { from?: string }).from ?? "");
  } catch {
    from = "";
  }
  const held = from.startsWith("2025-01");
  return {
    days: 5,
    held_with_lists: held ? 4 : 1,
    held_no_list: held ? 1 : 0,
    waiting: held ? 0 : 1,
    failed: 0,
    not_queued: held ? 0 : 3,
    calls_estimate: held ? 0 : STRESS.count,
    masters_stale: !held,
  };
}

type ActivityOut = components["schemas"]["ActivityOut"];

/** The ping's answer with the API's default limits: 30 min idle, a 2 min warning, 12 h left of a 12 h session. */
export const ACTIVITY_DEFAULT: ActivityOut = {
  idle_seconds: 1800,
  warning_seconds: 120,
  idle_ends_in: 1800,
  session_ends_in: 43_200,
  max_hours: 12,
};

export function answer(
  method: string,
  url: URL,
  apiPath: string,
  body: string | null = null,
  activity?: Partial<ActivityOut>,
): Answer {
  if (method === "POST" && apiPath === "/me/activity") return { status: 200, body: { ...ACTIVITY_DEFAULT, ...activity } };
  if (method === "POST" && apiPath === "/admin/data-load/preview") return { status: 200, body: loadPreview(body) };
  if (method !== "GET") return { status: 405, body: { detail: "the browser check never acts" }, problem: `${method} ${apiPath}` };
  // design office-head-picker: New User's e-mail check for a new person answers 404, as the API does
  if (apiPath === "/admin/users/lookup" && (url.searchParams.get("email") ?? "").startsWith("new.")) {
    return { status: 404, body: { detail: "no such user" } };
  }
  // design office-head-picker-followups, decision 5: the User Picker's search for "fail" answers 500 (the error state)
  if (apiPath === "/admin/users" && url.searchParams.get("q") === "fail") {
    return { status: 500, body: { detail: { code: "internal", message: "the browser check's failed search" } } };
  }
  for (const [pattern, make] of OVERRIDES) if (pattern.test(apiPath)) return { status: 200, body: make(url) };
  const synthetic = synthFor(apiPath);
  if (!synthetic) return { status: 404, body: { detail: "no fixture" }, problem: `GET ${apiPath}${url.search}` };
  return { status: 200, body: tidy(apiPath, synthetic.body) };
}
