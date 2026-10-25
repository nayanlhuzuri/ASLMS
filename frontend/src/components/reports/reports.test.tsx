import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Sidebar } from "@/components/shell/PortalShell";
import type { Me, Permission, Report, ReportCatalogue, ReportSection } from "@/lib/api/types";
import { istDay } from "@/lib/format";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, labels, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { ReportPage } from "./ReportPage";
import { ReportsFrame, ReportsIndex } from "./ReportsFrame";

const ALL = ["pending-cases", "hearings-disposals", "pending-actions", "data-health"];

function catalogue(state: boolean, codes: string[] = ["EDU"]): ReportCatalogue {
  const departments = state
    ? [
        { code: "EDU", name: "Education", is_active: true },
        { code: "FIN", name: "Finance", is_active: false },
        { code: "HEALTH", name: "Health", is_active: true },
      ]
    : codes.map((code) => ({ code, name: code === "EDU" ? "Education" : "Health", is_active: true }));
  const list = departments.map((d) => d.code);
  return {
    reports: ALL.filter((k) => state || k !== "data-health").map((key) => ({
      key,
      title: key,
      params: [],
      scopes: state ? (key === "data-health" ? ["state"] : ["state", "department"]) : ["department"],
      departments: key === "data-health" ? [] : list,
    })),
    departments,
  };
}

function section(extra: Partial<ReportSection> = {}): ReportSection {
  return {
    key: "by_group",
    title: "By department",
    columns: [
      { key: "group_code", label: "Department code", kind: "text" },
      { key: "group", label: "Department", kind: "text" },
      { key: "total", label: "Active cases", kind: "int" },
      { key: "oldest", label: "Oldest listing", kind: "date" },
      { key: "age", label: "Days pending", kind: "days" },
      { key: "brand_new", label: "A column the portal does not know", kind: "text" },
    ],
    rows: [
      { group_code: "EDU", group: "Education", total: 128400, oldest: "2026-10-01", age: 12, brand_new: "server-only" },
      { group_code: "HEALTH", group: null, total: 3, oldest: null, age: null, brand_new: "" },
    ],
    totals: { group_code: null, group: "Total", total: 128403, oldest: null, age: null, brand_new: null },
    note: "Counted for the current owner.",
    total_rows: 2,
    truncated: false,
    ...extra,
  };
}

function report(key: string, extra: Partial<Report> = {}): Report {
  return {
    key,
    title: "Pending cases by department, court and age",
    scope: "state",
    department_code: null,
    params: { department: null },
    generated_at: "2026-10-14T05:00:00Z",
    generated_by: { name: "Anita Sharma", designation: "Under Secretary", office_code: "GOA" },
    as_of_note: "Counts as they stand today.",
    sections: [section()],
    ...extra,
  };
}

function stateMe(extra: Partial<Me> = {}): Me {
  return makeMe(["reports.state", "cases.view_all"], "state_oversight", extra);
}

const deptMe = () => makeMe(["reports.department", "cases.view_scope"], "dept_admin");

function reportCalls(api: { calls: { path: string }[] }) {
  return api.calls.filter((c) => c.path.startsWith("/reports/"));
}

beforeEach(() => {
  resetNav("/reports/pending-cases");
});

describe("navigation", () => {
  it("the Reports entry shows with reports.department or reports.state and not without", () => {
    for (const fns of [["reports.department"], ["reports.state"]] as Permission[][]) {
      browserApi({ "GET /reference/labels": labels() });
      const { unmount } = renderWithClient(<Sidebar me={makeMe(fns)} />);
      const main = screen.getByRole("navigation", { name: "Main navigation" });
      expect(within(main).getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports");
      unmount();
    }
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(["cases.view_scope"])} />);
    const main = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(main).queryByRole("link", { name: "Reports" })).toBeNull();
  });
});

describe("tabs follow the catalogue", () => {
  it("a State reader gets four tabs, a department reader three", async () => {
    browserApi({ "GET /reports": catalogue(true) });
    const { unmount } = renderWithClient(<ReportsFrame>body</ReportsFrame>);
    const tabs = await screen.findByRole("navigation", { name: "Reports sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Pending cases",
      "Hearings and disposals",
      "Pending actions",
      "Data collection health",
    ]);
    expect(within(tabs).getByRole("link", { name: "Pending cases" })).toHaveAttribute("aria-current", "page");
    unmount();
    browserApi({ "GET /reports": catalogue(false) });
    renderWithClient(<ReportsFrame>body</ReportsFrame>);
    const three = await screen.findByRole("navigation", { name: "Reports sections" });
    expect(within(three).getAllByRole("link")).toHaveLength(3);
    expect(within(three).queryByRole("link", { name: "Data collection health" })).toBeNull();
  });

  it("/reports opens the first tab", async () => {
    resetNav("/reports");
    browserApi({ "GET /reports": catalogue(false) });
    renderWithClient(<ReportsIndex />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/reports/pending-cases"));
  });

  it("a path not in the catalogue says it is not available and makes no report request", async () => {
    resetNav("/reports/data-health");
    const api = browserApi({ "GET /me": deptMe(), "GET /reports": catalogue(false) });
    renderWithClient(<ReportPage reportKey="data-health" params={{}} />);
    expect(await screen.findByText("This report is not available to you.")).toBeInTheDocument();
    expect(reportCalls(api)).toHaveLength(0);
  });

  it("without a reports function the frame says so and renders nothing else", async () => {
    resetNav("/reports");
    const api = browserApi({ "GET /reports": json(403, { detail: { code: "forbidden", message: "no" } }) });
    renderWithClient(<ReportsFrame>body</ReportsFrame>);
    expect(await screen.findByText("This report is not available to you.")).toBeInTheDocument();
    expect(screen.queryByText("body")).toBeNull();
    expect(reportCalls(api)).toHaveLength(0);
  });
});

describe("scope", () => {
  it("a department-only reader gets their first department written to the URL", async () => {
    const api = browserApi({ "GET /me": deptMe(), "GET /reports": catalogue(false, ["EDU", "HEALTH"]) });
    renderWithClient(<ReportPage reportKey="pending-cases" params={{}} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/reports/pending-cases?department=EDU"));
    expect(reportCalls(api)).toHaveLength(0);
  });

  it("a single department shows as text", async () => {
    browserApi({
      "GET /me": deptMe(),
      "GET /reports": catalogue(false),
      "GET /reports/pending-cases": report("pending-cases", { scope: "department", department_code: "EDU" }),
    });
    renderWithClient(<ReportPage reportKey="pending-cases" params={{ department: "EDU" }} />);
    expect(await screen.findByText("Department: Education (EDU)")).toBeInTheDocument();
    expect(screen.queryByLabelText("Department")).toBeNull();
    expect(await screen.findByText("Scope: Education (EDU)")).toBeInTheDocument();
  });

  it("a State reader defaults to Whole State and may pick an inactive department by name", async () => {
    const api = browserApi({
      "GET /me": stateMe(),
      "GET /reports": catalogue(true),
      "GET /reports/pending-cases": report("pending-cases"),
    });
    renderWithClient(<ReportPage reportKey="pending-cases" params={{}} />);
    const scope = await screen.findByLabelText("Scope");
    expect(scope).toHaveValue("");
    expect(within(scope).getByRole("option", { name: "Whole State" })).toBeInTheDocument();
    expect(within(scope).getByRole("option", { name: "Finance (FIN) — inactive" })).toBeInTheDocument();
    expect(await screen.findByText("Scope: Whole State")).toBeInTheDocument();
    expect(reportCalls(api).map((c) => c.path)).toEqual(["/reports/pending-cases"]);
    await userEvent.selectOptions(scope, "FIN");
    await userEvent.click(screen.getByRole("button", { name: "Show report" }));
    expect(nav.push).toHaveBeenCalledWith("/reports/pending-cases?department=FIN");
  });
});

describe("sections render from columns", () => {
  it("caption, headers, number and date formatting, null as a dash, totals in tfoot, note, truncated and empty", async () => {
    browserApi({
      "GET /me": stateMe(),
      "GET /reports": catalogue(true),
      "GET /reports/pending-cases": report("pending-cases", {
        sections: [
          section({ truncated: true, total_rows: 9 }),
          section({ key: "empty", title: "By court", rows: [], totals: null, note: null }),
        ],
      }),
    });
    renderWithClient(<ReportPage reportKey="pending-cases" params={{}} />);
    const table = await screen.findByRole("table", { name: "By department" });
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Department code",
      "Department",
      "Active cases",
      "Oldest listing",
      "Days pending",
      "A column the portal does not know",
    ]);
    expect(within(table).getByText("1,28,400")).toBeInTheDocument();
    expect(within(table).getByText("1 Oct 2026")).toBeInTheDocument();
    expect(within(table).getByText("server-only")).toBeInTheDocument();
    expect(within(table).getAllByText("—").length).toBeGreaterThanOrEqual(3);
    const foot = table.querySelector("tfoot")!;
    expect(within(foot).getByText("Total")).toBeInTheDocument();
    expect(within(foot).getByText("1,28,403")).toBeInTheDocument();
    expect(screen.getByText("Counted for the current owner.")).toBeInTheDocument();
    expect(screen.getByText("First 2 of 9 rows; narrow the report to see the rest.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "By department" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("heading", { name: "By court" })).toBeInTheDocument();
    expect(screen.getByText("Nothing to report for these parameters.")).toBeInTheDocument();
    expect(screen.getByText("Counts as they stand today.")).toBeInTheDocument();
    expect(screen.getByText("Generated by Anita Sharma, Under Secretary, GOA")).toBeInTheDocument();
  });

  it("case rows link to the case page and are paged by 50", async () => {
    resetNav("/reports/pending-actions", "include_cases=true");
    const rows = Array.from({ length: 60 }, (_, i) => ({
      case_no: `WP(C)/${i + 1}/2026`,
      cnr: null,
      ref_no: `EDU/2026/${String(i + 1).padStart(4, "0")}`,
      holder_office_code: "EDU",
      due_date: null,
      overdue_days: 0,
    }));
    const api = browserApi({
      "GET /me": stateMe(),
      "GET /reports": catalogue(true),
      "GET /custody/recipients": { departments: [], items: [], total: 0 },
      "GET /reports/pending-actions": report("pending-actions", {
        params: { department: null, holder_department: null, include_cases: true },
        sections: [
          {
            key: "files",
            title: "Cases with a pending action",
            columns: [
              { key: "case_no", label: "Case number", kind: "text" },
              { key: "holder_office_code", label: "Holder office", kind: "text" },
              { key: "due_date", label: "Due", kind: "date" },
              { key: "overdue_days", label: "Days overdue", kind: "days" },
            ],
            rows,
            totals: null,
            note: "Only cases you may open are listed.",
            total_rows: 60,
            truncated: false,
          },
        ],
      }),
    });
    renderWithClient(<ReportPage reportKey="pending-actions" params={{ include_cases: "true" }} />);
    const table = await screen.findByRole("table", { name: "Cases with a pending action" });
    expect(within(table).getByRole("link", { name: "WP(C)/1/2026" })).toHaveAttribute("href", "/cases/EDU-2026-0001");
    expect(within(table).getAllByRole("link")).toHaveLength(50);
    expect(screen.getByText("with the case list")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(within(table).getAllByRole("link")).toHaveLength(10);
    expect(within(table).getByRole("link", { name: "WP(C)/60/2026" })).toBeInTheDocument();
    expect(reportCalls(api).map((c) => c.path)).toEqual(["/reports/pending-actions?include_cases=true"]);
  });
});

describe("downloads", () => {
  it("carry the shown parameters and appear only after the report loaded", async () => {
    let release: (v: unknown) => void = () => undefined;
    const pending = new Promise((r) => (release = r));
    browserApi({
      "GET /me": stateMe(),
      "GET /reports": catalogue(true),
      "GET /reports/pending-cases": async () => {
        await pending;
        return report("pending-cases", { scope: "department", department_code: "EDU" });
      },
    });
    renderWithClient(<ReportPage reportKey="pending-cases" params={{ department: "EDU" }} />);
    expect(await screen.findByText("Preparing the report…")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download Excel" })).toBeNull();
    release(undefined);
    const xlsx = await screen.findByRole("link", { name: "Download Excel" });
    expect(xlsx).toHaveAttribute("href", "/api/backend/reports/pending-cases?department=EDU&format=xlsx");
    expect(xlsx).toHaveAttribute("download");
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "/api/backend/reports/pending-cases?department=EDU&format=pdf",
    );
    expect(screen.getByText(/Downloads are recorded in the audit log\./)).toBeInTheDocument();
  });

  it("a bad period shows the API message under the period fields and no download", async () => {
    resetNav("/reports/hearings-disposals", "from=2024-01-01&to=2026-01-01");
    browserApi({
      "GET /me": stateMe(),
      "GET /reports": catalogue(true),
      "GET /reports/hearings-disposals": json(422, { detail: { code: "bad_period", message: "the period is at most 366 days" } }),
    });
    renderWithClient(<ReportPage reportKey="hearings-disposals" params={{ from: "2024-01-01", to: "2026-01-01" }} />);
    const message = await screen.findByText("the period is at most 366 days");
    expect(message).toHaveAttribute("role", "alert");
    expect(screen.getByLabelText("To")).toHaveAttribute("aria-describedby", expect.stringContaining(message.id));
    expect(screen.queryByRole("link", { name: "Download Excel" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("a 503 shows the message with Try again and no download", async () => {
    let calls = 0;
    browserApi({
      "GET /me": stateMe(),
      "GET /reports": catalogue(true),
      "GET /reports/pending-cases": () => {
        calls += 1;
        return calls === 1
          ? json(503, { detail: { code: "report_timeout", message: "the report took too long" } })
          : report("pending-cases");
      },
    });
    renderWithClient(<ReportPage reportKey="pending-cases" params={{}} />);
    expect(
      await screen.findByText("The report took too long. Choose a shorter period or one department."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download Excel" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Download Excel" })).toBeInTheDocument();
  });
});

describe("the period", () => {
  it("hearings and disposals open on this month; Last month writes its dates", async () => {
    resetNav("/reports/hearings-disposals");
    const today = istDay();
    const api = browserApi({
      "GET /me": stateMe(),
      "GET /reports": catalogue(true),
      "GET /reports/hearings-disposals": report("hearings-disposals"),
    });
    renderWithClient(<ReportPage reportKey="hearings-disposals" params={{}} />);
    const period = await screen.findByLabelText("Period");
    expect(period).toHaveValue("this_month");
    await waitFor(() =>
      expect(reportCalls(api)[0]!.path).toBe(`/reports/hearings-disposals?from=${today.slice(0, 7)}-01&to=${today}`),
    );
    await userEvent.selectOptions(period, "last_month");
    await userEvent.click(screen.getByRole("button", { name: "Show report" }));
    expect(nav.push.mock.calls[0]![0]).toMatch(/^\/reports\/hearings-disposals\?from=\d{4}-\d{2}-01&to=\d{4}-\d{2}-\d{2}$/);
  });

  it("Choose dates checks the order in the browser and sends nothing for a bad pair", async () => {
    resetNav("/reports/data-health");
    browserApi({ "GET /me": stateMe(), "GET /reports": catalogue(true), "GET /reports/data-health": report("data-health") });
    renderWithClient(<ReportPage reportKey="data-health" params={{}} />);
    const period = await screen.findByLabelText("Period");
    expect(period).toHaveValue("last_7");
    expect(screen.queryByLabelText("Scope")).toBeNull();
    await userEvent.selectOptions(period, "custom");
    await userEvent.type(screen.getByLabelText("From"), "2026-10-05");
    await userEvent.type(screen.getByLabelText("To"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Show report" }));
    expect(await screen.findByText("The end date is before the start date.")).toBeInTheDocument();
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("the data-health report links to Live health", async () => {
    resetNav("/reports/data-health");
    browserApi({ "GET /me": stateMe(), "GET /reports": catalogue(true), "GET /reports/data-health": report("data-health") });
    renderWithClient(<ReportPage reportKey="data-health" params={{}} />);
    expect(await screen.findByRole("link", { name: "Live health" })).toHaveAttribute("href", "/data/health");
  });
});

describe("pending actions", () => {
  it("holder department lists all active departments and says it does not narrow compliance", async () => {
    resetNav("/reports/pending-actions");
    browserApi({
      "GET /me": deptMe(),
      "GET /reports": catalogue(false),
      "GET /custody/recipients": {
        departments: [
          { code: "EDU", name: "Education" },
          { code: "HEALTH", name: "Health" },
          { code: "PWD", name: "Public Works" },
        ],
        items: [],
        total: 0,
      },
      "GET /reports/pending-actions": report("pending-actions", { scope: "department", department_code: "EDU" }),
    });
    renderWithClient(<ReportPage reportKey="pending-actions" params={{ department: "EDU" }} />);
    const holder = await screen.findByLabelText("Holder department");
    await waitFor(() => expect(within(holder).getAllByRole("option")).toHaveLength(4));
    expect(within(holder).getByRole("option", { name: "All holders" })).toBeInTheDocument();
    expect(within(holder).getByRole("option", { name: "Public Works (PWD)" })).toBeInTheDocument();
    expect(screen.getByText(/overdue compliance is always by the office addressed/)).toBeInTheDocument();
    await userEvent.selectOptions(holder, "HEALTH");
    await userEvent.click(screen.getByRole("checkbox", { name: "List the cases" }));
    await userEvent.click(screen.getByRole("button", { name: "Show report" }));
    expect(nav.push).toHaveBeenCalledWith(
      "/reports/pending-actions?department=EDU&holder_department=HEALTH&include_cases=true",
    );
  });

  it("the Pending action link to the Cases list shows only to a tracker (case-workspace-admin, decision 21)", async () => {
    resetNav("/reports/pending-actions");
    const routes = {
      "GET /reports": catalogue(false),
      "GET /custody/recipients": { departments: [], items: [], total: 0 },
      "GET /reports/pending-actions": report("pending-actions", { scope: "department", department_code: "EDU" }),
    };
    browserApi({ ...routes, "GET /me": deptMe() });
    const { unmount } = renderWithClient(<ReportPage reportKey="pending-actions" params={{ department: "EDU" }} />);
    await screen.findByRole("link", { name: "Download Excel" });
    expect(screen.queryByRole("link", { name: "Pending action" })).toBeNull();
    unmount();
    const tracker = deptMe();
    tracker.memberships = (tracker.memberships ?? []).map((m) => ({ ...m, functions: ["custody.track", "reports.department"] }));
    browserApi({ ...routes, "GET /me": tracker });
    renderWithClient(<ReportPage reportKey="pending-actions" params={{ department: "EDU" }} />);
    expect(await screen.findByRole("link", { name: "Pending action" })).toHaveAttribute("href", "/cases/pending");
  });
});

describe("the Report template (design portal-ui-redesign, decision 26)", () => {
  it("the choices sit on top, the downloads in the header's secondary actions, disabled until the report loads", async () => {
    let release: (v: unknown) => void = () => undefined;
    const pending = new Promise((r) => (release = r));
    browserApi({
      "GET /me": stateMe(),
      "GET /reports": catalogue(true),
      "GET /reports/pending-cases": async () => {
        await pending;
        return report("pending-cases");
      },
    });
    const { container } = renderWithClient(
      <ReportsFrame>
        <ReportPage reportKey="pending-cases" params={{}} />
      </ReportsFrame>,
    );
    const group = await screen.findByRole("group", { name: "Downloads" });
    const header = group.closest("header")!;
    expect(within(header).getByRole("heading", { level: 1, name: "Reports" })).toBeInTheDocument();
    // before the report: the two buttons are there but disabled, and no link is offered
    expect(within(group).getByRole("button", { name: "Download Excel" })).toBeDisabled();
    expect(within(group).getByRole("button", { name: "Download PDF" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "Download Excel" })).toBeNull();
    // the form comes before the results
    const form = screen.getByRole("form", { name: "Report choices" });
    release(undefined);
    const xlsx = await within(group).findByRole("link", { name: "Download Excel" });
    expect(xlsx).toHaveAttribute("href", "/api/backend/reports/pending-cases?format=xlsx");
    expect(xlsx.className).not.toMatch(/primary/);
    expect(screen.getAllByRole("link", { name: "Download Excel" })).toHaveLength(1);
    const title = screen.getByRole("heading", { level: 2, name: "Pending cases by department, court and age" });
    expect(form.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // one primary on the page: Show report
    expect(primaryActions(container)).toEqual(["Show report"]);
  });

  it("a reader without reports sees no download buttons", async () => {
    browserApi({ "GET /reports": json(403, { detail: { code: "forbidden", message: "no" } }) });
    renderWithClient(<ReportsFrame>body</ReportsFrame>);
    expect(await screen.findByText("This report is not available to you.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Downloads" })).toBeNull();
  });
});

describe("the data-health call figures (court-data-freshness, decision 20)", () => {
  it("says calls are kept for 2 years when the period starts before the oldest kept day, and not otherwise", async () => {
    const { ReportView } = await import("./ReportView");
    const health = (from: string) =>
      report("data-health", {
        title: "Data collection health",
        params: { department: null, from, to: "2026-10-14" },
        meta: { calls_kept_from: "2024-10-14", calls_kept_days: 730 },
      });
    const { unmount } = renderWithClient(<ReportView report={health("2024-09-01")} departments={[]} />);
    expect(screen.getByText("Calls are kept for 2 years; earlier days show no call figures.")).toBeInTheDocument();
    unmount();
    renderWithClient(<ReportView report={health("2026-10-01")} departments={[]} />);
    expect(screen.queryByText(/Calls are kept for/)).toBeNull();
  });
});
