/** Fixtures shared by the Case inbox and Case claim tests (design portal-ui-redesign, round 2). */
import type {
  CaseDetail,
  CaseOwnershipView,
  CaseSummary,
  InboxCounts,
  Me,
  MyCase,
  OwnershipActions,
  Permission,
  PoolCase,
  Recommendation,
  Transfer,
} from "@/lib/api/types";

import { makeMe } from "./render";

export const ADMIN_FNS: Permission[] = [
  "cases.view_scope",
  "cases.claim",
  "cases.dismiss",
  "cases.suggest_elsewhere",
  "cases.allot",
  "cases.transfer_request",
  "cases.transfer_decide",
  "documents.view",
  "documents.download",
];

export const REF = "ASLMS-GOA-CASE-2026-000001";

export function membership(code: string, functions: Permission[], primary = true, role: Me["user"]["role"] = "dept_admin") {
  return {
    id: `m-${code}`,
    office: { code, name: code, kind: "department" },
    department_code: code,
    designation: null,
    role,
    is_primary: primary,
    is_active: true,
    functions,
  };
}

export function admin(functions: Permission[] = ADMIN_FNS, extra: Partial<Me> = {}): Me {
  return makeMe(functions, "dept_admin", { memberships: [membership("EDU", functions)], ...extra });
}

export function officer(functions: Permission[] = ["cases.view_scope"]): Me {
  return makeMe(functions, "dept_officer", { memberships: [membership("EDU", functions, true, "dept_officer")] });
}

export function block(code: string | null, extra: Partial<InboxCounts> = {}): InboxCounts {
  return {
    office_code: code,
    recommended_high: 2,
    recommended_medium: 1,
    claimed_active: 4,
    claimed_disposed: 1,
    transfers_in_open: 1,
    pool_with_hearing_7d: 3,
    whole_department: true,
    ...extra,
  };
}

export function summary(n: number, extra: Partial<CaseSummary> = {}): CaseSummary {
  return {
    id: `c-${n}`,
    ref_no: `ASLMS/GOA/CASE/2026/00000${n}`,
    cnr: `ASHC01000${n}002026`,
    case_no_text: `WP(C)/${n}/2026`,
    is_provisional: false,
    petitioner_summary: "RAM KUMAR",
    respondent_summary: "STATE OF ASSAM",
    status: "pending",
    next_hearing_date: null,
    last_listed_on: "2026-09-25",
    last_listing: { list_date: "2026-09-25", list_type: "daily", court_no: "3", sr_no: 41 },
    ...extra,
  };
}

export function rec(n: number, extra: Partial<Recommendation> = {}): Recommendation {
  return {
    id: `r-${n}`,
    case: summary(n),
    office_code: "EDU",
    score: 0.849,
    band: "medium",
    status: "recommended",
    origin: "cause_list",
    signals: [
      { kind: "counsel_code", matched: "SC, EDU", weight: 0.6 },
      { kind: "linked_case", matched: "WP(C)/2417/2026", weight: 0.249 },
    ],
    suggested_by_office_code: null,
    reason: null,
    created_at: "2026-10-01T10:00:00Z",
    acted_at: null,
    current_owner_code: null,
    ...extra,
  };
}

export function poolItem(n: number, extra: Partial<PoolCase> = {}): PoolCase {
  return { case: summary(n), best_score: 0.42, best_office_code: "FIN", dismissed_by: ["HEALTH"], ...extra };
}

export function transfer(n: number, extra: Partial<Transfer> = {}): Transfer {
  return {
    id: `t-${n}`,
    ref_no: `ASLMS/EDU/TRF/2026/00000${n}`,
    case: summary(n),
    from_office_code: "HEALTH",
    to_office_code: "EDU",
    status: "requested",
    reason: "theirs",
    stay_as_watcher: false,
    decision_note: null,
    requested_by: { id: "u-2", full_name: "Health Admin" },
    requested_at: "2026-10-01T10:00:00Z",
    decided_by: null,
    decided_at: null,
    withdrawn_at: null,
    ...extra,
  };
}

export function actions(extra: Partial<OwnershipActions> = {}): OwnershipActions {
  return {
    claim: false,
    claim_departments: [],
    dismiss: false,
    dismiss_departments: [],
    suggest: false,
    suggest_departments: [],
    allot: false,
    allot_departments: [],
    take_over: false,
    take_over_departments: [],
    stop_watching: false,
    stop_watching_departments: [],
    request_transfer: false,
    transfer_from: null,
    withdraw_transfer: false,
    decide_transfer: false,
    ...extra,
  };
}

export function ownershipView(a: OwnershipActions, extra: Partial<CaseOwnershipView> = {}): CaseOwnershipView {
  return { primary: null, watchers: [], recommendations: [], open_transfer: null, actions: a, ...extra };
}

/** The overview fields the modal reads; the rest of `CaseDetailOut` is not needed by these tests. */
export function caseDetail(extra: Partial<CaseDetail> = {}): CaseDetail {
  return {
    id: "c-1",
    ref_no: "ASLMS/GOA/CASE/2026/000001",
    identity: {
      cnr: "ASHC010001002026",
      court_est_name: "Gauhati High Court",
      case_type_id: null,
      case_type_text: "WP(C)",
      reg_no: 1,
      reg_year: 2026,
      case_no_text: "WP(C)/1/2026",
      filing_case_type_id: null,
      filing_case_type_text: null,
      filing_no: null,
      filing_year: null,
      filing_no_text: null,
      filing_date: "2026-01-10",
      registration_date: null,
      date_first_list: null,
    },
    status: { status: "pending", next_hearing_date: "2026-09-25" },
    classification: { category: "Service", bench_name: "Single Bench" },
    court: { est_code: "GAHC01", name: "Principal Seat" },
    parties_as_printed: { petitioner_summary: "RAM KUMAR", respondent_summary: "STATE OF ASSAM", pet_advocate: null, res_advocate: null },
    ownership: { primary: null, watchers: [] },
    access_basis: ["recommended"],
    ...extra,
  } as unknown as CaseDetail;
}

export function myCase(n: number, extra: Partial<MyCase> = {}): MyCase {
  return {
    case: summary(n),
    owner_code: "EDU",
    stage: null,
    custody: null,
    allotment: null,
    reasons: ["allotted"],
    ...extra,
  };
}
