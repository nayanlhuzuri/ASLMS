/**
 * Fixtures of the System health component tests (designs api-health-checker and system-health-inspector): the 17
 * cards in four groups, the summary, the services, the token's reading and the scripted relay for the screen.
 */
import type {
  ApiCard,
  ApiConsole,
  ApiDetail,
  ApiTest,
  NapixReference,
  NapixToken,
  ServicesHealth,
  SystemHealth as SystemHealthData,
} from "@/lib/api/types";

import { browserApi, makeMe } from "./render";

export const GROUPS: [string, string[]][] = [
  ["masters", ["overview", "state", "district", "bench_master", "case_type", "act"]],
  ["causelists", ["causelist_bench", "causelist_details", "show_causelist"]],
  ["cases", ["cnr", "current_status", "order", "show_business"]],
  ["searches", ["case_search", "filing", "party_name", "advocate_name"]],
];

export function hours(answered = 0, failed = 0) {
  return Array.from({ length: 24 }, (_, i) => ({
    hour: `2026-10-21T${String(i % 24).padStart(2, "0")}:00:00+05:30`,
    answered: i === 23 ? answered : 0,
    failed: i === 23 ? failed : 0,
    avg_ms: null,
  }));
}

export function card(key: string, extra: Partial<ApiCard> = {}): ApiCard {
  return {
    key,
    label: key,
    label_key: key,
    group: "masters",
    status: "ok",
    status_word: "Working",
    last_call: {
      called_at: "2026-10-21T14:31:00+05:30",
      answered: true,
      ok: true,
      duration_ms: 840,
      http_status: 200,
      napix_status: null,
      error_family: null,
      reason: "The court answered",
      by: "background",
    },
    h24: { calls: 120, answered: 118, failed: 2, rate: 0.9833, p50_ms: 800, p95_ms: 1500 },
    d7: { calls: 700, answered: 679, failed: 21, rate: 0.97 },
    hours: hours(118, 2),
    test: { available: true, reason: null, cost: 1, next_allowed_at: null },
    last_test: null,
    ...extra,
  };
}

export function summary(enabled = true, cards: Record<string, Partial<ApiCard>> = {}): SystemHealthData {
  return {
    as_of: "2026-10-21T14:32:00+05:30",
    napix_enabled: enabled,
    window: {
      status: "current",
      started_at: "2026-10-21T13:34:00+05:30",
      observed_at: "2026-10-21T13:34:00+05:30",
      next_reset_at: "2026-10-21T14:34:00+05:30",
      seconds_to_next_reset: 120,
      anchor_at: null,
      calls: 188,
      failed: 2,
      remaining: 812,
      last_reading_at: null,
      recent_resets: [],
      window_seconds: 3600,
      margin_seconds: 60,
      probe_seconds: 180,
      reserve: 150,
      live_reserve: 100,
      search_floor: 50,
    },
    groups: GROUPS.map(([key, keys]) => ({
      key,
      label: key,
      cards: keys.map((k) => card(k, { group: key, ...(cards[k] ?? {}) })),
    })),
    summary: { working: 17, unsteady: 0, failing: 0, no_recent: 0, total: 17 },
  } as SystemHealthData;
}

export const SERVICES: ServicesHealth = {
  checked_at: "2026-10-21T14:32:00+05:30",
  overall: {
    status: "down",
    sentence_key: "not_working",
    counts: { court_working: 17, court_total: 17, services_working: 9, services_total: 10, attention: 0, not_working: 1 },
  },
  services: [
    { key: "api", label: "ASLMS API", status: "ok", headline: "Answering", facts: [{ label: "Version", value: "3.0.0" }], duration_ms: 0 },
    { key: "clamav", label: "Virus scanner", status: "down", headline: "The virus scanner does not answer", facts: [], duration_ms: 5 },
  ],
};

/** The Access token card's reading (the switch flag is the caller's: a file never turns it on). */
export function tokenState(enabled = true, extra: Partial<NapixToken> = {}): NapixToken {
  return {
    status: "ok",
    napix_enabled: enabled,
    shared_store: true,
    held: true,
    ttl_seconds: 2520,
    renewing_soon: false,
    valid_until: "2026-10-21T15:16:00+05:30",
    expires_at: "2026-10-21T15:16:00+05:30",
    obtained_at: "2026-10-21T14:16:00+05:30",
    token_type: "Bearer",
    scope: "napix",
    accepted_since: { at: "2026-10-21T14:31:05+05:30", api_label: "Case details by CNR", http_status: 200 },
    rejected_since: 0,
    last_request: {
      at: "2026-10-21T14:16:00+05:30",
      ok: true,
      outcome: "obtained",
      http_status: 200,
      duration_ms: 310,
      rate_limit: { limit: null, remaining: null },
    },
    last_failure: null,
    requests_today: 3,
    endpoint: {
      method: "POST",
      url: "https://delhigw.napix.gov.in/nic/ecourts//oauth2/token",
      body: "grant_type=client_credentials&scope=napix",
      content_type: "application/x-www-form-urlencoded",
      auth_note: "Basic authentication with the client key and secret from .env (not shown)",
    },
    curl_token: "curl -X POST 'https://delhigw.napix.gov.in/nic/ecourts//oauth2/token' -u '<CLIENT_KEY>:<CLIENT_SECRET>'",
    check: { allowed: true, reason: null, next_allowed_at: null },
    ...extra,
  };
}

export function routes(data: SystemHealthData = summary(), extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": makeMe(["admin.service_health"], "super_admin"),
    "GET /admin/system-health": data,
    "GET /admin/system-health/services": SERVICES,
    "GET /admin/system-health/token": tokenState(),
    ...extra,
  });
}

const CNR = "GAHC010277142024";

/** The console of Case details by CNR as the server builds it (no secret: dept_id masked, request_str not shown). */
export function consoleOf(extra: Partial<ApiConsole> = {}): ApiConsole {
  return {
    api: "cnr",
    label: "Case details by CNR",
    method: "GET",
    method_note: null,
    url: "https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR",
    plain: `cino=${CNR}`,
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
    templates: { curl: `# plain string: cino=${CNR}\ncurl -G 'https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR' \\n  -H 'Authorization: Bearer <ACCESS_TOKEN>'`, note: "These do not run as they are." },
    fields: [
      {
        name: "cino",
        value: CNR,
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
    sample: { available: true, label: `WP(C)/7714/2024 (CNR ${CNR})`, reason: null },
    send: { available: true, reason: null, cost: 1, next_allowed_at: null },
    last_send: null,
    latest_answer: null,
    doc: { doc: "hc_spec", page: 12, section: "6.1 Search by CNR API", available: true },
    full_answer_allowed: true,
    not_saved_note: "Shown, not saved to cases. Use Search to add a case.",
    full_answer_note: null,
    ...extra,
  };
}

/** One Send's answer: structure, inventory check and the stored answer's id. */
export function sendResult(extra: Partial<ApiTest> = {}): ApiTest {
  return {
    api: "cnr",
    ok: true,
    answered: true,
    status: "ok",
    reason: "The court answered",
    http_status: 200,
    napix_status: null,
    error_family: null,
    duration_ms: 910,
    attempts: 1,
    called_at: "2026-10-21T14:33:00+05:30",
    token_verified: true,
    remaining: 811,
    input: { label: "The values in the form", values: {} },
    summary: { kind: "record", row_count: 64, field_names: ["cino"], facts: [{ label: "Case status", value: "pending" }] },
    request: { method: "GET", url: "https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR", plain: "cino=GAHC010118832025", envelope: [] },
    edited: true,
    rate_limit: { limit: 1000, remaining: 811 },
    structure: {
      paths: [
        { path: "cino", type: "str", count: 1 },
        { path: "brand_new_field", type: "str", count: 1 },
      ],
      total: 2,
      more: 0,
      depth_limited: false,
    },
    inventory_diff: { checked: true, new: ["brand_new_field"], absent: ["acts[].actname"] },
    response_id: "0192f000-0000-7000-8000-000000000001",
    response_available: true,
    http_meaning: "Everything is normal: the gateway answered.",
    napix_meaning: null,
    ...extra,
  };
}

export function detailOf(key: string): ApiDetail {
  return {
    card: card(key),
    days: Array.from({ length: 7 }, (_, i) => ({ date: `2026-10-${15 + i}`, calls: 10, answered: 9, failed: 1, avg_ms: 700 })),
    recent: [card(key).last_call!],
    sample: { available: true, label: "a case held by ASLMS", values: {}, reason: null },
    technical: { name: key, path: "hc-cnr-api/CNR", method: "GET", input_fields: ["cino"] },
  };
}

export function referenceOf(api = "cnr"): NapixReference {
  return {
    api,
    inputs: [{ name: "cino", mandatory: true, required: true, format: "16 letters and digits", meaning: "The case's CNR.", note: null }],
    outputs: { kind: "json", note: null, paths: [{ path: "cino", type: "str" }] },
    statuses: [{ code: "600", name: "INVALID_CNR", meaning: "The CNR is not in the prescribed format.", listed: true }],
    build_steps: ["The plain string."],
    read_steps: ["The answer."],
    doc: api === "token"
      ? { doc: "subscriber_manual", page: 10, section: "2.2 Token Generation", available: true }
      : { doc: "hc_spec", page: 12, section: "6.1 Search by CNR API", available: true },
    general_links: [{ doc: "hc_spec", page: 68, label: "Annexure A: encryption and hash" }],
  };
}
