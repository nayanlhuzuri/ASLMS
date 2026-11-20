/** Answers of the Insights API for component tests (design state-insights, round 2). */
import type { InsightsCaseItem, InsightsCases, InsightsField, InsightsOverview, InsightsScopes } from "@/lib/api/types";

export const SCOPES_STATE: InsightsScopes = {
  state: true,
  departments: [
    { code: "EDU", name: "School Education" },
    { code: "HEALTH", name: "Health and Family Welfare" },
  ],
  default: { scope: "state", department: null },
};

export const SCOPES_ONE: InsightsScopes = {
  state: false,
  departments: [{ code: "EDU", name: "School Education" }],
  default: { scope: "department", department: "EDU" },
};

const AGE = ["age_lt_1", "age_1_3", "age_3_5", "age_5_10", "age_10_20", "age_20_30", "age_gt_30", "age_unknown"];
const AGE_LABELS = ["Up to 1 Year", "1 to 3 Years", "3 to 5 Years", "5 to 10 Years", "10 to 20 Years", "20 to 30 Years", "Over 30 Years", "Age Not Known"];

function byAge(values: number[]): Record<string, number> {
  return Object.fromEntries(AGE.map((k, i) => [k, values[i] ?? 0]));
}

export function overview(extra: Partial<InsightsOverview> = {}): InsightsOverview {
  return {
    scope: { kind: "state", department: null },
    generated_at: "2026-11-19T05:00:00Z",
    coverage: {
      court: "Gauhati High Court",
      listed_since: "2025-01-03",
      facts_waiting: 0,
      facts_built_at: "2026-11-19T04:50:00Z",
      line: "Cases listed since 3 Jan 2025 · State cases (worked out) · Pending · Interlocutory applications inside their main case",
    },
    chips: [],
    headline: {
      cases: 120,
      state_cases: 100,
      contempt: 12,
      over_5_years: 30,
      hearing_7_days: 9,
      not_claimed: 80,
      applications_inside: 14,
      applications_main_not_held: 2,
    },
    kind_by_age: {
      bands: AGE.map((k, i) => ({ key: k, label: AGE_LABELS[i]! })),
      rows: [
        { key: "wp", label: "Writ Petition", total: 70, by_age: byAge([20, 30, 10, 10]) },
        { key: "contempt", label: "Contempt", total: 12, by_age: byAge([2, 4, 6]) },
      ],
    },
    next_hearing: [
      { key: "today", label: "Today", count: 4 },
      { key: "tomorrow", label: "Tomorrow", count: 2 },
      { key: "days_2_7", label: "In 2 to 7 Days", count: 3 },
      { key: "days_8_30", label: "In 8 to 30 Days", count: 10 },
      { key: "later", label: "Later", count: 50 },
      { key: "passed", label: "Date Passed", count: 40 },
      { key: "none", label: "No Date Yet", count: 11 },
    ],
    age: AGE.map((k, i) => ({ key: k, label: AGE_LABELS[i]!, count: [40, 30, 20, 20, 10, 0, 0, 0][i]! })),
    filed: [
      { key: "2026", label: "2026", count: 40 },
      { key: "2025", label: "2025", count: 50 },
      { key: "earlier", label: "Before 2019", count: 30 },
      { key: "unknown", label: "Year Not Known", count: 0 },
    ],
    subjects: [
      { key: "service_state", label: "Service: State Government Employees", count: 60 },
      { key: "none", label: "No Category", count: 5 },
    ],
    posts: [
      { key: "secretary", label: "Secretary", count: 30 },
      { key: "director", label: "Director", count: 20 },
    ],
    counsel: [
      { key: "GA, ASSAM", label: "GA, ASSAM", count: 70 },
      { key: "SC, EDU", label: "SC, EDU", count: 15 },
    ],
    outcomes: [
      { key: "disposed_of", label: "Disposed Of", count: 40 },
      { key: "dismissed", label: "Dismissed", count: 5 },
    ],
    departments: [
      { code: "EDU", name: "School Education", claimed: 5, likely: 40, named: 20 },
      { code: "HEALTH", name: "Health and Family Welfare", claimed: 0, likely: 3, named: 8 },
    ],
    units: null,
    department_bands: null,
    unmapped_named: 7,
    trend: [
      { month: "2026-10", registered: 30, disposed: 25 },
      { month: "2026-11", registered: 12, disposed: 9 },
    ],
    accountability: {
      action: [
        { key: "not_claimed", label: "Not Claimed", count: 80 },
        { key: "overdue", label: "Overdue", count: 3 },
        { key: "due_soon", label: "Due Soon (2 Days)", count: 1 },
      ],
      compliance: [{ code: "EDU", name: "School Education", overdue: 2, due_soon: 1 }],
      holders: [{ code: "EDU-DSE", name: "Secondary Education", overdue: 3 }],
      scorecard: [
        {
          code: "EDU",
          name: "School Education",
          claimed: 5,
          likely: 40,
          named_only: 20,
          contempt_claimed: 1,
          hearing_7_days: 2,
          overdue_actions: 3,
          compliance_overdue: 2,
          median_days_to_claim: 6.5,
        },
      ],
    },
    ...extra,
  };
}

export function caseItem(n: number, extra: Partial<InsightsCaseItem> = {}): InsightsCaseItem {
  const no = String(n).padStart(6, "0");
  return {
    case: { id: `c-${n}`, ref_no: `ASLMS/GHC/CASE/2026/${no}`, case_no: `WP(C)/${n}/2026`, cnr: `ASHC01${no}2026` },
    kind: { code: "wp", label: "Writ Petition" },
    status: "pending",
    who: { kind: "not_claimed", text: "Not Claimed by Any Department", more: 0 },
    next_hearing: { on: null, basis: null },
    disposal_date: null,
    departments_named: [],
    phrases_unmapped: [],
    applications_pending: null,
    state_case: true,
    state_basis: ["party", "counsel"],
    ...extra,
  };
}

export function casesPage(items: InsightsCaseItem[], total = items.length, page = 1): InsightsCases {
  return { items, total, page, page_size: 20, sort: "next" };
}

/** The field registry as `GET /insights/fields` gives it (a part of the 33, with the defaults and the Excel-only link). */
export const FIELDS: InsightsField[] = [
  { key: "case_no", number: 1, label: "Case Number", group: "identity", default: true, excel_only: false },
  { key: "cnr", number: 2, label: "CNR", group: "identity", default: true, excel_only: false },
  { key: "ref_no", number: 3, label: "ASLMS Reference Number", group: "identity", default: false, excel_only: false },
  { key: "petitioners", number: 10, label: "Petitioners", group: "parties", default: true, excel_only: false },
  { key: "status", number: 18, label: "Status", group: "court", default: true, excel_only: false },
  { key: "coram", number: 21, label: "Bench or Judges", group: "court", default: false, excel_only: false },
  { key: "owning_department", number: 27, label: "Owning Department", group: "work", default: true, excel_only: false },
  { key: "link", number: 33, label: "Link to the Case Page", group: "work", default: false, excel_only: true },
  { key: "applications_pending", number: null, label: "Applications Pending", group: "work", default: false, excel_only: false },
];
