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
  DashboardIndex,
  InboxCounts,
  Me,
  MembershipOut,
  Permission,
  Report,
  ReportCatalogue,
  SentList,
  SystemHealth,
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
    { key: "next", label: "Next hearing", kind: "date" },
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

/** The ten user types (decision 20's stress for the type x function matrix: one column per type, as in the database). */
const USER_TYPES: [string, string][] = [
  ["super_admin", "Super admin"],
  ["state_oversight", "State oversight"],
  ["dept_head", "Department head"],
  ["dept_admin", "Department admin"],
  ["dept_officer", "Department officer"],
  ["directorate_user", "Directorate user"],
  ["referral_reviewer", "Referral reviewer"],
  ["standing_counsel", "Standing counsel"],
  ["central_operator", "Central operator"],
  ["auditor", "Auditor"],
];

function labels(): S["ReferenceLabelsOut"] {
  const base = synth({ $ref: "#/components/schemas/ReferenceLabelsOut" }) as S["ReferenceLabelsOut"];
  return {
    ...base,
    user_types: USER_TYPES.map(([code, label]) => ({ code, label, description: `${label}: functions by module`, assignable: code !== "super_admin" })),
  };
}

function accessMatrix(): Record<string, Record<string, boolean>> {
  const perms = (synthFor("/admin/permissions")?.body ?? []) as { code: string }[];
  return Object.fromEntries(USER_TYPES.map(([code], i) => [code, Object.fromEntries(perms.map((p, j) => [p.code, (i + j) % 2 === 0]))]));
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
  [/^\/reference\/labels$/, () => labels()],
  [/^\/admin\/access\/types$/, () => accessMatrix()],
  [/^\/reports$/, () => catalogue()],
  [/^\/reports\/[^/]+$/, (url) => report(url.pathname.split("/").pop()!)],
  [/^\/alerts$/, () => emptyList<AlertList>("AlertListOut")],
  [/^\/custody\/sent$/, () => emptyList<SentList>("SentListOut")],
  [
    /^\/inbox\/mine$/,
    (url) => (url.searchParams.get("tab") === "working" ? emptyList<S["MyCaseListOut"]>("MyCaseListOut") : synthFor("/inbox/mine")!.body),
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
