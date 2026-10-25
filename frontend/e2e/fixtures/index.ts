/**
 * The answers to the portal's API calls during the browser check (design portal-ui-polish, decisions 18 and 20). Every
 * `/api/backend/**` request is answered in the browser: a `GET` from a typed override below, else from the synthetic
 * answer built from the API's OpenAPI document (`synth.ts`); a `GET` the API does not have is answered 404 and is a
 * finding, and any other method is answered 405 and is a finding too (the check never acts). The overrides are typed
 * against the generated `schema.d.ts`, so a fixture that no longer matches the API breaks the image build.
 */
import type { components } from "@/lib/api/schema";
import type {
  AlertList,
  CustodyBrief,
  CustodyHistory,
  CustodyLeg,
  DashboardIndex,
  HeldList,
  InboxCounts,
  Me,
  MembershipOut,
  MyCaseList,
  Note,
  NoteList,
  Permission,
  PermissionInfo,
  Report,
  ReportCatalogue,
  SentList,
  SystemHealth,
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
    // the Case Assistant shows only while it is on (design assistant, decision 14)
    assistant_mode: "preview",
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
    ref_no: i === 0 ? SAMPLE.caseRef : `ASLMS/GOA/CASE/2026/00000${2 + i}`,
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
  ];
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
 * then a case allotted to me but with someone else (no badge, "—" for action, due and From).
 */
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
  const items = variants.map((v, i) => ({
    ...first,
    case: { ...first.case, id: `0192a3b4-0000-7000-8000-00000000050${i}` },
    reasons: v.with_me === false ? ["allotted"] : ["allotted", "file"],
    custody: { ...brief, ...v },
  }));
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
    ["allotted", "Allotted"],
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

type Override = (url: URL) => unknown;

/** Overrides by API path (exact) or pattern. */
const OVERRIDES: [RegExp, Override][] = [
  [/^\/me$/, () => me()],
  [/^\/dashboard$/, () => DASHBOARD],
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
    return {
      ...c,
      merged_into_ref_no: null,
      ref_no: SAMPLE.caseRef,
      identity: { ...c.identity, case_no_text: STRESS.caseNo },
      portal: { ...c.portal, merged_into_case_id: null, is_provisional: false },
    };
  }
  return body;
}

/** The answer to one request of the page to `/api/backend/…` (the API path after that prefix). */
export function answer(method: string, url: URL, apiPath: string): Answer {
  if (method !== "GET") return { status: 405, body: { detail: "the browser check never acts" }, problem: `${method} ${apiPath}` };
  for (const [pattern, make] of OVERRIDES) if (pattern.test(apiPath)) return { status: 200, body: make(url) };
  const synthetic = synthFor(apiPath);
  if (!synthetic) return { status: 404, body: { detail: "no fixture" }, problem: `GET ${apiPath}${url.search}` };
  return { status: 200, body: tidy(apiPath, synthetic.body) };
}
