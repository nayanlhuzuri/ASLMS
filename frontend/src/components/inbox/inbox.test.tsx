/**
 * The Case inbox = the user's own work (design portal-ui-redesign, decisions 5 and 10.4; round 2, row 102): the five
 * tabs by `/inbox/mine/counts` and `whole_department`, the own-work rows and their quick chips, Department cases with
 * the full filter bar (Not allotted sends `unallotted=true`), rows opening the case page, and the old addresses.
 * Recommended, the pool and Transfers are tested with Case claim (`components/claim/claim.test.tsx`).
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { Ownership } from "@/lib/api/types";
import { addDays, istDay } from "@/lib/format";
import { admin, block, membership, myCase, officer, summary } from "@/test/claimFixtures";
import { nav, resetNav } from "@/test/nav";
import { browserApi, makeMe, renderWithClient, type BrowserCall } from "@/test/render";

import { InboxFrame } from "./InboxFrame";
import { ClaimedRedirect, Redirect } from "./Redirects";

const COUNTS = { working: 5, files: 2, claimed: 7, disposed: 1 };

const PEOPLE = {
  departments: [],
  items: [
    { membership_id: "mm-1", user_id: "u-7", full_name: "Officer One", designation: "SO", office_code: "EDU", office_name: "Education", role_label: "Officer" },
  ],
  units: [{ code: "EDU-DSE", name: "Secondary Education" }],
  total: 1,
};

const WORKFLOW_CODES = {
  note_kinds: [],
  pending_actions: [],
  stages: [
    { code: "counsel_briefed", label: "Counsel briefed", phase: "main", sort_order: 4 },
    { code: "affidavit_filed", label: "Affidavit filed", phase: "main", sort_order: 7 },
  ],
  response_modes: [],
  custody_reasons: [],
  limits: { note_max_chars: 4000, attachments_max_files: 5, note_drafts_max: 10 },
};

function ownership(n: number, extra: Partial<Ownership> = {}): Ownership {
  return {
    id: `o-${n}`,
    case: summary(n),
    office_code: "EDU",
    role: "primary",
    status: "active",
    unit: { code: "EDU-DSE", name: "Secondary Education" },
    officer: { id: "u-7", full_name: "Officer One" },
    claimed_at: "2026-10-01T10:00:00Z",
    allotted_at: null,
    released_at: null,
    release_reason: null,
    stage: { stage: "affidavit_filed", label: "Affidavit filed", phase: "main" },
    custody: {
      holder_office: { code: "HEALTH", name: "Health" },
      holder_user: { full_name: "Health Officer", designation: "Deputy Secretary" },
      with_me: false,
      pending_action: "parawise_comments",
      pending_action_label: "Parawise comments",
      since: "2026-10-01T10:00:00Z",
      due_date: null,
      overdue: false,
      overdue_days: 0,
    },
    ...extra,
  };
}

function routes(extra: Record<string, unknown> = {}) {
  return {
    "GET /me": admin(),
    "GET /inbox/counts": { departments: [block("EDU")] },
    "GET /inbox/mine/counts": COUNTS,
    "GET /inbox/mine": { items: [], total: 0 },
    "GET /inbox/claimed": { items: [ownership(1)], total: 1 },
    "GET /custody/recipients": PEOPLE,
    "GET /workflow/codes": WORKFLOW_CODES,
    ...extra,
  };
}

const lastUrl = (calls: BrowserCall[], prefix: string) => calls.filter((c) => c.path.startsWith(prefix)).at(-1)?.path ?? "";

beforeEach(() => {
  resetNav("/inbox/working");
});

describe("tabs", () => {
  it("a department officer sees Working on, Files with me, Claimed by me and Disposed with counts, and no Department cases", async () => {
    browserApi(routes({ "GET /me": officer(), "GET /inbox/counts": { departments: [block("EDU", { whole_department: false })] } }));
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case inbox sections" });
    expect(within(tabs).getByRole("link", { name: /Working on.*\(5\)/ })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: /Files with me.*\(2\)/ })).toHaveAttribute("href", "/inbox/files");
    expect(within(tabs).getByRole("link", { name: /Claimed by me.*\(7\)/ })).toHaveAttribute("href", "/inbox/claimed-by-me");
    expect(within(tabs).getByRole("link", { name: /Disposed.*\(1\)/ })).toBeInTheDocument();
    expect(within(tabs).queryByRole("link", { name: /Department cases/ })).toBeNull();
  });

  it("the department admin also gets Department cases (whole_department)", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case inbox sections" });
    expect(within(tabs).getByRole("link", { name: "Department cases" })).toHaveAttribute("href", "/inbox/department");
  });

  it("a State-wide reader gets Department cases and picks any department", async () => {
    const reader = makeMe(["cases.view_scope", "cases.view_all"], "state_oversight", { memberships: [] });
    browserApi(
      routes({
        "GET /me": reader,
        "GET /inbox/counts": (call: BrowserCall) =>
          call.url.includes("office=FIN")
            ? { departments: [block("FIN")] }
            : { departments: [block(null, { whole_department: false, claimed_active: null, claimed_disposed: null })] },
        "GET /custody/recipients": (call: BrowserCall) =>
          call.url.includes("department=")
            ? PEOPLE
            : { departments: [{ code: "EDU", name: "Education" }, { code: "FIN", name: "Finance" }], items: [], units: [], total: 2 },
      }),
    );
    resetNav("/inbox/department");
    renderWithClient(<InboxFrame tab="department" params={{ department: "FIN" }} />);
    expect(await screen.findByRole("link", { name: "Department cases" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByLabelText("Department")).toHaveValue("FIN");
    await userEvent.selectOptions(screen.getByLabelText("Department"), "EDU");
    expect(nav.push).toHaveBeenCalledWith("/inbox/department?department=EDU");
  });
});

describe("own work", () => {
  it("rows show the case, stage, next hearing badge and my action; a row opens the case page", async () => {
    const soon = addDays(istDay(), 1);
    const api = browserApi(
      routes({
        "GET /inbox/mine": {
          items: [
            myCase(1, {
              case: summary(1, { next_hearing_date: soon }),
              stage: { stage: "counsel_briefed", label: "Counsel briefed", phase: "main" },
              custody: {
                holder_office: { code: "EDU", name: "Education" },
                holder_user: { full_name: "Anita Sharma", designation: "Under Secretary" },
                with_me: true,
                pending_action: "parawise_comments",
                pending_action_label: "Parawise comments",
                since: "2026-10-01T10:00:00Z",
                due_date: "2026-10-10",
                overdue: true,
                overdue_days: 3,
              },
              reasons: ["allotted", "file"],
            }),
            myCase(2),
          ],
          total: 2,
        },
      }),
    );
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const row = await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(within(row).getByText("Counsel briefed")).toBeInTheDocument();
    expect(within(row).getByText("48 h")).toBeInTheDocument();
    expect(within(row).getByText("Parawise comments")).toBeInTheDocument();
    expect(within(row).getByText("Overdue 3 days")).toBeInTheDocument();
    expect(within(row).getByText("RAM KUMAR", { exact: false })).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: "Open WP(C)/2/2026" })).getByText("No stage set")).toBeInTheDocument();
    expect(lastUrl(api.calls, "/inbox/mine?")).toContain("view=working");
    expect(screen.getByText("2 cases")).toBeInTheDocument();
    await userEvent.click(row);
    expect(nav.push).toHaveBeenCalledWith("/cases/ASLMS-GOA-CASE-2026-000001");
  });

  it("the quick chips write next=n7 and action=overdue; the filtered count reads n of m", async () => {
    const api = browserApi(routes({ "GET /inbox/mine": { items: [myCase(1)], total: 1 } }));
    const { unmount } = renderWithClient(<InboxFrame tab="files" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Hearing this week" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/working?next=n7");
    await userEvent.click(screen.getByRole("button", { name: "Action overdue" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/working?action=overdue");
    unmount();
    resetNav("/inbox/files");
    renderWithClient(<InboxFrame tab="files" params={{ next: "n7", action: "overdue", stage: "none" }} />);
    expect(await screen.findByText("1 of 2 cases")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hearing this week" })).toHaveAttribute("aria-pressed", "true");
    const url = lastUrl(api.calls, "/inbox/mine?");
    for (const part of ["view=files", "action=overdue", "stage=none", `next_from=${istDay()}`]) expect(url).toContain(part);
  });

  it("Stage is on the first row; words, case type, year and court are under More filters", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const stage = await screen.findByLabelText("Stage");
    await waitFor(() => expect(within(stage).getByRole("option", { name: "Counsel briefed" })).toBeInTheDocument());
    expect(within(stage).getByRole("option", { name: "No stage set" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Year")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    expect(screen.getByLabelText("Year")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Words/)).toBeInTheDocument();
    expect(screen.getByLabelText("Court")).toBeInTheDocument();
    await userEvent.selectOptions(stage, "counsel_briefed");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/working?stage=counsel_briefed");
  });

  it("the page has at most one primary button (decision 16)", async () => {
    browserApi(routes({ "GET /inbox/mine": { items: [myCase(1)], total: 1 } }));
    const { container } = renderWithClient(<InboxFrame tab="working" params={{}} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });

  it("an empty view says when items appear", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="claimed" params={{}} />);
    expect(await screen.findByText("Nothing waiting")).toBeInTheDocument();
    expect(screen.getByText(/Cases you claim for your department/)).toBeInTheDocument();
  });
});

describe("Department cases", () => {
  beforeEach(() => resetNav("/inbox/department"));

  it("the filter grid: Search, Unit, Officer, Stage, Next hearing; More filters slides open with the rest", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    const row = await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(within(row).getByText("EDU-DSE")).toBeInTheDocument();
    expect(within(row).getByText("Officer One", { exact: false })).toBeInTheDocument();
    expect(within(row).getByText("Affidavit filed")).toBeInTheDocument();
    expect(within(row).getByText("Health Officer", { exact: false })).toBeInTheDocument();
    for (const label of ["Unit", "Officer", "Stage", "Next hearing"]) expect(screen.getByLabelText(label)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Words/)).toBeInTheDocument();
    const next = screen.getByLabelText("Next hearing");
    expect(within(next).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Any date",
      "This week",
      "Next 30 days",
      "Choose dates…",
    ]);
    expect(screen.queryByLabelText("File is with")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    for (const label of ["Case type", "Year", "Court", "File is with", "Action"]) expect(screen.getByLabelText(label)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Active" })).toHaveAttribute("aria-checked", "true");
  });

  it("Not allotted sends unallotted=true; the chips show with n of m and removing one applies at once", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="department" params={{}} />);
    const officerSelect = await screen.findByLabelText("Officer");
    await waitFor(() => expect(within(officerSelect).getByRole("option", { name: "Officer One" })).toBeInTheDocument());
    await userEvent.selectOptions(officerSelect, "none");
    await userEvent.selectOptions(screen.getByLabelText("Next hearing"), "n7");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/department?next=n7&officer=none");
    unmount();
    renderWithClient(<InboxFrame tab="department" params={{ officer: "none", next: "n7", holder: "elsewhere", action: "overdue" }} />);
    expect(await screen.findByText("1 of 4 cases")).toBeInTheDocument();
    const url = lastUrl(api.calls, "/inbox/claimed?");
    for (const part of ["office=EDU", "case_state=active", "unallotted=true", "holder=elsewhere", "action=overdue", "next_from="]) {
      expect(url).toContain(part);
    }
    expect(url).not.toContain("officer_user_id");
    const chips = screen.getByRole("list", { name: "Applied filters" });
    expect(within(chips).getByText("Officer: Not allotted")).toBeInTheDocument();
    expect(within(chips).getByText("File is with: Another department")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove filter Officer: Not allotted" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/inbox/department?next=n7&holder=elsewhere&action=overdue");
  });

  it("an officer chosen sends officer_user_id; Disposed is the Status switch", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="department" params={{ officer: "u-7" }} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(lastUrl(api.calls, "/inbox/claimed?")).toContain("officer_user_id=u-7");
    await userEvent.click(screen.getByRole("radio", { name: "Disposed" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/department?officer=u-7&case_state=disposed");
    unmount();
    renderWithClient(<InboxFrame tab="department" params={{ case_state: "disposed" }} />);
    await waitFor(() => expect(lastUrl(api.calls, "/inbox/claimed?")).toContain("case_state=disposed"));
  });

  it("a row opens the case page; there is no release or return to the pool", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    await userEvent.click(await screen.findByRole("row", { name: "Open WP(C)/1/2026" }));
    expect(nav.push).toHaveBeenCalledWith("/cases/ASLMS-GOA-CASE-2026-000001");
    expect(screen.queryByRole("button", { name: /release|return|unclaim/i })).toBeNull();
  });

  it("the default department of a two-department login is the one read whole", async () => {
    const two = admin(undefined, { memberships: [membership("EDU", ["cases.view_scope"]), membership("HEALTH", ["cases.view_scope", "cases.claim"], false)] });
    const api = browserApi(
      routes({
        "GET /me": two,
        "GET /inbox/counts": { departments: [block("EDU", { whole_department: false }), block("HEALTH")] },
      }),
    );
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(lastUrl(api.calls, "/inbox/claimed?")).toContain("office=HEALTH");
  });
});

describe("old addresses", () => {
  it("/inbox opens Working on", async () => {
    resetNav("/inbox");
    renderWithClient(<Redirect to="/inbox/working" params={{}} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/working"));
  });

  it("/inbox/claimed goes to Department cases for a whole-department reader, keeping the query string", async () => {
    browserApi(routes());
    renderWithClient(<ClaimedRedirect params={{ department: "EDU", case_state: "disposed" }} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/department?department=EDU&case_state=disposed"));
  });

  it("/inbox/claimed goes to Working on for an officer", async () => {
    browserApi(routes({ "GET /me": officer(), "GET /inbox/counts": { departments: [block("EDU", { whole_department: false })] } }));
    renderWithClient(<ClaimedRedirect params={{}} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/working"));
  });
});
