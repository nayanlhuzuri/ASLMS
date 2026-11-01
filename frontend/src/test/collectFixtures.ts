/**
 * Collect Now's answers for the tests (design data-collection-redesign, round 3): a "use everything" plan, a request's
 * summary and its detail, built with overrides.
 */
import type { CollectPlan, CollectRequest, CollectSummary } from "@/lib/dataCollection";

export const PLAN: CollectPlan = {
  calls: 1250,
  remaining: 640,
  this_hour: 640,
  after_reset: 610,
  next_reset_at: "2026-10-29T16:35:00+05:30",
  finish_at: "2026-10-29T17:20:00+05:30",
  hourly_limit: 1000,
  search_floor: 50,
  rate_reserve: 150,
  live_reserve: 100,
};

const STATES = { waiting: 0, waiting_retry: 0, fetching: 0, done: 0, not_found: 0, failed: 0 };

export function summary(over: Partial<CollectSummary> = {}): CollectSummary {
  return {
    request_id: "r-1",
    action: "data_load.collect_requested",
    kind: "cases",
    bulk: false,
    asked_by: "Super Administrator",
    asked_by_office: "GOA",
    asked_at: "2026-10-29T15:50:00+05:30",
    date: null,
    scope: null,
    cases: 1,
    ref: "GAHC010129772026",
    priority: 3,
    counts: { ...STATES, waiting: 1 },
    by_kind: { dossier: { ...STATES, waiting: 1 } },
    total: 1,
    finished: false,
    stopped: false,
    stopped_at: null,
    stopped_by: null,
    using_everything: false,
    retry_at: null,
    eta_seconds: null,
    expected_end: null,
    ...over,
  };
}

export function detail(over: Partial<CollectRequest> = {}): CollectRequest {
  return {
    ...summary(),
    items: [],
    limit: 100,
    offset: 0,
    results: [],
    steps: { details: { ...STATES, waiting: 1 }, orders: { total: 0, stored: 0, not_available: 0, failed: 0, waiting: 0 } },
    collector: { last_active_at: "2026-10-29T15:49:00+05:30", now_waiting: false, not_running: false },
    window: { remaining: 640, next_reset_at: "2026-10-29T16:35:00+05:30", limit_used_up: false, resumes_at: null },
    left_out: [],
    ...over,
  };
}

/** A finished one-case request: details fetched, 39 PDFs stored, 1 not available, 1 waiting for a retry. */
export function finishedCase(): CollectRequest {
  return detail({
    finished: true,
    counts: { ...STATES, done: 40, not_found: 1, waiting_retry: 1 },
    by_kind: { dossier: { ...STATES, done: 1 }, order_pdf: { ...STATES, done: 39, not_found: 1, waiting_retry: 1 } },
    total: 42,
    retry_at: "2026-10-29T16:40:00+05:30",
    steps: { details: { ...STATES, done: 1 }, orders: { total: 41, stored: 39, not_available: 1, failed: 0, waiting: 0 } },
    results: [
      {
        case: { id: "c-1", ref_no: "ASLMS/GHC/CASE/2026/000001", cnr: "GAHC010129772026", case_no_text: "WP(C)/3600/2026" },
        status: "pending",
        details_fetched_at: "2026-10-29T15:51:00+05:30",
        details: "done",
        orders: { total: 41, stored: 39, not_available: 1, failed: 0, waiting: 0, retry_at: "2026-10-29T16:40:00+05:30" },
      },
    ],
  });
}

export function requestsList(items: CollectSummary[] = [], over: Record<string, unknown> = {}) {
  return {
    as_of: "2026-10-29T15:52:00+05:30",
    items,
    active: items.filter((i) => !i.finished).length,
    bulk: items.find((i) => i.using_everything) ?? null,
    collector: { last_active_at: "2026-10-29T15:49:00+05:30", now_waiting: false, not_running: false },
    window: { remaining: 640, next_reset_at: "2026-10-29T16:35:00+05:30", limit_used_up: false, resumes_at: null },
    ...over,
  };
}
