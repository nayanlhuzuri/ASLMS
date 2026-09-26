import type { components } from "./api-types";

type S = components["schemas"];

export type Me = S["MeOut"];
export type Office = S["OfficeOut"];
export type OwnerRef = S["OwnerRef"];
export type CaseCard = S["CaseCard"];
export type CaseDetail = S["CaseDetail"];
export type EventOut = S["EventOut"];
export type Hearing = S["HearingOut"];
export type Listing = S["ListingOut"];
export type LinkOut = S["LinkOut"];
export type Order = S["OrderOut"];
export type ScoreOut = S["ScoreOut"];
export type Ownership = S["OwnershipOut"];
export type DocumentOut = S["DocumentOut"];
export type NextDate = S["NextDateOut"];
export type Recommendation = S["RecommendationOut"];
export type Transfer = S["TransferOut"];
export type SearchOut = S["SearchOut"];
export type CauseList = S["CauseListOut"];
export type Entry = S["EntryOut"];
export type Alert = S["AlertOut"];
export type CalendarItem = S["CalendarItem"];
export type Notification = S["NotificationOut"];
export type User = S["UserOut"];
export type UserIn = S["UserIn"];
export type UserPatch = S["UserPatch"];
export type CounselCode = S["CounselCodeOut"];
export type Pattern = S["PatternOut"];
export type Keyword = S["KeywordOut"];
export type Watch = S["WatchOut"];
export type CaseType = S["CaseTypeOut"];
export type Audit = S["AuditOut"];
export type Preference = S["PreferenceOut"];
export type PreferenceIn = S["PreferenceIn"];
export type Ok = S["Ok"];

export interface Page<T> {
  total: number;
  page: number;
  size: number;
  items: T[];
}

/** One signal behind a score (backend `Signal.as_dict`). */
export interface Signal {
  kind: string;
  value: string;
  weight: number;
  office?: string;
  matched_text?: string | null;
  suggested_unit?: string | null;
}

/** GET /dashboard (untyped in the OpenAPI document; shape from the backend service). */
export interface DashboardSummary {
  role: string;
  cases_in_scope: number;
  pending_cases: number;
  hearings_48h: number;
  hearings_week: number;
  unread_notifications: number;
  open_critical_alerts: number;
  undelivered_email?: number;
  recommended_high?: number;
  recommended_total?: number;
  transfers_incoming?: number;
  by_unit?: { unit: string; cases: number }[];
  unclaimed_pending?: number;
  unclaimed_listed_week?: number;
  by_department?: { office_id: string; code: string; name: string; pending: number }[];
  allotted_to_me?: number;
}

export interface CauseListDate {
  date: string;
  lists: number;
  entries: number;
}

export interface UnmappedCode {
  code: string;
  seen: number;
}

export interface Failure {
  id: string;
  kind: string;
  ref: string;
  error: string;
  attempts: number;
  first_seen: string;
  last_seen: string;
  resolved_at?: string | null;
}

export interface DataHealth {
  jobs: {
    job: string;
    run_date: string | null;
    status: string;
    started_at: string;
    finished_at: string | null;
    counters: Record<string, unknown> | null;
    error: string | null;
  }[];
  napix_calls: { api: string; calls: number; ok: number; avg_ms: number }[];
  open_failures: Failure[];
  cause_lists: { date: string; source: string; lists: number; entries: number }[];
  entries_by_source: { source: string; entries: number; with_cnr: number; cnr_rate: number }[];
  orders: Record<string, number>;
}

export interface ReportTable {
  title: string;
  rows: Record<string, string | number | null>[];
}

export interface LiveSearch {
  napix?: string;
  found?: number;
  stored?: number;
  error?: string;
}
