import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CaseSummary, CustodyCard, CustodySummary, HeldItem, Me, Permission, SentItem } from "@/lib/api/types";
import { setFlash } from "@/lib/flash";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, makeMe, renderWithClient } from "@/test/render";

import { FilesFrame, FilesIndex } from "./FilesFrame";
import { Held } from "./Held";
import { Sent } from "./Sent";

const READER: Permission[] = ["cases.view_scope"];

function summary(id: string, caseNo: string, ref = `ASLMS/GOA/CASE/2026/${id}`): CaseSummary {
  return {
    id,
    ref_no: ref,
    cnr: null,
    case_no_text: caseNo,
    is_provisional: false,
    last_listed_on: null,
    last_listing: null,
    next_hearing_date: null,
    petitioner_summary: null,
    respondent_summary: null,
    status: "pending",
  };
}

function card(extra: Partial<CustodyCard> = {}): CustodyCard {
  return {
    can_recall: true,
    can_send: true,
    due_date: "2026-10-10",
    holder_office: { code: "EDU-DSE", name: "Secondary Education" },
    holder_user: { id: "u-7", full_name: "Officer One", designation: "Section Officer" },
    leg_seq_no: 2,
    overdue: true,
    overdue_days: 3,
    pending_action: "parawise_comments",
    pending_action_label: "Parawise comments",
    reason: "sent",
    remark: "please comment",
    sent_by: { name: "Edu Admin", designation: "Joint Secretary", office_code: "EDU" },
    since: "2026-10-01T10:00:00Z",
    ...extra,
  };
}

function held(items: HeldItem[]) {
  return { items, total: items.length };
}

function sentItem(id: string, caseNo: string, visible: boolean, remark: string | null = "over to you"): SentItem {
  return {
    case: summary(id, caseNo),
    visible,
    leg: {
      seq_no: 2,
      holder_office: { code: "HEALTH", name: "Health" },
      holder_user: { id: "u-h1", full_name: "Health Off" },
      holder_designation: "Under Secretary",
      reason: "sent",
      reason_label: "Sent",
      pending_action: "examine",
      pending_action_label: "Examine",
      due_date: "2026-11-01",
      remark,
      started_at: "2026-10-13T10:00:00Z",
      actor_name: "Anita Sharma",
      actor_designation: "Under Secretary",
      actor_office_code: "EDU",
    },
  };
}

function tracker(): Me {
  return makeMe(["cases.view_scope", "custody.track"], "dept_admin", {
    memberships: [
      {
        id: "m-1",
        office: { code: "EDU", name: "Education", kind: "department" },
        department_code: "EDU",
        designation: "Joint Secretary",
        role: "dept_admin",
        is_primary: true,
        is_active: true,
        functions: ["cases.view_scope", "custody.track"],
      },
    ],
  });
}

const SUMMARY: CustodySummary = {
  departments: [
    {
      code: "EDU",
      held: 5,
      due_soon: 2,
      overdue: 1,
      by_holder_department: [{ code: "HEALTH", held: 2, due_soon: 1, overdue: 0 }],
      by_holder: [{ office_code: "HEALTH", user_name: "Health Off", designation: "Under Secretary", held: 2, due_soon: 1, overdue: 0 }],
    },
    {
      code: "FIN",
      held: 1,
      due_soon: 0,
      overdue: 0,
      by_holder_department: [],
      by_holder: [],
    },
  ],
};

const DEPTS = { departments: [{ code: "EDU", name: "Education" }, { code: "HEALTH", name: "Health" }], items: [], units: [], total: 2 };

beforeEach(() => {
  resetNav("/files/mine");
  sessionStorage.clear();
});

describe("Files lists (portal-files-alerts, decision 12)", () => {
  it("each tab calls /custody/held with its scope", async () => {
    for (const [scope, path] of [
      ["me", "/files/mine"],
      ["office", "/files/offices"],
    ] as const) {
      resetNav(path);
      const api = browserApi({ "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card() }]) });
      const { unmount } = renderWithClient(<Held scope={scope} params={{}} />);
      expect(await screen.findByRole("link", { name: "WP(C)/1/2026" })).toHaveAttribute("href", "/cases/ASLMS-GOA-CASE-2026-c1");
      const call = api.calls.find((c) => c.path.startsWith("/custody/held"))!;
      expect(call.path).toContain(`scope=${scope}`);
      expect(call.path).not.toContain("overdue");
      unmount();
    }
  });

  it("With me shows the card's facts with the overdue badge; My offices adds the holder", async () => {
    browserApi({ "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card() }]) });
    const { unmount } = renderWithClient(<Held scope="me" params={{}} />);
    const table = await screen.findByRole("table", { name: "Files with me" });
    expect(within(table).getByText("Parawise comments")).toBeInTheDocument();
    expect(within(table).getByText("Overdue by 3 days")).toBeInTheDocument();
    expect(within(table).getByText("Edu Admin, Joint Secretary")).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "Held by" })).toBeNull();
    unmount();
    browserApi({ "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card() }]) });
    renderWithClient(<Held scope="office" params={{}} />);
    const offices = await screen.findByRole("table", { name: "Files with my offices" });
    expect(within(offices).getByRole("columnheader", { name: "Held by" })).toBeInTheDocument();
    expect(within(offices).getByText("Officer One, Section Officer")).toBeInTheDocument();
  });

  it("Overdue only goes to the query string and to the API as overdue=true", async () => {
    const api = browserApi({ "GET /custody/held": held([]) });
    const { unmount } = renderWithClient(<Held scope="me" params={{}} />);
    expect(await screen.findByText("No file is with you.")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Overdue only"));
    expect(nav.replace).toHaveBeenCalledWith("/files/mine?overdue=true");
    unmount();
    renderWithClient(<Held scope="me" params={{ overdue: "true" }} />);
    await waitFor(() => expect(api.calls.some((c) => c.path.includes("overdue=true"))).toBe(true));
  });

  it("Department files shows the summary per department and sends holder_department", async () => {
    resetNav("/files/department");
    const api = browserApi({
      "GET /custody/held": held([]),
      "GET /custody/summary": SUMMARY,
      "GET /custody/recipients": DEPTS,
    });
    const { unmount } = renderWithClient(<Held scope="owned" params={{}} />);
    const edu = await screen.findByRole("region", { name: "Tracking summary: EDU" });
    expect(within(edu).getByRole("table", { name: "By holder department" })).toBeInTheDocument();
    expect(within(edu).getByRole("table", { name: "By holder" })).toBeInTheDocument();
    expect(within(edu).getByText("Health Off")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Tracking summary: FIN" })).toBeInTheDocument();
    expect(await screen.findByText("No file of your department matches.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.startsWith("/custody/held"))!.path).toContain("scope=owned");
    await waitFor(() => expect(screen.getByRole("option", { name: "HEALTH — Health" })).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText("Holder department"), "HEALTH");
    expect(nav.replace).toHaveBeenCalledWith("/files/department?holder_department=HEALTH");
    unmount();
    renderWithClient(<Held scope="owned" params={{ holder_department: "HEALTH", overdue: "true" }} />);
    await waitFor(() =>
      expect(api.calls.some((c) => c.path.includes("holder_department=HEALTH") && c.path.includes("overdue=true"))).toBe(true),
    );
  });

  it("a 403 on Department files says tracking is not among the functions", async () => {
    browserApi({
      "GET /custody/held": json(403, { detail: { code: "forbidden", message: "custody.track needed" } }),
      "GET /custody/summary": json(403, { detail: { code: "forbidden", message: "custody.track needed" } }),
      "GET /custody/recipients": DEPTS,
    });
    renderWithClient(<Held scope="owned" params={{}} />);
    const alerts = await screen.findAllByText("Tracking files of this department is not among your functions.");
    expect(alerts.length).toBeGreaterThan(0);
  });

  it("Sent links only visible cases and shows the others as text", async () => {
    const api = browserApi({
      "GET /custody/sent": { items: [sentItem("c1", "WP(C)/1/2026", true), sentItem("c2", "WA/2/2026", false)], total: 2 },
    });
    renderWithClient(<Sent params={{}} />);
    const table = await screen.findByRole("table", { name: "Files I sent or recalled" });
    expect(within(table).getByRole("link", { name: "WP(C)/1/2026" })).toBeInTheDocument();
    expect(within(table).queryByRole("link", { name: "WA/2/2026" })).toBeNull();
    expect(within(table).getByText("WA/2/2026")).toBeInTheDocument();
    expect(within(table).getAllByText("Health Off, Under Secretary")).toHaveLength(2);
    expect(api.calls[0]!.path).toBe("/custody/sent?limit=50&offset=0");
  });

  it("no list offers an action button", async () => {
    browserApi({
      "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card({ remark: null }) }]),
      "GET /custody/sent": { items: [sentItem("c1", "WP(C)/1/2026", true, null)], total: 1 },
    });
    renderWithClient(
      <>
        <Held scope="me" params={{}} />
        <Sent params={{}} />
      </>,
    );
    await screen.findByRole("table", { name: "Files with me" });
    await screen.findByRole("table", { name: "Files I sent or recalled" });
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("a remark longer than two lines has Show more, with the full text in the page", async () => {
    const long = "Line one of the remark\nline two of the remark\nline three of the remark";
    browserApi({ "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card({ remark: long }) }]) });
    renderWithClient(<Held scope="me" params={{}} />);
    const more = await screen.findByRole("button", { name: "Show more" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(/line three of the remark/)).toBeInTheDocument();
    await userEvent.click(more);
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  });
});

describe("the Files frame (decisions 1, 13, 14)", () => {
  it("/files goes to the first tab", async () => {
    resetNav("/files");
    browserApi({ "GET /me": makeMe(READER) });
    renderWithClient(<FilesIndex />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/files/mine"));
  });

  it("Department files shows only with a tracked department", async () => {
    browserApi({ "GET /me": makeMe(READER) });
    const { unmount } = renderWithClient(
      <FilesFrame>
        <p>body</p>
      </FilesFrame>,
    );
    const tabs = await screen.findByRole("navigation", { name: "Files sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual(["With me", "My offices", "Sent"]);
    expect(within(tabs).getByRole("link", { name: "With me" })).toHaveAttribute("aria-current", "page");
    unmount();
    browserApi({ "GET /me": tracker() });
    renderWithClient(
      <FilesFrame>
        <p>body</p>
      </FilesFrame>,
    );
    const tracked = await screen.findByRole("navigation", { name: "Files sections" });
    expect(within(tracked).getByRole("link", { name: "Department files" })).toHaveAttribute("href", "/files/department");
  });

  it("a login without the tab or without case functions sees the neutral not-found text", async () => {
    resetNav("/files/department");
    browserApi({ "GET /me": makeMe(READER) });
    const { unmount } = renderWithClient(
      <FilesFrame>
        <p>body</p>
      </FilesFrame>,
    );
    expect(await screen.findByText("The page does not exist, or you cannot see it.")).toBeInTheDocument();
    expect(screen.queryByText("body")).toBeNull();
    unmount();
    resetNav("/files/mine");
    browserApi({ "GET /me": makeMe(["users.view"], "dept_admin") });
    renderWithClient(
      <FilesFrame>
        <p>body</p>
      </FilesFrame>,
    );
    expect(await screen.findByText("The page does not exist, or you cannot see it.")).toBeInTheDocument();
  });

  it("the flash notice of a file sent away shows once on the frame", async () => {
    resetNav("/files/sent");
    setFlash("File sent to Health Off. You no longer hold this case.");
    browserApi({ "GET /me": makeMe(READER) });
    const { unmount } = renderWithClient(
      <FilesFrame>
        <p>body</p>
      </FilesFrame>,
    );
    expect(await screen.findByText("File sent to Health Off. You no longer hold this case.")).toBeInTheDocument();
    expect(sessionStorage.getItem("aslms.flash")).toBeNull();
    unmount();
    renderWithClient(
      <FilesFrame>
        <p>body</p>
      </FilesFrame>,
    );
    await screen.findByText("body");
    expect(screen.queryByText(/You no longer hold this case/)).toBeNull();
  });
});
