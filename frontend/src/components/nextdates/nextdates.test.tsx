import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NextDateReviewItem, Permission } from "@/lib/api/types";
import { addDays } from "@/lib/format";
import { todayIst } from "@/lib/workflow";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, renderWithClient, type BrowserCall } from "@/test/render";

import { ReviewList } from "./ReviewList";

const CASE = { id: "c-1", ref_no: "ASLMS/GOA/CASE/2026/000001", cnr: "ASHC010012342026", case_no_text: "WP(C)/1234/2026" };
const CASE_PATH = "/cases/ASLMS-GOA-CASE-2026-000001";
const SOON = addDays(todayIst(), 10);
const LATER = addDays(todayIst(), 20);

function confirmItem(extra: Partial<NextDateReviewItem> = {}): NextDateReviewItem {
  return {
    kind: "confirm",
    id: "nd-1",
    case: CASE,
    order: { id: "o-1", order_no: "4", order_date: "2026-10-12", document_id: "d-1" },
    phrase: "List the matter after 2 (two) weeks.",
    rule: "list_after_period",
    next_date: SOON,
    act_by: "2026-10-20",
    alert_ref_no: "ASLMS/EDU/ALR/2026/000077",
    departments: ["EDU"],
    ...extra,
  };
}

function enterItem(extra: Partial<NextDateReviewItem> = {}): NextDateReviewItem {
  return {
    kind: "enter",
    id: "o-9",
    case: { ...CASE, id: "c-2", ref_no: "ASLMS/GOA/CASE/2026/000002", case_no_text: "WA/55/2026" },
    order: { id: "o-9", order_no: "2", order_date: "2026-10-13", document_id: null },
    phrase: "List after the next date fixed in WP(C)/9/2026.",
    rule: "conflicting_dates",
    next_date: null,
    act_by: "2026-10-21",
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

describe("the review list (portal-next-dates, decision 4)", () => {
  it("asks the API with kind omitted by default and shows both kinds of row", async () => {
    const api = browserApi(routes([confirmItem(), enterItem()]));
    renderWithClient(<ReviewList params={{}} />);
    const table = await screen.findByRole("table", { name: "Next Dates to Confirm" });
    const q = queryOf(reviewCalls(api.calls)[0]!);
    expect(q.has("kind")).toBe(false);
    expect(q.get("limit")).toBe("50");
    expect(q.get("offset")).toBe("0");
    expect(within(table).getByText("Suggested from the order — please confirm")).toBeInTheDocument();
    expect(within(table).getByText("Counted from the order date — the order gives a period, not a date")).toBeInTheDocument();
    expect(within(table).getByText("No date could be read from this order — please enter the next date")).toBeInTheDocument();
    expect(within(table).getByText("“List the matter after 2 (two) weeks.”")).toBeInTheDocument();
    expect(within(table).getByText("Please answer by 20 Oct 2026")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Confirm next date of WP(C)/1234/2026" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Not correct: next date of WP(C)/1234/2026" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Enter date for WA/55/2026" })).toBeInTheDocument();
    expect(screen.getByText("2 items match")).toBeInTheDocument();
    expect(screen.getByText("Only cases your office works on are listed here.")).toBeInTheDocument();
    // never the alert reference, the rule code, or a confidence
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("ALR");
    expect(text).not.toContain("list_after_period");
    expect(text).not.toContain("conflicting_dates");
    expect(text).not.toMatch(/confidence|0\.\d\d/i);
  });

  it("Show and the shared filters go to the query string and to the API", async () => {
    const api = browserApi(routes([]));
    const { unmount } = renderWithClient(<ReviewList params={{}} />);
    expect(await screen.findByText("Nothing to confirm. New orders of your cases are checked every few minutes.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Show"), "confirm");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalled());
    expect(nav.replace.mock.calls.at(-1)![0]).toContain("kind=confirm");
    unmount();
    const api2 = browserApi(routes([]));
    const { unmount: u2 } = renderWithClient(<ReviewList params={{ kind: "enter", q: "WP(C)/1234/2026", owner: "EDU" }} />);
    expect(await screen.findByText("No item matches these filters.")).toBeInTheDocument();
    const q = queryOf(reviewCalls(api2.calls)[0]!);
    expect(q.get("kind")).toBe("enter");
    expect(q.get("q")).toBe("WP(C)/1234/2026");
    expect(q.get("owner")).toBe("EDU");
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    u2();
    const api3 = browserApi(routes([]));
    renderWithClient(<ReviewList params={{ kind: "confirm" }} />);
    await screen.findByText("No item matches these filters.");
    expect(queryOf(reviewCalls(api3.calls)[0]!).get("kind")).toBe("confirm");
  });

  it("says when an order is a scanned copy", async () => {
    browserApi(routes([enterItem({ rule: null, phrase: null })]));
    renderWithClient(<ReviewList params={{}} />);
    expect(
      await screen.findByText("This order is a scanned copy and could not be read — please open it and enter the next date"),
    ).toBeInTheDocument();
  });

  it("View order only with a stored document and documents.view", async () => {
    browserApi(routes([confirmItem(), enterItem()]));
    const { unmount } = renderWithClient(<ReviewList params={{}} />);
    const links = await screen.findAllByRole("link", { name: "View Order" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", `/api/backend${CASE_PATH}/orders/o-1/file?disposition=inline`);
    unmount();
    browserApi(routes([confirmItem()], {}, me(["cases.view_scope", "next_dates.review"])));
    renderWithClient(<ReviewList params={{}} />);
    await screen.findByRole("table", { name: "Next Dates to Confirm" });
    expect(screen.queryByRole("link", { name: "View Order" })).toBeNull();
  });

  it("shows the department only for a login with more than one department", async () => {
    browserApi(routes([enterItem()]));
    const { unmount } = renderWithClient(<ReviewList params={{}} />);
    await screen.findByRole("table", { name: "Next Dates to Confirm" });
    expect(screen.queryByRole("columnheader", { name: "Department" })).toBeNull();
    unmount();
    browserApi(routes([enterItem()], {}, me(READ, ["EDU", "HEALTH"])));
    renderWithClient(<ReviewList params={{}} />);
    expect(await screen.findByRole("columnheader", { name: "Department" })).toBeInTheDocument();
    expect(screen.getByText("EDU, HEALTH")).toBeInTheDocument();
  });
});

describe("the actions (portal-next-dates, decisions 5-7, 9, 16, 17)", () => {
  it("Confirm asks first, posts {} and shows the notice; the list, case and dashboard are read again", async () => {
    const api = browserApi(routes([confirmItem()], { "POST /next-dates/nd-1/confirm": { next_date: SOON } }));
    const { client } = renderWithClient(<ReviewList params={{}} />);
    const spy = vi.spyOn(client, "invalidateQueries");
    await userEvent.click(await screen.findByRole("button", { name: "Confirm next date of WP(C)/1234/2026" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("It will appear in the hearing calendar and the hearing alerts.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/Confirmed\. .* is now the next date of WP\(C\)\/1234\/2026\./));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.path).toBe("/next-dates/nd-1/confirm");
    expect(post.body).toEqual({});
    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(keys).toContain(JSON.stringify(["next-dates"]));
    expect(keys).toContain(JSON.stringify(["dashboard"]));
    expect(keys).toContain(JSON.stringify(["alerts"]));
    expect(keys.some((k) => k.includes(CASE.ref_no) || k.includes("ASLMS-GOA-CASE-2026-000001"))).toBe(true);
  });

  it("Not correct posts only the filled fields and names the entered date", async () => {
    const api = browserApi(
      routes([confirmItem()], {
        "POST /next-dates/nd-1/reject": (c: BrowserCall) =>
          (c.body as { next_date?: string }).next_date
            ? { rejected: {}, entered: { next_date: LATER } }
            : { rejected: {}, entered: null },
      }),
    );
    renderWithClient(<ReviewList params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Not correct: next date of WP(C)/1234/2026" }));
    let dialog = screen.getByRole("dialog");
    const field = within(dialog).getByLabelText("The correct next date (if the order gives one)");
    expect(field).toHaveAttribute("min", todayIst());
    expect(within(dialog).getByText("Shown to everyone who can see the case. Do not write internal remarks.")).toBeInTheDocument();
    await userEvent.type(field, LATER);
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/^Saved\. The next date is now .+\.$/));
    expect(api.calls.filter((c) => c.method === "POST").at(-1)!.body).toEqual({ next_date: LATER });
    // with nothing filled the body is empty
    await userEvent.click(screen.getByRole("button", { name: "Not correct: next date of WP(C)/1234/2026" }));
    dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Reason (Optional)"), "  ");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved. The suggested date will not be used."));
    expect(api.calls.filter((c) => c.method === "POST").at(-1)!.body).toEqual({});
  });

  it("Enter date posts the order the item stands for", async () => {
    const api = browserApi(
      routes([enterItem()], { "POST /cases/ASLMS-GOA-CASE-2026-000002/next-dates": json(201, { next_date: SOON }) }),
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
    expect(post.path).toBe("/cases/ASLMS-GOA-CASE-2026-000002/next-dates");
    expect(post.body).toEqual({ next_date: SOON, note: "As told in court", order: "o-9" });
  });

  it("a refused date, an entered date and a released case are said in words, in the dialog", async () => {
    let answer: Response = json(400, { detail: { code: "bad_field", message: "next_date is at most 548 days ahead" } });
    browserApi(routes([enterItem()], { "POST /cases/ASLMS-GOA-CASE-2026-000002/next-dates": () => answer }));
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

  it("not_pending closes the dialog, says so above the list and reads the list again", async () => {
    let items = [confirmItem()];
    const api = browserApi({
      "GET /me": me(),
      "GET /next-dates/review": () => ({ items, total: items.length }),
      "POST /next-dates/nd-1/confirm": () => {
        items = [];
        return conflict("not_pending");
      },
    });
    renderWithClient(<ReviewList params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm next date of WP(C)/1234/2026" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }));
    expect(
      await screen.findByText("This date has already been answered or replaced by a newer order. The list has been read again."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(reviewCalls(api.calls).length).toBeGreaterThan(1));
    expect(await screen.findByText(/Nothing to confirm/)).toBeInTheDocument();
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("ReviewList renders a DataTable with a primary cell", async () => {
    browserApi(routes([confirmItem(), enterItem()]));
    renderWithClient(<ReviewList params={{}} />);
    expectDataTable(await screen.findByRole("table", { name: "Next Dates to Confirm" }));
  });
});
