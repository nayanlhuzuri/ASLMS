import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseDetail, CustodyCard, CustodyHistory, CustodyLeg } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, makeMe, PRIMARY_SELECTOR, renderWithClient } from "@/test/render";

import { CaseFrame } from "./CaseFrame";
import { Rail, type RailAction } from "./Rail";

const REF = "ASLMS-GOA-CASE-2026-000001";
const BASE = `/cases/${REF}`;

function card(extra: Partial<CustodyCard> = {}): CustodyCard {
  return {
    due_soon: false,
    can_recall: false,
    can_send: true,
    due_date: "2099-11-30",
    holder_office: { code: "EDU", name: "Education" },
    holder_user: { id: "u-1", full_name: "Anita Sharma", designation: "Under Secretary" },
    leg_seq_no: 5,
    overdue: false,
    overdue_days: 0,
    pending_action: "prepare_reply",
    pending_action_label: "Prepare reply",
    reason: "sent",
    remark: "Please draft the affidavit by Friday.",
    sent_by: { name: "Edu Head", designation: "Commissioner and Secretary", office_code: "EDU" },
    since: "2026-10-20T10:00:00Z",
    ...extra,
  };
}

function detail(extra: Partial<CaseDetail> = {}): CaseDetail {
  return {
    id: "c-1",
    ref_no: "ASLMS/GOA/CASE/2026/000001",
    identity: { case_no_text: "WP(C)/1234/2026" },
    custody: card(),
    workflow: { note_mode: "draft", upload: true, set_stage: true, next_dates: true },
    status: { status: "pending", next_hearing_date: "2099-11-20" },
    counts: { documents: 0, hearings: 0, links: 0, listings: 0, my_drafts: 0, notes: 3, orders: 0, timeline: 0 },
    ...extra,
  } as unknown as CaseDetail;
}

function leg(seq: number, extra: Partial<CustodyLeg> = {}): CustodyLeg {
  return {
    seq_no: seq,
    holder_office: { code: "EDU", name: "Education" },
    holder_user: { id: `u-${seq}`, full_name: `Officer ${seq}` },
    holder_designation: `Post ${seq}`,
    reason: "sent",
    reason_label: "Sent",
    pending_action: "examine",
    pending_action_label: "Examine",
    due_date: null,
    remark: `remark ${seq}`,
    started_at: `2026-10-${10 + seq}T10:00:00Z`,
    actor_name: "Edu Head",
    actor_designation: "Commissioner and Secretary",
    actor_office_code: "EDU",
    ...extra,
  };
}

function history(extra: Partial<CustodyHistory> = {}): CustodyHistory {
  return {
    card: card(),
    legs: [leg(5), leg(4, { reason: "recalled", reason_label: "Recalled" }), leg(3), leg(2), leg(1)],
    total: 5,
    remarks_shown: true,
    ...extra,
  };
}

function routes(h: CustodyHistory | null = history()) {
  return {
    "GET /me": makeMe(["cases.view_scope"]),
    [`GET ${BASE}/custody`]: h,
    [`GET ${BASE}/listings`]: { items: [], total: 0 },
  };
}

function renderRail(c: CaseDetail, wide = true, onAction: (a: RailAction) => void = () => {}, onRemarks = () => {}) {
  return renderWithClient(<Rail c={c} caseRef={REF} wide={wide} onAction={onAction} onRemarks={onRemarks} />);
}

beforeEach(() => resetNav(BASE));

describe("Your task (case-workspace-admin, decision 10)", () => {
  it("the case is with the caller: the action, From, Due by with days left, the latest remark, See all remarks and the hint", async () => {
    browserApi(routes());
    renderRail(detail());
    const task = await screen.findByRole("region", { name: "Your task" });
    expect(await within(task).findByText("Your task", { selector: "div" })).toBeInTheDocument();
    expect(within(task).getByText("Prepare reply")).toBeInTheDocument();
    expect(within(task).getByText("Commissioner and Secretary, EDU")).toHaveAttribute("title", "Edu Head");
    expect(within(task).getByText(/30 Nov 2099/)).toBeInTheDocument();
    expect(within(task).getByText(/days left/)).toBeInTheDocument();
    expect(within(task).getByText("“Please draft the affidavit by Friday.”")).toBeInTheDocument();
    expect(await within(task).findByRole("button", { name: "See all remarks (5)" })).toBeInTheDocument();
    expect(within(task).getByText("Done? Use Send case above to pass it on with your remark.")).toBeInTheDocument();
    expect(within(task).queryByRole("button", { name: "Recall case" })).toBeNull();
  });

  it("overdue says Overdue by n days", async () => {
    browserApi(routes());
    renderRail(detail({ custody: card({ overdue: true, overdue_days: 3, due_date: "2026-10-20" }) }));
    const task = await screen.findByRole("region", { name: "Your task" });
    expect(within(task).getByText("Overdue by 3 days")).toBeInTheDocument();
  });

  it("the case is with someone else: With <designation, office>, Recall case as a secondary danger button, never primary", async () => {
    const other = card({
      holder_user: { id: "u-7", full_name: "Officer One", designation: "Section Officer" },
      holder_office: { code: "EDU-DSE", name: "Secondary Education" },
      can_send: false,
      can_recall: true,
    });
    const onAction = vi.fn();
    browserApi(routes());
    const { container } = renderRail(detail({ custody: other }), true, onAction);
    const task = await screen.findByRole("region", { name: "Your task" });
    expect(await within(task).findByText("With Section Officer, Secondary Education")).toHaveAttribute("title", "Officer One");
    const recall = within(task).getByRole("button", { name: "Recall case" });
    expect(recall).toHaveAttribute("data-variant", "danger");
    expect(container.querySelectorAll(PRIMARY_SELECTOR)).toHaveLength(0);
    expect(within(task).queryByText(/Done\? Use Send case/)).toBeNull();
    await userEvent.click(recall);
    expect(onAction).toHaveBeenCalledWith("recall");
  });

  it("Recall case shows only with can_recall", async () => {
    browserApi(routes());
    renderRail(detail({ custody: card({ holder_user: { id: "u-7", full_name: "O", designation: "SO" }, can_recall: false }) }));
    const task = await screen.findByRole("region", { name: "Your task" });
    await within(task).findByText(/With SO/);
    expect(within(task).queryByRole("button", { name: "Recall case" })).toBeNull();
  });

  it("the remark is absent when the API omits it, with no placeholder; See the journey when remarks are not shown", async () => {
    browserApi(routes(history({ remarks_shown: false, legs: [leg(2, { remark: null }), leg(1, { remark: null })], total: 2 })));
    renderRail(detail({ custody: card({ holder_user: { id: "u-7", full_name: "O", designation: "SO" }, remark: null }) }));
    const task = await screen.findByRole("region", { name: "Your task" });
    expect(await within(task).findByRole("button", { name: "See the journey (2)" })).toBeInTheDocument();
    expect(within(task).queryByRole("button", { name: /See all remarks/ })).toBeNull();
    expect(within(task).queryByText(/“/)).toBeNull();
    expect(within(task).queryByText(/remark|hidden/i)).toBeNull();
  });

  it("See all remarks opens the history", async () => {
    const onRemarks = vi.fn();
    browserApi(routes());
    renderRail(detail(), true, () => {}, onRemarks);
    await userEvent.click(await screen.findByRole("button", { name: "See all remarks (5)" }));
    expect(onRemarks).toHaveBeenCalled();
  });

  it("a case with an office and no officer: With <office name>", async () => {
    browserApi(routes());
    renderRail(detail({ custody: card({ holder_user: null, can_send: false }) }));
    const task = await screen.findByRole("region", { name: "Your task" });
    expect(within(task).getByText("With Education")).toBeInTheDocument();
  });

  it("no custody: one muted line and no buttons; no journey card", async () => {
    browserApi(routes(null));
    renderRail(detail({ custody: null, workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false } }));
    const task = await screen.findByRole("region", { name: "Your task" });
    expect(within(task).getByText("The case moves between officers once a department claims it.")).toBeInTheDocument();
    expect(within(task).queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("region", { name: "Journey of this case" })).toBeNull();
  });
});

describe("Next hearing, Quick actions and Journey (decisions 11, 12 and 14)", () => {
  it("Next hearing: the weekday and date with the countdown; none says so and offers Enter next date by the flag", async () => {
    browserApi(routes());
    const onAction = vi.fn();
    const { unmount } = renderRail(detail(), true, onAction);
    const card1 = screen.getByRole("region", { name: "Next hearing" });
    expect(within(card1).getByText(/^Fri, 20 Nov 2099 · in [0-9]+ days$/)).toBeInTheDocument();
    unmount();
    renderRail(detail({ status: { status: "pending", next_hearing_date: null } as CaseDetail["status"] }), true, onAction);
    const none = screen.getByRole("region", { name: "Next hearing" });
    expect(within(none).getByText("No next hearing date yet")).toBeInTheDocument();
    await userEvent.click(within(none).getByRole("button", { name: "Enter next date" }));
    expect(onAction).toHaveBeenCalledWith("next");
  });

  it("Quick actions follow the three workflow flags, and the card hides with none", async () => {
    browserApi(routes());
    const onAction = vi.fn();
    const { unmount } = renderRail(detail(), true, onAction);
    const quick = screen.getByRole("region", { name: "Quick actions" });
    expect(within(quick).getAllByRole("button").map((b) => b.textContent)).toEqual(["Add note", "Upload a document", "Set stage"]);
    for (const b of within(quick).getAllByRole("button")) expect(b).toHaveAttribute("data-variant", "secondary");
    await userEvent.click(within(quick).getByRole("button", { name: "Upload a document" }));
    expect(onAction).toHaveBeenCalledWith("upload");
    unmount();
    const { unmount: u2 } = renderRail(detail({ workflow: { note_mode: null, upload: false, set_stage: true, next_dates: false } }));
    expect(within(screen.getByRole("region", { name: "Quick actions" })).getAllByRole("button").map((b) => b.textContent)).toEqual(["Set stage"]);
    u2();
    renderRail(detail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false } }));
    expect(screen.queryByRole("region", { name: "Quick actions" })).toBeNull();
  });

  it("the journey shows the latest 4 movements newest first, the now marker and the reason when it is not a send", async () => {
    const api = browserApi(routes());
    renderRail(detail());
    const journey = screen.getByRole("region", { name: "Journey of this case" });
    const list = await within(journey).findByRole("list", { name: "Journey of this case" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items.map((li) => within(li).getByText(/^With /).textContent)).toEqual([
      "With Post 5, Education",
      "With Post 4, Education",
      "With Post 3, Education",
      "With Post 2, Education",
    ]);
    expect(items[0]).toHaveAttribute("aria-current", "step");
    expect(within(items[0]!).getByText("now")).toBeInTheDocument();
    expect(within(items[1]!).getByText("Recalled")).toBeInTheDocument();
    expect(within(journey).getByRole("link", { name: "Journey and stage" })).toHaveAttribute("href", `${BASE}/custody`);
    expect(within(journey).queryByRole("button", { name: /See all remarks/ })).toBeNull();
    const call = api.calls.find((c) => c.path.startsWith(`${BASE}/custody`))!;
    expect(call.path).toContain("order=desc");
    expect(call.path).toContain("limit=4");
  });
});

describe("the layout (decision 8)", () => {
  it("below 1100 px the cards are collapsibles: Your task open, the others closed with their key fact", async () => {
    browserApi(routes());
    renderRail(detail(), false);
    const task = await screen.findByRole("region", { name: "Your task" });
    expect(within(task).getByRole("button", { name: /Your task/ })).toHaveAttribute("aria-expanded", "true");
    const hearing = screen.getByRole("region", { name: "Next hearing" });
    const toggle = within(hearing).getByRole("button", { name: /Next hearing/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent(/Fri, 20 Nov 2099/);
    expect(within(screen.getByRole("region", { name: "Quick actions" })).getByRole("button", { name: /3 actions/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    const journey = screen.getByRole("region", { name: "Journey of this case" });
    await waitFor(() => expect(within(journey).getByRole("button", { name: /Journey of this case/ })).toHaveTextContent("With Post 5, Education"));
  });

  describe("on the case page", () => {
    const original = window.matchMedia;
    afterEach(() => {
      window.matchMedia = original;
    });

    function wideScreen(matches: boolean) {
      window.matchMedia = ((query: string) => ({
        matches,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      })) as unknown as typeof window.matchMedia;
    }

    function pageRoutes() {
      return {
        ...routes(),
        [`GET ${BASE}`]: {
          ...detail(),
          identity: { case_no_text: "WP(C)/1234/2026" },
          ownership: { primary: null, watchers: [] },
          parties_as_printed: { petitioner_summary: null, respondent_summary: null },
          portal: { is_provisional: false },
          dossier_status: "fetched",
          stage: null,
          merged_into_ref_no: null,
        },
        [`GET ${BASE}/ownership`]: { primary: null, watchers: [], recommendations: [], open_transfer: null, actions: {} },
      };
    }

    it("from 1100 px the rail is a column beside the tabs; below, its cards sit above the tabs", async () => {
      wideScreen(true);
      browserApi(pageRoutes());
      const { unmount } = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
      const aside = await screen.findByRole("complementary", { name: "Case work" });
      expect(within(aside).getByRole("region", { name: "Your task" })).toBeInTheDocument();
      const tabs = screen.getByRole("navigation", { name: "Case sections" });
      expect(tabs.compareDocumentPosition(aside) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      unmount();
      wideScreen(false);
      browserApi(pageRoutes());
      renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
      const task = await screen.findByRole("region", { name: "Your task" });
      expect(screen.queryByRole("complementary", { name: "Case work" })).toBeNull();
      const tabs2 = screen.getByRole("navigation", { name: "Case sections" });
      expect(task.compareDocumentPosition(tabs2) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("Add note, Upload and Set stage are not in the header or its menu; one primary, Send case", async () => {
      wideScreen(true);
      browserApi(pageRoutes());
      const { container } = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
      const group = await screen.findByRole("group", { name: "Case actions" });
      expect(within(group).getByRole("button", { name: "Send case" })).toHaveAttribute("data-variant", "primary");
      for (const name of ["Add note", "Upload a document", "Set stage"]) expect(within(group).queryByRole("button", { name })).toBeNull();
      await userEvent.click(within(group).getByRole("button", { name: "More actions" }));
      const items = within(group).getAllByRole("menuitem").map((m) => m.textContent);
      for (const name of ["Add note", "Upload a document", "Set stage"]) expect(items).not.toContain(name);
      expect(container.querySelectorAll(PRIMARY_SELECTOR)).toHaveLength(1);
    });
  });
});
