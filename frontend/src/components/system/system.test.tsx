import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/shell/PortalShell";
import type { ApiCard, ApiDetail, ApiTest, ServicesHealth, SystemHealth as SystemHealthData } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, labels, makeMe, renderWithClient } from "@/test/render";

import { SystemHealth } from "./SystemHealth";

const GROUPS: [string, string[]][] = [
  ["masters", ["overview", "state", "district", "bench_master", "case_type", "act"]],
  ["causelists", ["causelist_bench", "causelist_details", "show_causelist"]],
  ["cases", ["cnr", "current_status", "order", "show_business"]],
  ["searches", ["case_search", "filing", "party_name", "advocate_name"]],
];

function hours(answered = 0, failed = 0) {
  return Array.from({ length: 24 }, (_, i) => ({
    hour: `2026-10-21T${String(i % 24).padStart(2, "0")}:00:00+05:30`,
    answered: i === 23 ? answered : 0,
    failed: i === 23 ? failed : 0,
    avg_ms: null,
  }));
}

function card(key: string, extra: Partial<ApiCard> = {}): ApiCard {
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

function summary(enabled = true, cards: Record<string, Partial<ApiCard>> = {}): SystemHealthData {
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

const SERVICES: ServicesHealth = {
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

function detail(key: string): ApiDetail {
  return {
    card: card(key),
    days: Array.from({ length: 7 }, (_, i) => ({ date: `2026-10-${15 + i}`, calls: 10, answered: 9, failed: 1, avg_ms: 700 })),
    recent: [card(key).last_call!],
    sample: { available: true, label: "a case held by ASLMS", values: {}, reason: null },
    technical: { name: key, path: "hc-cnr-api/CNR", method: "GET", input_fields: ["cino"] },
  };
}

const RESULT: ApiTest = {
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
  input: { label: "a case held by ASLMS", values: {} },
  summary: {
    kind: "record",
    row_count: 64,
    field_names: ["cino", "pend_disp"],
    facts: [{ label: "Case status", value: "pending" }],
  },
};

function routes(data: SystemHealthData = summary(), extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": makeMe(["admin.service_health"], "super_admin"),
    "GET /admin/system-health": data,
    "GET /admin/system-health/services": SERVICES,
    "GET /admin/system-health/napix/cnr": detail("cnr"),
    ...extra,
  });
}

beforeEach(() => {
  resetNav("/system");
});

type View = ReturnType<typeof renderWithClient>;

/** A new address: the server page renders the screen again with the new query (inside the same query client). */
function navigate(view: View, ui: ReactElement) {
  view.rerender(<QueryClientProvider client={view.client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.useRealTimers();
});

describe("the navigation entry", () => {
  it("shows only with admin.service_health, after Data collection", () => {
    const { unmount } = renderWithClient(<Sidebar me={makeMe(["admin.napix_refetch", "reports.state"], "central_operator")} />);
    expect(screen.queryByRole("link", { name: "System health" })).toBeNull();
    unmount();
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(["admin.service_health", "admin.data_load", "users.view"], "super_admin")} />);
    const links = within(screen.getByRole("navigation", { name: "Main navigation" }))
      .getAllByRole("link")
      .map((a) => a.textContent);
    const at = links.findIndex((t) => t?.includes("System health"));
    expect(at).toBeGreaterThan(links.findIndex((t) => t?.includes("Data collection")));
    expect(at).toBeLessThan(links.findIndex((t) => t?.includes("Administration")));
  });
});

describe("the System health screen", () => {
  it("renders the 17 cards in four groups with their badge inside a Lead", async () => {
    routes();
    renderWithClient(<SystemHealth params={{}} />);
    expect(await screen.findByRole("heading", { name: "Connection and masters" })).toBeInTheDocument();
    for (const name of ["Cause lists", "Case details", "Searches"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    const cards = screen.getAllByTestId(/^card-/);
    expect(cards).toHaveLength(17);
    for (const c of cards) {
      const lead = c.querySelector("[data-lead='lead']");
      expect(lead).not.toBeNull();
      expect(lead!.textContent).toBe("Working");
    }
    expect(within(screen.getByTestId("card-cnr")).getByRole("button", { name: "Case details by CNR: details" })).toBeInTheDocument();
    expect(screen.getByText("17 of 17 working")).toBeInTheDocument();
  });

  it("shows the overview: ring, the server's sentence and the four figures", async () => {
    routes();
    renderWithClient(<SystemHealth params={{}} />);
    expect(await screen.findByRole("img", { name: "98 % answered" })).toBeInTheDocument();
    expect(await screen.findByText("1 is not working")).toBeInTheDocument();
    expect(screen.getByText("Court calls answered (24 h)")).toBeInTheDocument();
    expect(screen.getByText("Calls left this hour")).toBeInTheDocument();
    expect(screen.getByText("resets about 14:34")).toBeInTheDocument();
    expect(screen.getByText("ASLMS services working")).toBeInTheDocument();
  });

  it("disables Test now with the reason when the switch is off", async () => {
    routes(summary(false, Object.fromEntries(GROUPS.flatMap(([, ks]) => ks).map((k) => [k, { test: { available: false, reason: "Court calls are switched off on this server (NAPIX_ENABLED is false)", cost: 1, next_allowed_at: null } }]))));
    renderWithClient(<SystemHealth params={{}} />);
    expect(await screen.findByText(/The cards show the last results; tests are not possible/)).toBeInTheDocument();
    const button = within(screen.getByTestId("card-state")).getByRole("button", { name: "Test now · 1 court call" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription("Court calls are switched off on this server (NAPIX_ENABLED is false)");
  });

  it("disables Test now when no sample is held or the next test is not yet allowed", async () => {
    const soon = new Date(Date.now() + 40_000).toISOString();
    routes(
      summary(true, {
        order: { test: { available: false, reason: "No stored order PDF yet", cost: 1, next_allowed_at: null } },
        state: { test: { available: false, reason: "The next test of this API is not yet allowed", cost: 1, next_allowed_at: soon } },
      }),
    );
    renderWithClient(<SystemHealth params={{}} />);
    const order = within(await screen.findByTestId("card-order")).getByRole("button", { name: "Test now · 1 court call" });
    expect(order).toBeDisabled();
    expect(order).toHaveAccessibleDescription("No stored order PDF yet");
    const state = within(screen.getByTestId("card-state")).getByRole("button", { name: "Test now · 1 court call" });
    expect(state).toBeDisabled();
    expect(state).toHaveAccessibleDescription(/^Next test possible in (39|40) s$/);
    expect(within(screen.getByTestId("card-act")).getByRole("button", { name: "Test now · 1 court call" })).toBeEnabled();
  });

  it("a click posts once (a double click is guarded) and the panel shows the summary", async () => {
    let posts = 0;
    let release: (v: Response) => void = () => {};
    const api = routes(summary(), {
      "POST /admin/system-health/napix/cnr/test": () => {
        posts += 1;
        return new Promise<Response>((r) => (release = r));
      },
    });
    const view = renderWithClient(<SystemHealth params={{}} />);
    const button = within(await screen.findByTestId("card-cnr")).getByRole("button", { name: "Test now · 1 court call" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(posts).toBe(1);
    expect(nav.push).toHaveBeenCalledWith("/system?api=cnr");
    navigate(view, <SystemHealth params={{ api: "cnr" }} />);
    expect(await screen.findByRole("dialog", { name: "Case details by CNR" })).toBeInTheDocument();
    expect(screen.getByText("Testing… (up to 30 s)")).toBeInTheDocument();
    await act(async () => release(json(200, RESULT)));
    const dialog = screen.getByRole("dialog", { name: "Case details by CNR" });
    const result = within(dialog).getByRole("region", { name: "Result" });
    expect(await within(result).findByText("Answered")).toBeInTheDocument();
    expect(within(result).getByText("Case status")).toBeInTheDocument();
    expect(within(result).getByText("pending")).toBeInTheDocument();
    expect(within(result).getByText("Response time 910 ms")).toBeInTheDocument();
    expect(within(result).getByText("811")).toBeInTheDocument();
    expect(await within(dialog).findByText("a case held by ASLMS")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });

  it("a 429 shows when the next test is possible", async () => {
    routes(summary(), {
      "POST /admin/system-health/napix/cnr/test": json(
        429,
        { detail: { code: "test_too_soon", message: "too soon", retry_after: 42 } },
        { "retry-after": "42" },
      ),
    });
    renderWithClient(<SystemHealth params={{ api: "cnr" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Test now · 1 court call" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Next test possible in 42 s.");
  });

  it("a 409 no_sample shows the reason", async () => {
    routes(summary(), {
      "POST /admin/system-health/napix/cnr/test": json(409, {
        detail: { code: "no_sample", message: "No case has been fetched from the court yet" },
      }),
    });
    renderWithClient(<SystemHealth params={{ api: "cnr" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Test now · 1 court call" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("No case has been fetched from the court yet");
  });

  it("lists the services with words, and Check services again is the only primary button", async () => {
    const api = routes();
    renderWithClient(<SystemHealth params={{}} />);
    const list = (await screen.findByText("Virus scanner")).closest("ul")!;
    expect(list).not.toBeNull();
    expect(within(list).getByText("Not working")).toBeInTheDocument();
    expect(within(list).getAllByText("Working").length).toBeGreaterThan(0);
    await screen.findAllByTestId(/^card-/);
    const primaries = document.querySelectorAll("button[data-variant='primary']");
    expect(primaries).toHaveLength(1);
    expect(primaries[0]).toHaveTextContent("Check services again");
    const before = api.calls.filter((c) => c.path === "/admin/system-health/services").length;
    await userEvent.click(screen.getByRole("button", { name: "Check services again" }));
    await waitFor(() =>
      expect(api.calls.filter((c) => c.path === "/admin/system-health/services").length).toBe(before + 1),
    );
  });

  it("the panel's address is ?api= and Back closes it", async () => {
    routes();
    const view = renderWithClient(<SystemHealth params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Case details by CNR: details" }));
    expect(nav.push).toHaveBeenCalledWith("/system?api=cnr");
    navigate(view, <SystemHealth params={{ api: "cnr" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    expect(await within(dialog).findByRole("table", { name: "The last 7 days" })).toBeInTheDocument();
    expect(within(dialog).getByText("Background work")).toBeInTheDocument();
    // Back: the address loses ?api= and the panel closes
    navigate(view, <SystemHealth params={{}} />);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // the close button replaces the address opened directly (a fresh history entry, no mark of this page)
    window.history.replaceState(null, "", window.location.href);
    navigate(view, <SystemHealth params={{ api: "cnr" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /close/i }));
    expect(nav.replace).toHaveBeenCalledWith("/system");
  });

  it("closing the API card goes back after opening it (design portal-ui-polish, decision 10)", async () => {
    routes();
    const view = renderWithClient(<SystemHealth params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Case details by CNR: details" }));
    expect(nav.push).toHaveBeenCalledWith("/system?api=cnr");
    navigate(view, <SystemHealth params={{ api: "cnr" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    await waitFor(() => expect((window.history.state as Record<string, unknown> | null)?.__aslmsOverlay).toBe("api=cnr"));
    await userEvent.click(within(dialog).getByRole("button", { name: /close/i }));
    expect(nav.back).toHaveBeenCalledTimes(1);
    expect(nav.replace).not.toHaveBeenCalled();
  });
});
