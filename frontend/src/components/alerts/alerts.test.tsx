import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { AlertItem } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, labels, makeMe, renderWithClient } from "@/test/render";

import { AlertList } from "./AlertList";
import { AlertsFrame } from "./AlertsFrame";

const CASE = { id: "c1", ref_no: "ASLMS/GOA/CASE/2026/000001", cnr: "ASHC010012342026", case_no_text: "WP(C)/1234/2026" };

function alert(extra: Partial<AlertItem> = {}): AlertItem {
  return {
    id: "a-1",
    ref_no: "ASLMS/GOA/ALR/2026/000001",
    kind: "hearing_due",
    kind_label: "Hearing due",
    severity: "high",
    status: "open",
    title: "Hearing in three days",
    body: "Listed as item 5",
    due_at: "2026-10-16T04:30:00Z",
    case: CASE,
    case_visible: true,
    ticket_ref: null,
    data: {},
    notified_at: "2026-10-13T04:30:00Z",
    read_at: null,
    acknowledged_by: null,
    acknowledged_at: null,
    closed_at: null,
    created_at: "2026-10-13T04:30:00Z",
    can_act: true,
    ...extra,
  };
}

const COUNTS = { unread: 2, open: { critical: 1, high: 3, normal: 4 } };

function page(items: AlertItem[]) {
  return { items, total: items.length };
}

function routes(items: AlertItem[], extra: Record<string, unknown> = {}) {
  return {
    "GET /reference/labels": labels(),
    "GET /alerts/counts": COUNTS,
    "GET /alerts": page(items),
    "POST /alerts/read": { marked: 1 },
    ...extra,
  };
}

function alertCalls(calls: { method: string; path: string }[]) {
  return calls.filter((c) => c.method === "GET" && c.path.startsWith("/alerts?"));
}

beforeEach(() => {
  resetNav("/alerts");
});

describe("the alert list (portal-files-alerts, decisions 7-9)", () => {
  it("the default list omits status and opening it posts nothing", async () => {
    const api = browserApi(routes([alert()]));
    renderWithClient(<AlertList params={{}} />);
    expect(await screen.findByText("Hearing in three days")).toBeInTheDocument();
    const call = alertCalls(api.calls)[0]!;
    expect(call.path).toBe("/alerts?offset=0&limit=50");
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("the filters go to the query string and to the API as its parameters", async () => {
    const api = browserApi(routes([]));
    const { unmount } = renderWithClient(<AlertList params={{}} />);
    expect(await screen.findByText("You have no open alerts.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Status"), "all");
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    await waitFor(() => expect(screen.getByRole("option", { name: "File movement" })).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "workflow");
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "critical");
    await userEvent.click(screen.getByLabelText("Unread only"));
    expect(nav.replace).not.toHaveBeenCalled(); // nothing is requested until Apply
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/alerts?status=all&kind=workflow&severity=critical&unread=true");
    unmount();
    renderWithClient(<AlertList params={{ status: "done", kind: "workflow", severity: "critical", unread: "true", offset: "50" }} />);
    expect(await screen.findByText("No alerts match these filters.")).toBeInTheDocument();
    const last = alertCalls(api.calls).at(-1)!.path;
    for (const part of ["status=done", "kind=workflow", "severity=critical", "unread=true", "offset=50"]) {
      expect(last).toContain(part);
    }
  });

  it("a filter change resets the offset", async () => {
    browserApi(routes([]));
    renderWithClient(<AlertList params={{ offset: "50" }} />);
    await screen.findByText("No alerts match these filters.");
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "high");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/alerts?severity=high");
  });

  it("shows the counts header from /alerts/counts", async () => {
    browserApi(routes([]));
    renderWithClient(<AlertList params={{}} />);
    const group = await screen.findByRole("group", { name: "Alert counts" });
    expect(within(group).getByText("Unread 2")).toBeInTheDocument();
    expect(within(group).getByText("Critical 1")).toBeInTheDocument();
    expect(within(group).getByText("High 3")).toBeInTheDocument();
    expect(within(group).getByText("Normal 4")).toBeInTheDocument();
  });

  it("Mark read shows only on unread rows and posts the one id; the list and counts are read again", async () => {
    const api = browserApi(routes([alert(), alert({ id: "a-2", title: "Already read", read_at: "2026-10-13T05:00:00Z" })]));
    renderWithClient(<AlertList params={{}} />);
    await screen.findByText("Already read");
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]!).getByText("New")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("unread")).toHaveClass("visually-hidden");
    expect(within(rows[1]!).queryByRole("button", { name: "Mark read" })).toBeNull();
    const before = alertCalls(api.calls).length;
    const countsBefore = api.calls.filter((c) => c.path === "/alerts/counts").length;
    await userEvent.click(within(rows[0]!).getByRole("button", { name: "Mark read" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ alert_ids: ["a-1"] }));
    await waitFor(() => expect(alertCalls(api.calls).length).toBeGreaterThan(before));
    expect(api.calls.filter((c) => c.path === "/alerts/counts").length).toBeGreaterThan(countsBefore);
  });

  it("Mark all read posts all and shows only while unread > 0", async () => {
    const api = browserApi(routes([alert()]));
    const { unmount } = renderWithClient(<AlertList params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ all: true }));
    unmount();
    browserApi(routes([], { "GET /alerts/counts": { unread: 0, open: { critical: 0, high: 0, normal: 0 } } }));
    renderWithClient(<AlertList params={{}} />);
    await screen.findByText("Unread 0");
    expect(screen.queryByRole("button", { name: "Mark all read" })).toBeNull();
  });

  it("following a case link marks the row read first, then navigates", async () => {
    const api = browserApi(routes([alert()]));
    renderWithClient(<AlertList params={{}} />);
    await userEvent.click(await screen.findByRole("link", { name: "WP(C)/1234/2026" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/cases/ASLMS-GOA-CASE-2026-000001"));
    const post = api.calls.findIndex((c) => c.method === "POST" && c.path === "/alerts/read");
    expect(post).toBeGreaterThanOrEqual(0);
    expect(api.calls[post]!.body).toEqual({ alert_ids: ["a-1"] });
  });

  it("navigates even when the mark fails", async () => {
    browserApi(routes([alert()], { "POST /alerts/read": json(500, { detail: "boom" }) }));
    renderWithClient(<AlertList params={{}} />);
    await userEvent.click(await screen.findByRole("link", { name: "WP(C)/1234/2026" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/cases/ASLMS-GOA-CASE-2026-000001"));
  });

  it("a case_visible: false row shows the case as text with the line, never a link", async () => {
    browserApi(routes([alert({ case_visible: false, kind: "workflow", kind_label: "File movement", title: "File recalled" })]));
    renderWithClient(<AlertList params={{}} />);
    await screen.findByText("File recalled");
    expect(screen.queryByRole("link", { name: "WP(C)/1234/2026" })).toBeNull();
    // portal-ui-redesign, decision 10.1: a case number is semibold with tabular figures (`cno`), not monospace
    expect(screen.getByText("WP(C)/1234/2026")).toHaveClass("cno");
    expect(screen.getByText("You can no longer open this case.")).toBeInTheDocument();
  });

  it("an admin-ticket row links to the ticket", async () => {
    browserApi(
      routes([alert({ case: null, case_visible: false, ticket_ref: "ASLMS/GOA/TKT/2026/000003", kind: "admin_ticket", kind_label: "Admin ticket" })]),
    );
    renderWithClient(<AlertList params={{}} />);
    expect(await screen.findByRole("link", { name: "Ticket ASLMS/GOA/TKT/2026/000003" })).toHaveAttribute(
      "href",
      "/admin/tickets/ASLMS-GOA-TKT-2026-000003",
    );
  });

  it("Acknowledge and Done show only with can_act and by status", async () => {
    browserApi(
      routes([
        alert({ id: "a-1", title: "Open one" }),
        alert({ id: "a-2", title: "Acknowledged one", status: "acknowledged" }),
        alert({ id: "a-3", title: "No function", can_act: false }),
        alert({ id: "a-4", title: "Done one", status: "done", can_act: false }),
      ]),
    );
    renderWithClient(<AlertList params={{}} />);
    await screen.findByText("Done one");
    const row = (title: string) => screen.getByText(title).closest("li")!;
    expect(within(row("Open one")).getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(within(row("Open one")).getByRole("button", { name: "Done" })).toBeInTheDocument();
    expect(within(row("Acknowledged one")).queryByRole("button", { name: "Acknowledge" })).toBeNull();
    expect(within(row("Acknowledged one")).getByRole("button", { name: "Done" })).toBeInTheDocument();
    expect(within(row("No function")).queryByRole("button", { name: "Done" })).toBeNull();
    expect(within(row("Done one")).queryByRole("button", { name: "Done" })).toBeNull();
  });

  it("after an acknowledge the list and the counts are read again", async () => {
    const api = browserApi(routes([alert()], { "POST /alerts/a-1/acknowledge": alert({ status: "acknowledged" }) }));
    renderWithClient(<AlertList params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Acknowledge" }));
    const dialog = screen.getByRole("dialog", { name: "Acknowledge the alert" });
    const lists = alertCalls(api.calls).length;
    const counts = api.calls.filter((c) => c.path === "/alerts/counts").length;
    await userEvent.click(within(dialog).getByRole("button", { name: "Acknowledge" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "/alerts/a-1/acknowledge")).toBe(true));
    await waitFor(() => expect(alertCalls(api.calls).length).toBeGreaterThan(lists));
    expect(api.calls.filter((c) => c.path === "/alerts/counts").length).toBeGreaterThan(counts);
  });

  it("an unknown filter value shows the server's message", async () => {
    browserApi(routes([], { "GET /alerts": json(400, { detail: { code: "bad_request", message: "unknown kind 'nonsense'" } }) }));
    renderWithClient(<AlertList params={{ kind: "nonsense" }} />);
    expect(await screen.findByText("unknown kind 'nonsense'")).toBeInTheDocument();
  });
});

describe("the Alerts frame (decisions 1, 13)", () => {
  it("Alerts has two tabs, Alerts and Next dates to confirm, and no calendar (portal-ui-redesign, decision 8)", async () => {
    browserApi({ "GET /me": makeMe(["cases.view_scope", "next_dates.review"]) });
    const { unmount } = renderWithClient(
      <AlertsFrame>
        <p>body</p>
      </AlertsFrame>,
    );
    expect(await screen.findByRole("heading", { name: "Alerts", level: 1 })).toBeInTheDocument();
    const tabs = await screen.findByRole("navigation", { name: "Alerts sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual(["Alerts", "Next dates to confirm"]);
    expect(within(tabs).getByRole("link", { name: "Alerts" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).queryByRole("link", { name: /calendar/i })).toBeNull();
    unmount();
    resetNav("/alerts/next-dates");
    renderWithClient(
      <AlertsFrame>
        <p>body</p>
      </AlertsFrame>,
    );
    const tabs2 = await screen.findByRole("navigation", { name: "Alerts sections" });
    expect(within(tabs2).getByRole("link", { name: "Alerts" })).not.toHaveAttribute("aria-current");
    expect(within(tabs2).getByRole("link", { name: "Next dates to confirm" })).toHaveAttribute("aria-current", "page");
  });

  it("a login without case functions sees the neutral not-found text", async () => {
    browserApi({ "GET /me": makeMe(["users.view"], "dept_admin") });
    renderWithClient(
      <AlertsFrame>
        <p>body</p>
      </AlertsFrame>,
    );
    expect(await screen.findByText("The page does not exist, or you cannot see it.")).toBeInTheDocument();
    expect(screen.queryByText("body")).toBeNull();
  });
});

describe("the filter bar on Alerts (portal-filters)", () => {
  it("sends the case filters with the alert filters", async () => {
    const api = browserApi(routes([], { "GET /custody/recipients": { departments: [], items: [], units: [], total: 0 } }));
    renderWithClient(
      <AlertList params={{ status: "all", severity: "high", year: "2025", owner: "EDU", next: "n7", bench: "SAIKIA" }} />,
    );
    await screen.findByText("No alerts match these filters.");
    const url = alertCalls(api.calls).at(-1)!.path;
    for (const part of ["status=all", "severity=high", "year=2025", "owner=EDU", "next_from=", "next_to=", "bench=SAIKIA"]) {
      expect(url).toContain(part);
    }
  });

  it("the case-less line shows only while a case filter is set", async () => {
    browserApi(routes([alert()]));
    const { unmount } = renderWithClient(<AlertList params={{ status: "all", kind: "workflow" }} />);
    await screen.findByText("1 alerts match");
    expect(screen.queryByText("Alerts without a case are hidden while case filters are set.")).toBeNull();
    unmount();
    browserApi(routes([alert()]));
    renderWithClient(<AlertList params={{ case_status: "pending" }} />);
    expect(await screen.findByText("Alerts without a case are hidden while case filters are set.")).toBeInTheDocument();
    expect(screen.getByText("Status: Pending")).toBeInTheDocument();
  });
});

describe("next dates (portal-next-dates, decisions 1 and 14)", () => {
  it("a visible next_date_review alert has Answer it to the review list for its case; others do not", async () => {
    browserApi(
      routes([
        alert({ id: "a-1", kind: "next_date_review", kind_label: "Next date to confirm", title: "Confirm the next date" }),
        alert({ id: "a-2", kind: "next_date_review", kind_label: "Next date to confirm", title: "Hidden case", case_visible: false }),
        alert({ id: "a-3", title: "Hearing in three days" }),
      ]),
    );
    renderWithClient(<AlertList params={{}} />);
    await screen.findByText("Confirm the next date");
    const links = screen.getAllByRole("link", { name: "Answer it" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/alerts/next-dates?q=c1");
    // following it marks the alert read first, then navigates
    await userEvent.click(links[0]!);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/alerts/next-dates?q=c1"));
  });

  it("the frame has the Next dates to confirm tab with next_dates.review", async () => {
    browserApi({ "GET /me": makeMe(["cases.view_scope", "next_dates.review"]) });
    const { unmount } = renderWithClient(
      <AlertsFrame>
        <p>body</p>
      </AlertsFrame>,
    );
    const tabs = await screen.findByRole("navigation", { name: "Alerts sections" });
    expect(within(tabs).getByRole("link", { name: "Next dates to confirm" })).toHaveAttribute("href", "/alerts/next-dates");
    unmount();
    browserApi({ "GET /me": makeMe(["cases.view_scope"]) });
    renderWithClient(
      <AlertsFrame>
        <p>body</p>
      </AlertsFrame>,
    );
    const only = await screen.findByRole("navigation", { name: "Alerts sections" });
    expect(within(only).queryByRole("link", { name: "Next dates to confirm" })).toBeNull();
  });
});
