import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { NextDateReviewItem, Permission } from "@/lib/api/types";
import { addDays } from "@/lib/format";
import { todayIst } from "@/lib/workflow";
import { resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, renderWithClient, type BrowserCall } from "@/test/render";

import { ReviewList } from "./ReviewList";

const CASE = { id: "c-1", ref_no: "ASLMS/GHC/CASE/2026/000001", cnr: "ASHC010012342026", case_no_text: "WP(C)/1234/2026" };
const CASE_PATH = "/cases/ASLMS-GHC-CASE-2026-000001";
const SOON = addDays(todayIst(), 10);

/** An order with no clear date on a case with a stored order (design next-date-direct, decision 9). */
function unclearItem(extra: Partial<NextDateReviewItem> = {}): NextDateReviewItem {
  return {
    kind: "enter",
    id: "o-1",
    case: CASE,
    order: { id: "o-1", order_no: "4", order_date: "2026-10-12", document_id: "d-1" },
    phrase: "List the matter after the ensuing vacation.",
    rule: "no_countable_date",
    next_date: null,
    act_by: "2026-10-20",
    reason: "unclear",
    alert_ref_no: "ASLMS/EDU/ALR/2026/000077",
    departments: ["EDU"],
    ...extra,
  };
}

function enterItem(extra: Partial<NextDateReviewItem> = {}): NextDateReviewItem {
  return {
    kind: "enter",
    id: "o-9",
    case: { ...CASE, id: "c-2", ref_no: "ASLMS/GHC/CASE/2026/000002", case_no_text: "WA/55/2026" },
    order: { id: "o-9", order_no: "2", order_date: "2026-10-13", document_id: null },
    phrase: "List after the next date fixed in WP(C)/9/2026.",
    rule: "conflicting_dates",
    next_date: null,
    act_by: "2026-10-21",
    reason: "none",
    alert_ref_no: null,
    departments: ["EDU", "HEALTH"],
    ...extra,
  };
}

const READ: Permission[] = ["cases.view_scope", "next_dates.review", "documents.view"];

function me(functions: Permission[] = READ, departments: string[] = ["EDU"]) {
  return makeMe(functions, "dept_admin", {
    memberships: departments.map((code, i) => ({
      id: `m-${i}`,
      office: { code, name: code, kind: "department" },
      department_code: code,
      designation: null,
      role: "dept_admin",
      is_primary: i === 0,
      is_active: true,
      functions,
    })),
  });
}

function routes(items: NextDateReviewItem[], extra: Record<string, unknown> = {}, who = me()) {
  return {
    "GET /me": who,
    "GET /next-dates/review": { items, total: items.length },
    ...extra,
  };
}

function reviewCalls(calls: BrowserCall[]) {
  return calls.filter((c) => c.method === "GET" && c.path.startsWith("/next-dates/review"));
}

function queryOf(call: BrowserCall): URLSearchParams {
  return new URLSearchParams(call.path.split("?")[1] ?? "");
}

function conflict(code: string) {
  return json(409, { detail: { code, message: `server says ${code}` } });
}

beforeEach(() => {
  resetNav("/alerts/next-dates");
});

describe("Next Dates to Enter (portal-next-dates, decision 4; next-date-direct, decision 9)", () => {
  it("lists enter items only, each with why the order asks for a date, and no Confirm or Not Correct", async () => {
    const api = browserApi(routes([unclearItem(), enterItem()]));
    renderWithClient(<ReviewList params={{}} />);
    const table = await screen.findByRole("table", { name: "Next Dates to Enter" });
    const q = queryOf(reviewCalls(api.calls)[0]!);
    expect(q.has("kind")).toBe(false);
    expect(q.get("limit")).toBe("50");
    expect(q.get("offset")).toBe("0");
    expect(within(table).getByText("The order gives no clear date")).toBeInTheDocument();
    expect(within(table).getByText("The order gives no next date")).toBeInTheDocument();
    expect(within(table).getByText("“List the matter after the ensuing vacation.”")).toBeInTheDocument();
    expect(within(table).getByText("Please answer by 20 Oct 2026")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Enter date for WP(C)/1234/2026" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Enter date for WA/55/2026" })).toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: /Confirm|Not correct/ })).toBeNull();
    expect(screen.queryByLabelText("Show")).toBeNull();
    expect(screen.getByText("2 items match")).toBeInTheDocument();
    expect(screen.getByText("Only cases your office works on are listed here.")).toBeInTheDocument();
    // never the alert reference, the rule code, or a confidence
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("ALR");
    expect(text).not.toContain("no_countable_date");
    expect(text).not.toMatch(/confidence|0\.\d\d/i);
  });

  it("the shared filters go to the query string and to the API", async () => {
    const api = browserApi(routes([]));
    const { unmount } = renderWithClient(<ReviewList params={{}} />);
    expect(await screen.findByText("Nothing to enter. New orders of your cases are checked every few minutes.")).toBeInTheDocument();
    unmount();
    const api2 = browserApi(routes([]));
    renderWithClient(<ReviewList params={{ q: "WP(C)/1234/2026", owner: "EDU" }} />);
    expect(await screen.findByText("No item matches these filters.")).toBeInTheDocument();
    const q = queryOf(reviewCalls(api2.calls)[0]!);
    expect(q.get("q")).toBe("WP(C)/1234/2026");
    expect(q.get("owner")).toBe("EDU");
    expect(q.has("kind")).toBe(false);
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("names each reason, the scanned copy and a date marked wrong", async () => {
    browserApi(
      routes([
        enterItem({ id: "o-2", reason: "no_text", rule: null, phrase: null }),
        enterItem({ id: "o-3", reason: "marked_wrong", case: { ...CASE, id: "c-3", case_no_text: "WA/3/2026" } }),
        enterItem({ id: "o-4", reason: null, rule: null, phrase: null, case: { ...CASE, id: "c-4", case_no_text: "WA/4/2026" } }),
      ]),
    );
    renderWithClient(<ReviewList params={{}} />);
    expect(await screen.findAllByText("This order is a scanned copy and could not be read")).toHaveLength(2);
    expect(screen.getByText("The date read from this order was marked wrong")).toBeInTheDocument();
  });

  it("View order only with a stored document and documents.view", async () => {
    browserApi(routes([unclearItem(), enterItem()]));
    const { unmount } = renderWithClient(<ReviewList params={{}} />);
    const links = await screen.findAllByRole("link", { name: "View Order" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", `/api/backend${CASE_PATH}/orders/o-1/file?disposition=inline`);
    unmount();
    browserApi(routes([unclearItem()], {}, me(["cases.view_scope", "next_dates.review"])));
    renderWithClient(<ReviewList params={{}} />);
    await screen.findByRole("table", { name: "Next Dates to Enter" });
    expect(screen.queryByRole("link", { name: "View Order" })).toBeNull();
  });

  it("shows the department only for a login with more than one department", async () => {
    browserApi(routes([enterItem()]));
    const { unmount } = renderWithClient(<ReviewList params={{}} />);
    await screen.findByRole("table", { name: "Next Dates to Enter" });
    expect(screen.queryByRole("columnheader", { name: "Department" })).toBeNull();
    unmount();
    browserApi(routes([enterItem()], {}, me(READ, ["EDU", "HEALTH"])));
    renderWithClient(<ReviewList params={{}} />);
    expect(await screen.findByRole("columnheader", { name: "Department" })).toBeInTheDocument();
    expect(screen.getByText("EDU, HEALTH")).toBeInTheDocument();
  });
});

describe("Enter Date (portal-next-dates, decisions 7, 9, 16, 17)", () => {
  it("Enter date posts the order the item stands for", async () => {
    const api = browserApi(
      routes([enterItem()], { "POST /cases/ASLMS-GHC-CASE-2026-000002/next-dates": json(201, { next_date: SOON }) }),
    );
    renderWithClient(<ReviewList params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Enter date for WA/55/2026" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/until a newer order of the case arrives/)).toBeInTheDocument();
    // the date is required
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Choose the next date.")).toBeInTheDocument();
    const field = within(dialog).getByLabelText("Next Date");
    expect(field).toHaveAttribute("min", todayIst());
    await userEvent.type(field, SOON);
    await userEvent.type(within(dialog).getByLabelText("Note (Optional)"), "As told in court");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/is the next date of WA\/55\/2026\./));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.path).toBe("/cases/ASLMS-GHC-CASE-2026-000002/next-dates");
    expect(post.body).toEqual({ next_date: SOON, note: "As told in court", order: "o-9" });
  });

  it("a refused date, an entered date and a released case are said in words, in the dialog", async () => {
    let answer: Response = json(400, { detail: { code: "bad_field", message: "next_date is at most 548 days ahead" } });
    browserApi(routes([enterItem()], { "POST /cases/ASLMS-GHC-CASE-2026-000002/next-dates": () => answer }));
    renderWithClient(<ReviewList params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Enter date for WA/55/2026" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Next Date"), SOON);
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("The date must be today or later, and not more than about 18 months ahead."),
    ).toBeInTheDocument();
    answer = conflict("already_entered");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("This date is already entered for the case.")).toBeInTheDocument();
    answer = conflict("not_owned");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("The case is no longer claimed by a department, so its next dates cannot be changed."),
    ).toBeInTheDocument();
  });

  it("a court-given date refused by the server is said in words", async () => {
    browserApi(routes([enterItem()], { "POST /cases/ASLMS-GHC-CASE-2026-000002/next-dates": conflict("court_date_fixed") }));
    renderWithClient(<ReviewList params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Enter date for WA/55/2026" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Next Date"), SOON);
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("The court has given the next date for this case, so it cannot be changed."),
    ).toBeInTheDocument();
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("ReviewList renders a DataTable with a primary cell", async () => {
    browserApi(routes([unclearItem(), enterItem()]));
    renderWithClient(<ReviewList params={{}} />);
    expectDataTable(await screen.findByRole("table", { name: "Next Dates to Enter" }));
  });
});
