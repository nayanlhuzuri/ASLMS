/**
 * The Insights answers of the browser check (design state-insights, round 2 "Tests": the uicheck states). Counts in the
 * dev data's proportions, the long office name of the stress set on the department and holder charts, and the chips
 * built from the address as the API builds them, so `/insights?kind=contempt&next=within_7` shows its two chips. The
 * counsel code `NOTHING` answers an empty selection (the empty state). Typed against the generated schema.
 */
import type { components } from "@/lib/api/schema";

import { STRESS } from "./synth";

type S = components["schemas"];

const AGE: [string, string][] = [
  ["age_lt_1", "Up to 1 Year"],
  ["age_1_3", "1 to 3 Years"],
  ["age_3_5", "3 to 5 Years"],
  ["age_5_10", "5 to 10 Years"],
  ["age_10_20", "10 to 20 Years"],
  ["age_20_30", "20 to 30 Years"],
  ["age_gt_30", "Over 30 Years"],
  ["age_unknown", "Age Not Known"],
];

const KINDS: [string, string, number[]][] = [
  ["wp", "Writ Petition", [5200, 4100, 1800, 900, 120, 10, 0, 40]],
  ["contempt", "Contempt", [420, 610, 330, 190, 30, 2, 0, 0]],
  ["wa", "Writ Appeal", [300, 260, 140, 70, 9, 0, 0, 2]],
  ["bail", "Bail", [820, 40, 3, 0, 0, 0, 0, 0]],
  ["crl_pet", "Criminal Petition (Section 482)", [640, 300, 90, 30, 2, 0, 0, 0]],
  ["civil_appeal", "Civil Appeal", [210, 250, 300, 260, 90, 12, 1, 5]],
  ["review", "Review", [90, 30, 6, 1, 0, 0, 0, 0]],
  ["pil", "Public Interest Litigation", [40, 35, 22, 12, 1, 0, 0, 0]],
  ["revision", "Revision", [160, 140, 70, 50, 20, 1, 0, 0]],
  ["arbitration", "Arbitration", [30, 22, 10, 4, 0, 0, 0, 0]],
  ["tax", "Tax and Customs", [25, 18, 9, 3, 0, 0, 0, 0]],
  ["other", "Other", [70, 40, 20, 10, 2, 0, 0, 1]],
];

function emptyFor(url: URL): boolean {
  return url.searchParams.get("counsel") === "NOTHING";
}

function chips(url: URL): S["InsightsChipOut"][] {
  const out: S["InsightsChipOut"][] = [];
  const p = url.searchParams;
  if (p.get("kind")) out.push({ param: "kind", value: p.get("kind")!, label: `Kind: ${KINDS.find((k) => k[0] === p.get("kind"))?.[1] ?? p.get("kind")}` });
  if (p.get("next") === "within_7") out.push({ param: "next", value: "within_7", label: "Next Hearing: In the Next 7 Days" });
  if (p.get("counsel")) out.push({ param: "counsel", value: p.get("counsel")!, label: `Counsel Code: ${p.get("counsel")}` });
  if (p.get("dept")) out.push({ param: "dept", value: p.get("dept")!, label: `${STRESS.office} · Recommended, Not Claimed` });
  return out;
}

export function insightsScopes(): S["InsightsScopesOut"] {
  return {
    state: true,
    departments: [
      { code: "EDU", name: "Department of School Education, Government of Assam, Dispur" },
      { code: "HEALTH", name: "Health and Family Welfare" },
    ],
    default: { scope: "state", department: null },
  };
}

export function insightsOverview(url: URL): S["InsightsOut"] {
  const empty = emptyFor(url);
  const n = (v: number) => (empty ? 0 : v);
  const department = url.searchParams.get("scope") === "department";
  const status = url.searchParams.get("status") ?? "pending";
  return {
    scope: department
      ? { kind: "department", department: { code: "EDU", name: "Department of School Education, Government of Assam, Dispur" } }
      : { kind: "state", department: null },
    generated_at: "2026-11-19T05:00:00Z",
    coverage: {
      court: "Gauhati High Court",
      listed_since: "2025-01-03",
      facts_waiting: n(12),
      facts_built_at: "2026-11-19T04:50:00Z",
      line: `Cases listed since 3 Jan 2025 · State cases (worked out) · ${status === "all" ? "All" : status === "disposed" ? "Disposed" : "Pending"} · Interlocutory applications inside their main case`,
    },
    chips: chips(url),
    headline: {
      cases: n(18830),
      state_cases: n(18830),
      contempt: n(1582),
      over_5_years: n(2911),
      hearing_7_days: n(642),
      not_claimed: n(18825),
      applications_inside: n(5210),
      applications_main_not_held: n(260),
    },
    kind_by_age: {
      bands: AGE.map(([key, label]) => ({ key, label })),
      rows: KINDS.map(([key, label, values]) => ({
        key,
        label,
        total: n(values.reduce((a, b) => a + b, 0)),
        by_age: Object.fromEntries(AGE.map(([k], i) => [k, n(values[i] ?? 0)])),
      })),
    },
    next_hearing: [
      ["today", "Today", 61],
      ["tomorrow", "Tomorrow", 88],
      ["days_2_7", "In 2 to 7 Days", 493],
      ["days_8_30", "In 8 to 30 Days", 2104],
      ["later", "Later", 3988],
      ["passed", "Date Passed", 9620],
      ["none", "No Date Yet", 2476],
    ].map(([key, label, count]) => ({ key: String(key), label: String(label), count: n(Number(count)) })),
    age: AGE.map(([key, label], i) => ({ key, label, count: n([8300, 5900, 2700, 1500, 280, 25, 1, 48][i] ?? 0) })),
    filed: ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "earlier", "unknown"].map((key, i) => ({
      key,
      label: key === "earlier" ? "Before 2019" : key === "unknown" ? "Year Not Known" : key,
      count: n([7400, 6100, 2300, 1100, 700, 450, 300, 200, 230, 50][i] ?? 0),
    })),
    subjects: [
      ["service_state", "Service: State Government Employees", 5400],
      ["service_teachers", "Service: Teachers of Provincialised Schools", 2900],
      ["land", "Land and Revenue", 2100],
      ["criminal", "Criminal Matters and Bail", 3300],
      ["foreigners", "Foreigners Tribunal and Citizenship", 1200],
      ["contempt", "Contempt (Original Subject Not Yet Known)", 1100],
      ["none", "No Category", 1800],
      ["not_grouped", "Not Grouped", 0],
    ].map(([key, label, count]) => ({ key: String(key), label: String(label), count: n(Number(count)) })),
    posts: [
      ["secretary", "Secretary", 4200],
      ["principal_secretary", "Principal Secretary", 2600],
      ["director", "Director", 3100],
      ["deputy_commissioner", "Deputy Commissioner", 2200],
      ["superintendent_police", "Superintendent of Police", 1900],
      ["inspector_schools", "Inspector of Schools", 700],
    ].map(([key, label, count]) => ({ key: String(key), label: String(label), count: n(Number(count)) })),
    counsel: [
      ["GA, ASSAM", 9800],
      ["SR. GA, ASSAM", 4100],
      ["PP, ASSAM", 3600],
      ["SC, EDU", 1900],
      ["SC, REVENUE", 1200],
      ["ADDL. AG, ASSAM", 800],
      ["SC, HEALTH", 600],
      ["SC, PWD", 410],
      ["SC, FOREST", 380],
      ["SC, FINANCE", 260],
      ["SC, SOCIAL WELFARE", 120],
      ["SC, LABOUR", 60],
    ].map(([key, count]) => ({ key: String(key), label: String(key), count: n(Number(count)) })),
    outcomes: [
      ["withdrawn", "Withdrawn", 300],
      ["infructuous", "Infructuous", 120],
      ["dismissed_default", "Dismissed for Default", 90],
      ["dismissed", "Dismissed", 800],
      ["rejected", "Rejected", 40],
      ["allowed", "Allowed", 410],
      ["disposed_of", "Disposed Of", 9200],
      ["closed", "Closed", 60],
      ["other", "Other", 30],
    ].map(([key, label, count]) => ({ key: String(key), label: String(label), count: n(Number(count)) })),
    departments: department
      ? null
      : [
          { code: "EDU", name: "Department of School Education, Government of Assam, Dispur", claimed: n(5), likely: n(2121), named: n(1400) },
          { code: "EDU-DSE", name: STRESS.office, claimed: n(0), likely: n(340), named: n(220) },
          { code: "HEALTH", name: "Health and Family Welfare", claimed: n(0), likely: n(0), named: n(610) },
        ],
    units: department
      ? [
          { code: "EDU-DSE", name: STRESS.office, claimed: n(3) },
          { code: "none", name: "Not Yet Assigned to a Unit", claimed: n(2) },
        ]
      : null,
    department_bands: department ? { claimed: n(5), likely: n(2121), named: n(1400) } : null,
    unmapped_named: n(9100),
    trend: ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"].map(
      (month, i) => ({ month, registered: n(2100 + ((i * 137) % 600)), disposed: n(1800 + ((i * 211) % 700)) }),
    ),
    accountability: {
      action: [
        ["not_claimed", "Not Claimed", 18825],
        ["closed", "Closed in ASLMS", 0],
        ["overdue", "Overdue", 2],
        ["due_soon", "Due Soon (2 Days)", 1],
        ["due_later", "Due Later", 1],
        ["no_due_date", "Action Pending With No Due Date", 0],
        ["with_officer", "With an Officer, No Action Pending", 1],
        ["not_sent", "Claimed, Not Sent to an Officer", 0],
      ].map(([key, label, count]) => ({ key: String(key), label: String(label), count: n(Number(count)) })),
      compliance: empty ? [] : [{ code: "EDU", name: "Department of School Education, Government of Assam, Dispur", overdue: 1, due_soon: 1 }],
      holders: empty ? [] : [{ code: "EDU-DSE", name: STRESS.office, overdue: 2 }],
      scorecard: department
        ? null
        : [
            {
              code: "EDU",
              name: "Department of School Education, Government of Assam, Dispur",
              claimed: n(5),
              likely: n(2121),
              named_only: n(1400),
              contempt_claimed: n(1),
              hearing_7_days: n(2),
              overdue_actions: n(2),
              compliance_overdue: n(1),
              median_days_to_claim: empty ? null : 6.5,
            },
            {
              code: "HEALTH",
              name: "Health and Family Welfare",
              claimed: 0,
              likely: 0,
              named_only: n(610),
              contempt_claimed: 0,
              hearing_7_days: 0,
              overdue_actions: 0,
              compliance_overdue: 0,
              median_days_to_claim: null,
            },
          ],
    },
  };
}

export function insightsCases(url: URL, sampleRef: string, istDayPlus: (days: number) => string): S["InsightsCasesOut"] {
  if (emptyFor(url)) return { items: [], total: 0, page: 1, page_size: 20, sort: "next" };
  const page = Number(url.searchParams.get("page") ?? "1") || 1;
  const kinds: S["InsightsWhoOut"][] = [
    {
      kind: "officer",
      text: `With Anita Sharma Baruah, ${STRESS.designation} · ${STRESS.office}`,
      officer_name: "Anita Sharma Baruah",
      designation: STRESS.designation,
      office_code: "EDU-DSE",
      department_code: "EDU",
      more: 0,
    },
    { kind: "recommended", text: "Not Claimed · Recommended to School Education and 2 more", recommended_to: "EDU", more: 2 },
    { kind: "office", text: "With School Education · Not Sent to an Officer", office_code: "EDU", department_code: "EDU", more: 0 },
    { kind: "none", text: "Not Claimed by Any Department", more: 0 },
  ];
  const items: S["InsightsCaseItemOut"][] = Array.from({ length: 20 }, (_, i) => {
    const n = (page - 1) * 20 + i + 1;
    return {
      case: {
        id: `0192a3b4-0000-7000-8000-0000000071${String(n).padStart(2, "0")}`.slice(0, 36),
        ref_no: i === 0 ? sampleRef : `ASLMS/GHC/CASE/2026/${String(54000 + n).padStart(6, "0")}`,
        case_no: i === 0 ? STRESS.caseNo : `WP(C)/${4000 + n}/2026`,
        cnr: `ASHC01${String(54000 + n).padStart(6, "0")}2026`,
      },
      kind: i % 5 === 1 ? { code: "contempt", label: "Contempt" } : { code: "wp", label: "Writ Petition" },
      status: "pending",
      who: kinds[i % kinds.length]!,
      next_hearing: { on: i % 4 === 3 ? null : istDayPlus((i % 9) - 2), basis: i % 6 === 2 ? "around" : "court" },
      disposal_date: null,
      departments_named:
        i % 3 === 0 ? [{ code: "EDU", name: "Department of School Education, Government of Assam, Dispur" }] : [],
      phrases_unmapped: i % 3 === 1 ? ["FINANCE (TAXATION)", "REVENUE AND DISASTER MANAGEMENT"] : [],
      applications_pending: i % 4 === 0 ? 2 : null,
      state_case: true,
      state_basis: i % 2 ? ["party", "counsel"] : ["officer", "title", "writ"],
    };
  });
  return { items, total: 18830, page, page_size: 20, sort: url.searchParams.get("sort") ?? "next" };
}

const GROUPS: [string, string, string][] = [
  ["identity", "case_no", "Case Number"],
  ["identity", "cnr", "CNR"],
  ["identity", "ref_no", "ASLMS Reference Number"],
  ["identity", "kind", "Kind of Case"],
  ["identity", "case_type_code", "Court's Case Type Code"],
  ["identity", "subject", "Subject (Court Category)"],
  ["identity", "filing_date", "Filing Date"],
  ["identity", "registration_date", "Registration Date"],
  ["identity", "pending_for", "Pending For (or Time Taken)"],
  ["parties", "petitioners", "Petitioners"],
  ["parties", "respondents", "Respondents"],
  ["parties", "state_case", "State Case"],
  ["parties", "department_named", "Department Named in the Cause Title"],
  ["parties", "posts", "Posts Named"],
  ["parties", "petitioner_advocate", "Petitioner's Advocate"],
  ["parties", "government_codes", "Counsel Code for the Government"],
  ["parties", "acts", "Acts and Sections"],
  ["court", "status", "Status"],
  ["court", "next_hearing", "Next Hearing"],
  ["court", "next_purpose", "Next Hearing Purpose"],
  ["court", "coram", "Bench or Judges"],
  ["court", "last_hearing_date", "Last Hearing Date"],
  ["court", "latest_order_date", "Latest Order Date"],
  ["court", "orders_count", "Number of Orders"],
  ["court", "disposal", "Disposal Date and Outcome"],
  ["court", "original_writ", "Original Writ (Contempt)"],
  ["work", "owning_department", "Owning Department"],
  ["work", "with_officer", "With Officer"],
  ["work", "recommended_to", "Recommended To"],
  ["work", "pending_action", "Pending Action and Due Date"],
  ["work", "case_stage", "Case Stage"],
  ["work", "open_closed", "Open or Closed in ASLMS"],
  ["work", "link", "Link to the Case Page"],
];
const DEFAULTS = new Set([1, 2, 4, 6, 8, 9, 10, 11, 12, 13, 16, 18, 19, 23, 27, 28, 29, 30]);

export function insightsFields(): S["InsightsFieldOut"][] {
  return [
    ...GROUPS.map(([group, key, label], i) => ({
      key,
      number: i + 1,
      label,
      group,
      default: DEFAULTS.has(i + 1),
      excel_only: key === "link",
    })),
    { key: "applications_pending", number: null, label: "Applications Pending", group: "work", default: false, excel_only: false },
  ];
}

function group(kind: "subject" | "family", code: string, label: string, i: number, extra: Partial<S["InsightGroupOut"]> = {}): S["InsightGroupOut"] {
  return {
    id: `0192a3b4-0000-7000-8000-00000000g${kind === "subject" ? "s" : "f"}${String(i).padStart(2, "0")}`,
    kind,
    code,
    label,
    description: null,
    sort_order: (i + 1) * 10,
    is_reserved: false,
    is_active: true,
    members: 12 + i,
    cases: 900 - i * 40,
    pending: 400 - i * 20,
    ...extra,
  };
}

export function insightGroups(url: URL): S["InsightGroupOut"][] {
  if (url.searchParams.get("kind") === "family") {
    return [
      group("family", "wp", "Writ Petition", 0),
      group("family", "contempt", "Contempt", 1, { is_reserved: true }),
      group("family", "wa", "Writ Appeal", 2),
      group("family", "ia", "Interlocutory Application", 3, { is_reserved: true }),
      group("family", "other", "Other", 4, { is_reserved: true }),
    ];
  }
  return [
    group("subject", "service_state", "Service: State Government Employees", 0),
    group("subject", "service_teachers", "Service: Teachers of Provincialised Schools", 1),
    group("subject", "land", "Land and Revenue", 2),
    group("subject", "elections", "Panchayat, Municipal, Elections and Co-operatives", 3, { is_active: false }),
    group("subject", "contempt", "Contempt (Original Subject Not Yet Known)", 4, { is_reserved: true }),
  ];
}

export function insightCategories(): S["InsightCategoryOut"][] {
  return [
    { code: 10245, label: "Service Matters - Pay Fixation and Arrears of the Employees of the State Government", group: "service_state", cases: 812, pending: 344 },
    { code: 10247, label: "Service Matters - Provincialisation of Venture Schools", group: "service_teachers", cases: 640, pending: 290 },
    { code: 20240, label: "Land Acquisition and Compensation", group: "land", cases: 410, pending: 120 },
    { code: 30210, label: "Panchayat Elections", group: "elections", cases: 90, pending: 12 },
    { code: 40999, label: "A Category the Court Added Later", group: null, cases: 3, pending: 3 },
  ];
}

export function insightCaseTypes(): S["InsightCaseTypeOut"][] {
  return [
    { id: "0192a3b4-0000-7000-8000-0000000000t1", code: 111, name: "WP(C)", full_name: "Writ Petition (Civil)", group: "wp", cases: 9100, pending: 4100 },
    { id: "0192a3b4-0000-7000-8000-0000000000t2", code: 142, name: "CONT.CAS(C)", full_name: "Contempt Case (Civil)", group: "contempt", cases: 1900, pending: 1200 },
    { id: "0192a3b4-0000-7000-8000-0000000000t3", code: 218, name: "I.A.(CIVIL)", full_name: "Interlocutory Application (Civil)", group: "ia", cases: 9800, pending: 3600 },
    { id: "0192a3b4-0000-7000-8000-0000000000t4", code: 159, name: "MC", full_name: null, group: "other", cases: 300, pending: 40 },
  ];
}

export function titleNames(url: URL): S["TitleNameListOut"] {
  if (url.searchParams.get("active") === "false") {
    return { items: [], total: 0 };
  }
  return {
    items: [
      { id: "0192a3b4-0000-7000-8000-0000000000n1", phrase: "SCHOOL EDUCATION", office_code: "EDU", office_name: "Department of School Education, Government of Assam, Dispur", department_code: "EDU", is_active: true, cases: 1210 },
      { id: "0192a3b4-0000-7000-8000-0000000000n2", phrase: "SECONDARY EDUCATION", office_code: "EDU-DSE", office_name: STRESS.office, department_code: "EDU", is_active: true, cases: 340 },
    ],
    total: 2,
  };
}

export function unmappedTitleNames(): S["UnmappedTitleNamePageOut"] {
  return {
    items: [
      { phrase: "REVENUE AND DISASTER MANAGEMENT", cases: 2310, example_case_no: STRESS.caseNo },
      { phrase: "FINANCE (TAXATION)", cases: 880, example_case_no: "WP(C)/4211/2026" },
      { phrase: "PANCHAYAT AND RURAL DEVELOPMENT", cases: 610, example_case_no: null },
    ],
    total: 3,
  };
}
