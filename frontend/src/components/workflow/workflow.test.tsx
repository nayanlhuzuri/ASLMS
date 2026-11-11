import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Documents } from "@/components/case/Documents";
import { Notes } from "@/components/case/Notes";
import type { AlertItem, CaseDetail, CustodyCard, DocumentItem, Draft, Note, Permission, WorkflowCodes } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, renderWithClient } from "@/test/render";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import { caseKey } from "@/lib/api/hooks";

import { CaseAlerts } from "./CaseAlerts";
import { CloseCaseDialog } from "./CloseCaseDialog";
import { CustodyActions } from "./CustodyDialogs";
import { CustodyTab } from "./CustodyTab";
import { ReopenCaseDialog } from "./ReopenCaseDialog";
import { withNextHearing } from "@/test/nextHearing";

const REF = "ASLMS-GHC-CASE-2026-000001";
const BASE = `/cases/${REF}`;
const READ: Permission[] = ["cases.view_scope", "documents.view", "documents.download", "notes.add", "documents.upload"];

function card(extra: Partial<CustodyCard> = {}): CustodyCard {
  return {
    due_soon: false,
    can_recall: false,
    can_send: true,
    closed: false,
    due_date: null,
    holder_office: { code: "EDU-DSE", name: "Secondary Education" },
    holder_user: { id: "u-7", full_name: "Officer One", designation: "SO" },
    leg_seq_no: 1,
    overdue: false,
    overdue_days: 0,
    pending_action: "examine",
    pending_action_label: "Examine",
    reason: "claimed",
    remark: null,
    sent_by: null,
    since: "2026-10-01T10:00:00Z",
    ...extra,
  };
}

function detail(extra: Partial<CaseDetail> = {}): CaseDetail {
  return withNextHearing(detailBase(extra), extra);
}

function detailBase(extra: Partial<CaseDetail>): CaseDetail {
  return {
    id: "c-1",
    ref_no: "ASLMS/GHC/CASE/2026/000001",
    access_basis: ["owner"],
    counts: { documents: 0, hearings: 0, links: 0, listings: 0, my_drafts: 0, notes: 0, orders: 0, timeline: 0 },
    workflow: { note_mode: "permanent", upload: true, set_stage: true, next_dates: false, next_date_report: false, next_date_correct: false, close: false, reopen: false },
    custody: card(),
    stage: null,
    ownership: {
      primary: { office_code: "EDU", office_name: "Education", unit: null, officer: null, claimed_at: "2026-09-01T10:00:00Z" },
      watchers: [],
    },
    ...extra,
  } as CaseDetail;
}

const CODES: WorkflowCodes = {
  note_kinds: [
    { code: "general", label: "General", selectable: true },
    { code: "opinion", label: "Opinion", selectable: true },
    { code: "correction", label: "Correction", selectable: false },
  ],
  pending_actions: [
    { code: "none", label: "None", sendable: false },
    { code: "examine", label: "Examine", sendable: true },
    { code: "parawise_comments", label: "Parawise comments", sendable: true },
  ],
  stages: [
    { code: "notice_received", label: "Notice received", phase: "intake", sort_order: 10 },
    { code: "reply_due", label: "Reply due", phase: "main", sort_order: 20 },
    { code: "reply_filed", label: "Reply filed", phase: "main", sort_order: 30 },
  ],
  response_modes: [
    { code: "department", label: "By the department" },
    { code: "counsel", label: "By counsel" },
  ],
  custody_reasons: [
    { code: "sent", label: "Sent" },
    { code: "recalled", label: "Recalled" },
  ],
  limits: { note_max_chars: 200, attachments_max_files: 2, note_drafts_max: 20 },
};

const TYPES = {
  items: [
    { code: "petition", label: "Petition", doc_group: "court_filing", group_choosable: false },
    { code: "correspondence", label: "Correspondence", doc_group: "internal", group_choosable: false },
    { code: "office_note", label: "Office note", doc_group: "internal", group_choosable: false },
    { code: "other", label: "Other", doc_group: "internal", group_choosable: true },
  ],
  upload: { max_bytes: 50, extensions: ["pdf", "docx", "doc", "jpg", "jpeg", "png"] },
};

const DEPTS = { departments: [{ code: "EDU", name: "Education" }, { code: "HEALTH", name: "Health" }], items: [], units: [], total: 2 };
const HEALTH_PEOPLE = {
  departments: [],
  items: [
    { membership_id: "m-h1", user_id: "u-h1", full_name: "Health Off", designation: "Under Secretary", office_code: "HEALTH", office_name: "Health", role_label: "Department officer" },
    { membership_id: "m-h2", user_id: "u-h2", full_name: "Health Dir", designation: "Deputy Director", office_code: "HEALTH-DHS", office_name: "Health Services", role_label: "Directorate user" },
  ],
  units: [],
  total: 2,
};

function moved(cardAfter: CustodyCard | null, finalised: string[] = []) {
  return json(201, {
    card: cardAfter,
    leg: {
      seq_no: 2,
      holder_office: { code: "HEALTH", name: "Health" },
      holder_user: { id: "u-h1", full_name: "Health Off" },
      holder_designation: "Under Secretary",
      reason: "sent",
      reason_label: "Sent",
      pending_action: "parawise_comments",
      pending_action_label: "Parawise comments",
      due_date: null,
      remark: "please comment",
      started_at: "2026-10-13T10:00:00Z",
      actor_name: "Edu Admin",
      actor_designation: null,
      actor_office_code: "EDU",
    },
    finalised_notes: finalised,
  });
}

function me(functions: Permission[] = READ) {
  return makeMe(functions, "dept_admin");
}

beforeEach(() => {
  resetNav(BASE);
  sessionStorage.clear();
});

// ------------------------------------------------------------------------------------------------ custody

describe("Send case and Recall case", () => {
  it("appear exactly when the card's can_send / can_recall say so", async () => {
    browserApi({ "GET /me": me() });
    const { unmount } = renderWithClient(<CustodyActions caseRef={REF} detail={detail()} card={card({ can_send: true, can_recall: true })} />);
    expect(screen.getByRole("button", { name: "Send Case" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recall Case" })).toBeInTheDocument();
    unmount();
    renderWithClient(<CustodyActions caseRef={REF} detail={detail()} card={card({ can_send: false, can_recall: false })} />);
    expect(screen.queryByRole("button", { name: /Send Case|Recall Case/ })).toBeNull();
  });

  it("Send case walks three steps: who, what, remark; Continue refuses a missing field; Back keeps values; the body is unchanged", async () => {
    const api = browserApi({
      "GET /workflow/codes": CODES,
      "GET /custody/recipients": (call: { url: string }) => (call.url.includes("department=HEALTH") ? HEALTH_PEOPLE : DEPTS),
      [`POST ${BASE}/custody/send`]: moved(card({ holder_user: { id: "u-h1", full_name: "Health Off", designation: null }, can_send: false })),
    });
    renderWithClient(
      <CustodyActions caseRef={REF} detail={detail({ counts: { ...detail().counts, my_drafts: 2 } })} card={card()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Send Case" }));
    const dialog = screen.getByRole("dialog", { name: "Send the Case" });
    // step 1: who receives it (the stepper says where we are)
    expect(within(dialog).getByText("Step 1 of 3 · Who Receives It")).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "Health" })).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).getByText("Required.")).toBeInTheDocument();
    expect(within(dialog).getByText("Step 1 of 3 · Who Receives It")).toBeInTheDocument();
    await userEvent.selectOptions(within(dialog).getByLabelText("Department"), "HEALTH");
    await waitFor(() => expect(within(dialog).getByRole("radio", { name: /Health Off/ })).toBeInTheDocument());
    await userEvent.type(within(dialog).getByLabelText("Search by Name or Designation"), "dir");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("department=HEALTH") && c.url.includes("q=dir"))).toBe(true));
    // the people are cards with their initials
    expect(within(dialog).getAllByText("HO").length).toBeGreaterThan(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).getByText("Choose the person who receives the case.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("radio", { name: /Health Off/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    // step 2: what they should do — the sendable actions only, nothing pre-selected; the stage with the flag
    expect(within(dialog).getByText("Step 2 of 3 · What They Should Do")).toBeInTheDocument();
    const action = within(dialog).getByLabelText("Pending Action") as HTMLSelectElement;
    await waitFor(() => expect(within(action).getByRole("option", { name: "Parawise Comments" })).toBeInTheDocument());
    expect(action.value).toBe("");
    expect(within(action).queryByRole("option", { name: "None" })).toBeNull();
    expect(within(dialog).getByLabelText("Stage (Optional)")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).getByText("Required.")).toBeInTheDocument();
    await userEvent.selectOptions(action, "parawise_comments");
    // Back keeps what was entered
    await userEvent.click(within(dialog).getByRole("button", { name: "Back" }));
    expect(within(dialog).getByRole("radio", { name: /Health Off/ })).toBeChecked();
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect((within(dialog).getByLabelText("Pending Action") as HTMLSelectElement).value).toBe("parawise_comments");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    // step 3: the remark is required; the drafts notice and the summary line
    expect(within(dialog).getByText("Step 3 of 3 · Remark and Confirm")).toBeInTheDocument();
    expect(within(dialog).getByText("Your 2 draft notes become permanent notes of the case when you send.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Send Case" }));
    expect(within(dialog).getByText("Give a remark of 3 to 2,000 characters.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByLabelText("Remark"), "please comment");
    expect(within(dialog).getByText("Send to Health Off, Under Secretary, Health — Parawise Comments")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Send Case" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
        to_membership: "m-h1",
        pending_action: "parawise_comments",
        due_date: null,
        remark: "please comment",
        stage: null,
      }),
    );
    expect(await screen.findByText("Case sent to Health Off, Under Secretary, Health.")).toBeInTheDocument();
  });

  it("offers no stage without workflow.set_stage", async () => {
    browserApi({
      "GET /workflow/codes": CODES,
      "GET /custody/recipients": (call: { url: string }) => (call.url.includes("department=HEALTH") ? HEALTH_PEOPLE : DEPTS),
    });
    renderWithClient(
      <CustodyActions caseRef={REF} detail={detail({ workflow: { note_mode: "draft", upload: true, set_stage: false, next_dates: false, next_date_report: false, next_date_correct: false, close: false, reopen: false } })} card={card()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Send Case" }));
    const dialog = screen.getByRole("dialog", { name: "Send the Case" });
    await chooseHealthOff(dialog);
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "Examine" })).toBeInTheDocument());
    expect(within(dialog).queryByLabelText("Stage (Optional)")).toBeNull();
    await userEvent.selectOptions(within(dialog).getByLabelText("Pending Action"), "examine");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).queryByText(/draft notes? become/)).toBeNull();
  });

  async function chooseHealthOff(dialog: HTMLElement) {
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "Health" })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog).getByLabelText("Department"), "HEALTH");
    await waitFor(() => expect(within(dialog).getByRole("radio", { name: /Health Off/ })).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("radio", { name: /Health Off/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
  }

  async function fillAndSend(dialog: HTMLElement) {
    await chooseHealthOff(dialog);
    await userEvent.selectOptions(within(dialog).getByLabelText("Pending Action"), "examine");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    await userEvent.type(within(dialog).getByLabelText("Remark"), "over to you");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send Case" }));
  }

  it("a card: null answer goes to Case inbox → Sent by me with the notice and the finalised notes", async () => {
    browserApi({
      "GET /workflow/codes": CODES,
      "GET /custody/recipients": (call: { url: string }) => (call.url.includes("department=HEALTH") ? HEALTH_PEOPLE : DEPTS),
      [`POST ${BASE}/custody/send`]: moved(null, ["ASLMS/HEALTH/NOTE/2026/000001"]),
    });
    renderWithClient(<CustodyActions caseRef={REF} detail={detail()} card={card()} />);
    await userEvent.click(screen.getByRole("button", { name: "Send Case" }));
    await fillAndSend(screen.getByRole("dialog", { name: "Send the Case" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/inbox/sent?earlier=true"));
    expect(sessionStorage.getItem("aslms.flash")).toBe(
      "Case sent to Health Off, Under Secretary, Health. It is no longer with you. Made permanent: ASLMS/HEALTH/NOTE/2026/000001",
    );
  });

  it("sending the case away does not fetch it again before Case inbox → Sent by me (no not-found flash)", async () => {
    const calls = browserApi({
      "GET /workflow/codes": CODES,
      "GET /custody/recipients": (call: { url: string }) => (call.url.includes("department=HEALTH") ? HEALTH_PEOPLE : DEPTS),
      [`POST ${BASE}/custody/send`]: moved(null, []),
      [`GET ${BASE}`]: detail(),
    });
    function CasePageProbe() {
      // stands in for the case page that observes the case's query while the dialog is open and re-renders
      // (as CaseFrame does when the dialog closes) before the navigation commits
      const [, tick] = useState(0);
      useEffect(() => {
        const t = setInterval(() => tick((n) => n + 1), 5);
        return () => clearInterval(t);
      }, []);
      const q = useQuery({ queryKey: caseKey(REF), queryFn: () => api<CaseDetail>(BASE) });
      return <span>{q.data ? "case loaded" : "loading"}</span>;
    }
    renderWithClient(
      <>
        <CasePageProbe />
        <CustodyActions caseRef={REF} detail={detail()} card={card()} />
      </>,
    );
    expect(await screen.findByText("case loaded")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send Case" }));
    await fillAndSend(screen.getByRole("dialog", { name: "Send the Case" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/inbox/sent?earlier=true"));
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.calls.filter((c) => c.method === "GET" && c.path === BASE)).toHaveLength(1);
    expect(screen.getByText("case loaded")).toBeInTheDocument();
  });

  it("the finalised notes are listed when the sender still sees the case", async () => {
    browserApi({
      "GET /workflow/codes": CODES,
      "GET /custody/recipients": (call: { url: string }) => (call.url.includes("department=HEALTH") ? HEALTH_PEOPLE : DEPTS),
      [`POST ${BASE}/custody/send`]: moved(card({ can_send: false }), ["ASLMS/EDU/NOTE/2026/000004", "ASLMS/EDU/NOTE/2026/000005"]),
    });
    renderWithClient(<CustodyActions caseRef={REF} detail={detail()} card={card()} />);
    await userEvent.click(screen.getByRole("button", { name: "Send Case" }));
    await fillAndSend(screen.getByRole("dialog", { name: "Send the Case" }));
    expect(
      await screen.findByText(/Made permanent: ASLMS\/EDU\/NOTE\/2026\/000004, ASLMS\/EDU\/NOTE\/2026\/000005/),
    ).toBeInTheDocument();
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("409 unchanged and 403 not_in_control are put in words", async () => {
    let answer = json(409, { detail: { code: "unchanged", message: "the case is already with that officer" } });
    browserApi({
      "GET /workflow/codes": CODES,
      "GET /custody/recipients": (call: { url: string }) => (call.url.includes("department=HEALTH") ? HEALTH_PEOPLE : DEPTS),
      [`POST ${BASE}/custody/send`]: () => answer,
    });
    renderWithClient(<CustodyActions caseRef={REF} detail={detail()} card={card()} />);
    await userEvent.click(screen.getByRole("button", { name: "Send Case" }));
    const dialog = screen.getByRole("dialog", { name: "Send the Case" });
    await fillAndSend(dialog);
    expect(await within(dialog).findByText("the case is already with that officer")).toBeInTheDocument();
    answer = json(403, { detail: { code: "not_in_control", message: "x" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send Case" }));
    expect(
      await within(dialog).findByText("The case is not with you, and you do not control the office it is with."),
    ).toBeInTheDocument();
  });

  it("the recall dialog names the holder and needs a remark", async () => {
    const api = browserApi({ [`POST ${BASE}/custody/recall`]: moved(card({ can_recall: false })) });
    renderWithClient(<CustodyActions caseRef={REF} detail={detail()} card={card({ can_send: false, can_recall: true })} />);
    await userEvent.click(screen.getByRole("button", { name: "Recall Case" }));
    const dialog = screen.getByRole("dialog", { name: "Recall the Case" });
    expect(within(dialog).getByText("The case is with Officer One, SO, Secondary Education.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Recall Case" }));
    expect(within(dialog).getByText("Give a remark of 3 to 2,000 characters.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByLabelText("Remark"), "needed back");
    await userEvent.click(within(dialog).getByRole("button", { name: "Recall Case" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ remark: "needed back" }));
    expect(await screen.findByText("The case is with you now, with 'Examine' pending.")).toBeInTheDocument();
  });
});

describe("the custody tab", () => {
  const legs = [
    {
      seq_no: 1,
      holder_office: { code: "EDU", name: "Education" },
      holder_user: null,
      holder_designation: null,
      reason: "claimed",
      reason_label: "Claimed",
      pending_action: "examine",
      pending_action_label: "Examine",
      due_date: null,
      remark: null,
      started_at: "2026-10-01T10:00:00Z",
      actor_name: "Edu Admin",
      actor_designation: null,
      actor_office_code: "EDU",
    },
    {
      seq_no: 2,
      holder_office: { code: "HEALTH", name: "Health" },
      holder_user: { id: "u-h1", full_name: "Health Off" },
      holder_designation: "Under Secretary",
      reason: "sent",
      reason_label: "Sent",
      pending_action: "parawise_comments",
      pending_action_label: "Parawise comments",
      due_date: "2026-10-20",
      remark: "comments within a week",
      started_at: "2026-10-02T10:00:00Z",
      actor_name: "Edu Admin",
      actor_designation: null,
      actor_office_code: "EDU",
    },
  ];
  const stagesBody = {
    current: {
      id: "s-1",
      stage: "reply_filed",
      label: "Reply filed",
      phase: "main",
      response_mode: "department",
      response_mode_label: "By the department",
      note: null,
      office_code: "EDU",
      set_by: "Edu Admin",
      set_at: "2026-10-05T10:00:00Z",
    },
    history: [],
    gaps: ["reply_due"],
  };

  function routes(d: CaseDetail, extra: Record<string, unknown> = {}) {
    return {
      "GET /me": me(),
      "GET /workflow/codes": CODES,
      [`GET ${BASE}`]: d,
      // newest first when asked (`order=desc`), as the API answers
      [`GET ${BASE}/custody`]: (call: { url: string }) => ({
        card: d.custody,
        legs: call.url.includes("order=desc") ? [...legs].reverse() : legs,
        total: 2,
        remarks_shown: true,
      }),
      [`GET ${BASE}/stages`]: stagesBody,
      ...extra,
    };
  }

  it("CustodyTab renders a DataTable with a primary cell (design portal-ui-polish, decision 15)", async () => {
    browserApi(routes(detail()));
    renderWithClient(<CustodyTab caseRef={REF} />);
    expectDataTable(await screen.findByRole("table", { name: "Movement Record" }));
  });

  it("lists the legs, hides a remark the API does not send, and shows the stage gaps", async () => {
    browserApi(routes(detail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false, next_date_report: false, next_date_correct: false, close: false, reopen: false } })));
    renderWithClient(<CustodyTab caseRef={REF} />);
    const table = await screen.findByRole("table", { name: "Movement Record" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    // newest first (design portal-screen-fixes-work, decision 13)
    expect(within(rows[1]!).getByText("comments within a week")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Not Shown")).toBeInTheDocument();
    expect(await screen.findByText("Not recorded: Reply Due")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set Stage" })).toBeNull();
  });

  it("Set stage shows only with the flag and puts 409 unchanged in words", async () => {
    const api = browserApi(
      routes(detail(), {
        [`POST ${BASE}/stages`]: json(409, { detail: { code: "unchanged", message: "the case is already at Reply filed" } }),
      }),
    );
    renderWithClient(<CustodyTab caseRef={REF} />);
    const block = await screen.findByRole("region", { name: "Stage" });
    await userEvent.click(await within(block).findByRole("button", { name: "Set Stage" }));
    const dialog = screen.getByRole("dialog", { name: "Set the Stage" });
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "Reply Filed (current)" })).toBeInTheDocument());
    expect((within(dialog).getByLabelText("Response Mode") as HTMLSelectElement).value).toBe("department");
    await userEvent.selectOptions(within(dialog).getByLabelText("Stage"), "reply_filed");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set Stage" }));
    expect(await within(dialog).findByText("the case is already at Reply filed")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ stage: "reply_filed", response_mode: "department", note: null });
  });

  it("the Movement Record reads order=desc, the highest move first; the cards' own facts grid; no mono holder; the stage note headed Note (portal-screen-fixes-work, decisions 7 and 13)", async () => {
    const withRemark = detail();
    const custody = { ...withRemark.custody!, remark: "Please prepare the parawise comments and send them back by Friday." };
    const api = browserApi(
      routes({ ...withRemark, custody } as CaseDetail, {
        [`GET ${BASE}/stages`]: { ...stagesBody, current: { ...stagesBody.current, note: "Reply filed on time." } },
      }),
    );
    renderWithClient(<CustodyTab caseRef={REF} />);
    const table = await screen.findByRole("table", { name: "Movement Record" });
    const call = api.calls.find((c) => c.path.startsWith(`${BASE}/custody`))!;
    expect(call.path).toContain("order=desc");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0]!.textContent)).toEqual(["2", "1"]);
    // the holder cells name the office, never a code in mono
    for (const r of rows) {
      const holder = within(r).getAllByRole("cell").find((c) => c.getAttribute("data-label") === "Holder" || c.hasAttribute("data-primary"));
      if (holder) expect(holder.querySelector(".mono")).toBeNull();
    }
    // the custody card: its own grid, the remark across the card
    const card = screen.getByRole("region", { name: "Journey" });
    const remark = within(card).getByText(custody.remark);
    const item = remark.closest("div")!;
    expect(item.className).toMatch(/wide/);
    expect(item.parentElement!.className).toMatch(/cardFacts/);
    // the stage card's note header reads Note, not the form's label
    const stage = screen.getByRole("region", { name: "Stage" });
    const note = await within(stage).findByText("Reply filed on time.");
    expect(note.previousElementSibling).toHaveTextContent(/^Note$/);
    expect(note.closest("div")!.className).toMatch(/wide/);
  });

  it("an unclaimed case has no custody and no actions", async () => {
    browserApi(routes(detail({ custody: null, ownership: { primary: null, watchers: [] } as CaseDetail["ownership"] })));
    renderWithClient(<CustodyTab caseRef={REF} />);
    expect(await screen.findByText("The journey begins when a department claims the case.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ notes

function note(seq: number, extra: Partial<Note> = {}): Note {
  return {
    id: `n-${seq}`,
    ref_no: `ASLMS/EDU/NOTE/2026/00000${seq}`,
    seq_no: seq,
    kind: "opinion",
    kind_label: "Opinion",
    body: `body ${seq}`,
    author: { name: "Edu Admin", designation: "Under Secretary", office_code: "EDU", role: "dept_admin" },
    created_at: "2026-10-01T10:00:00Z",
    visibility: "counsel_shared",
    attachments: [],
    supersedes: null,
    superseded_by: null,
    custody_leg_seq_no: null,
    drafted_at: null,
    can_correct: false,
    draft: false,
    ...extra,
  } as Note;
}

function docItem(id: string, extra: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id,
    ref_no: `ASLMS/EDU/DOC/2026/${id}`,
    kind: "upload",
    doc_group: "court_filing",
    doc_type: "petition",
    doc_type_label: "Petition",
    doc_date: "2026-09-01",
    description: `${id} description`,
    original_filename: `${id}.pdf`,
    mime: "application/pdf",
    size_bytes: 2048,
    page_count: 1,
    uploaded_by: { name: "Edu Admin", office_code: "EDU", designation: null },
    uploaded_at: "2026-09-01T10:00:00Z",
    office: null,
    visibility: "case_scope",
    assistant_available: false,
    sourcetrace_status: "pending",
    text_status: "extracted",
    virus_scan_status: "clean",
    archived_at: null,
    archive_reason: null,
    can_manage: false,
    ...extra,
  } as DocumentItem;
}

function draft(extra: Partial<Draft> = {}): Draft {
  return {
    id: "dr-1",
    kind: "general",
    body: "my working draft",
    visibility: "case_scope",
    supersedes: null,
    documents: [{ id: "ord-1", ref_no: null, original_filename: null, doc_type: "order", mime: "application/pdf" }],
    created_at: "2026-10-10T10:00:00Z",
    updated_at: "2026-10-10T10:00:00Z",
    draft: true,
    ...extra,
  } as Draft;
}

function noteRoutes(d: CaseDetail, notes: Note[], extra: Record<string, unknown> = {}) {
  return {
    "GET /me": me(),
    "GET /workflow/codes": CODES,
    "GET /documents/types": TYPES,
    [`GET ${BASE}`]: d,
    [`GET ${BASE}/notes`]: { items: notes, total: notes.length },
    [`GET ${BASE}/documents`]: { items: [docItem("d-1"), docItem("d-2", { archived_at: "2026-10-02T10:00:00Z" })], total: 2 },
    [`GET ${BASE}/notes/drafts`]: { items: [] },
    ...extra,
  };
}

describe("writing notes", () => {
  it("the composer says draft from note_mode, offers no upload and sends links only", async () => {
    const api = browserApi(
      noteRoutes(detail({ workflow: { note_mode: "draft", upload: true, set_stage: true, next_dates: false, next_date_report: false, next_date_correct: false, close: false, reopen: false } }), [], {
        [`POST ${BASE}/notes`]: json(201, draft({ documents: [] })),
      }),
    );
    renderWithClient(<Notes caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Write a Note" });
    expect(within(form).getByText(/This case is with you. Your notes are drafts/)).toBeInTheDocument();
    expect(within(form).queryByLabelText("Attach New Files")).toBeNull();
    expect(within(form).getByText("Notes and their attachments are internal and are never sent to the Case Assistant.")).toBeInTheDocument();
    // the drafts panel shows for the holder
    expect(await screen.findByRole("region", { name: "My Drafts" })).toBeInTheDocument();
    // archived documents are not offered as links
    await waitFor(() => expect(within(form).getByLabelText(/d-1 description/)).toBeInTheDocument());
    expect(within(form).queryByLabelText(/d-2 description/)).toBeNull();
    await userEvent.selectOptions(within(form).getByLabelText("Kind"), "general");
    await userEvent.type(within(form).getByLabelText("Note"), "draft text");
    await userEvent.click(within(form).getByLabelText(/d-1 description/));
    await userEvent.click(within(form).getByRole("button", { name: "Save Draft" }));
    // visibility is required and nothing was pre-selected
    expect(within(form).getAllByText("Required.").length).toBeGreaterThan(0);
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(form).getByLabelText(/^Shared with Counsel/));
    await userEvent.click(within(form).getByRole("button", { name: "Save Draft" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const body = api.calls.find((c) => c.method === "POST")!.body as FormData;
    expect(body.get("kind")).toBe("general");
    expect(body.get("body")).toBe("draft text");
    expect(body.get("visibility")).toBe("counsel_shared");
    expect(body.getAll("document_refs")).toEqual(["d-1"]);
    expect(body.getAll("files")).toEqual([]);
    expect(await screen.findByText("Draft saved.")).toBeInTheDocument();
  });

  it("a permanent note sends multipart with files and file_doc_types; nothing pre-selected", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const api = browserApi(
      noteRoutes(detail(), [], { [`POST ${BASE}/notes`]: json(201, note(1, { ref_no: "ASLMS/EDU/NOTE/2026/000001" })) }),
    );
    renderWithClient(<Notes caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Write a Note" });
    expect(within(form).getByText(/becomes part of the case record at once/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "My Drafts" })).toBeNull();
    for (const radio of within(form).getAllByRole("radio")) expect(radio).not.toBeChecked();
    expect((within(form).getByLabelText("Kind") as HTMLSelectElement).value).toBe("");
    const input = await within(form).findByLabelText("Attach New Files");
    await user.upload(input, [new File(["%PDF-1"], "reply.pdf", { type: "application/pdf" })]);
    await waitFor(() => expect(within(form).getByLabelText("Document type for reply.pdf")).toBeInTheDocument());
    expect((within(form).getByLabelText("Document type for reply.pdf") as HTMLSelectElement).value).toBe("correspondence");
    await user.selectOptions(within(form).getByLabelText("Document type for reply.pdf"), "office_note");
    // a wrong type is refused before sending
    await user.upload(input, [new File(["x"], "notes.txt", { type: "text/plain" })]);
    expect(within(form).getByText(/notes\.txt: This file type is not accepted/)).toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText("Kind"), "opinion");
    await user.type(within(form).getByLabelText("Note"), "final view");
    await user.click(within(form).getByLabelText(/^Everyone with the Case/));
    await user.click(within(form).getByRole("button", { name: "Add Note" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const body = api.calls.find((c) => c.method === "POST")!.body as FormData;
    expect((body.getAll("files") as File[]).map((f) => f.name)).toEqual(["reply.pdf"]);
    expect(body.getAll("file_doc_types")).toEqual(["office_note"]);
    expect(body.get("visibility")).toBe("case_scope");
    expect(await screen.findByText("Note ASLMS/EDU/NOTE/2026/000001 added.")).toBeInTheDocument();
  });

  it("Correct shows only with can_correct, fixes kind and visibility, and permanent notes have no Edit or Delete", async () => {
    const api = browserApi(
      noteRoutes(detail(), [note(1, { can_correct: true }), note(2)], {
        [`POST ${BASE}/notes`]: json(409, { detail: { code: "already_superseded", message: "x" } }),
      }),
    );
    renderWithClient(<Notes caseRef={REF} />);
    const trail = await screen.findByRole("list", { name: "Notes" });
    expect(within(trail).getAllByRole("button", { name: "Correct" })).toHaveLength(1);
    expect(within(trail).queryByRole("button", { name: /Edit|Delete/ })).toBeNull();
    await userEvent.click(within(trail).getByRole("button", { name: "Correct" }));
    const form = screen.getByRole("form", { name: "Write a Note" });
    expect(within(form).getByText("Corrects ASLMS/EDU/NOTE/2026/000001")).toBeInTheDocument();
    expect(within(form).getByLabelText("Kind")).toBeDisabled();
    expect((within(form).getByLabelText("Kind") as HTMLSelectElement).value).toBe("opinion");
    expect(within(form).getByLabelText(/^Shared with Counsel/)).toBeChecked();
    expect(within(form).getByLabelText(/^Shared with Counsel/)).toBeDisabled();
    await userEvent.type(within(form).getByLabelText("Note"), "corrected text");
    await userEvent.click(within(form).getByRole("button", { name: "Add Note" }));
    expect(await within(form).findByText("Someone corrected this note first. Correct the latest note instead.")).toBeInTheDocument();
    const body = api.calls.find((c) => c.method === "POST")!.body as FormData;
    expect(body.get("supersedes")).toBe("ASLMS/EDU/NOTE/2026/000001");
    expect(body.get("kind")).toBeNull();
    expect(body.get("visibility")).toBe("counsel_shared");
  });

  it("no composer without note_mode", async () => {
    browserApi(noteRoutes(detail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false, next_date_report: false, next_date_correct: false, close: false, reopen: false } }), [note(1)]));
    renderWithClient(<Notes caseRef={REF} />);
    await screen.findByText("body 1");
    expect(screen.queryByRole("form", { name: "Write a Note" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Correct" })).toBeNull();
  });
});

describe("the drafts panel", () => {
  function draftRoutes(extra: Record<string, unknown> = {}) {
    return noteRoutes(
      detail({ workflow: { note_mode: "draft", upload: true, set_stage: false, next_dates: false, next_date_report: false, next_date_correct: false, close: false, reopen: false }, counts: { ...detail().counts, my_drafts: 1 } }),
      [],
      { [`GET ${BASE}/notes/drafts`]: { items: [draft()] }, ...extra },
    );
  }

  it("edit sends only the changed fields, links as ids", async () => {
    const api = browserApi(draftRoutes({ "PATCH /notes/drafts/dr-1": draft({ body: "edited" }) }));
    renderWithClient(<Notes caseRef={REF} />);
    const panel = await screen.findByRole("region", { name: "My Drafts" });
    // design portal-ui-kit-fixes, decision 14: the kind first, then Draft and the visibility at the end
    const head = (await within(panel).findByText("Draft")).closest("[data-ui='item-head']") as HTMLElement;
    expect(head.firstElementChild!.firstElementChild!.tagName).toBe("STRONG");
    expect(head.lastElementChild!.textContent).toMatch(/^Draft/);
    expect(head.lastElementChild!.children).toHaveLength(2);
    await userEvent.click(await within(panel).findByRole("button", { name: "Edit" }));
    const form = within(panel).getByRole("form", { name: "Edit the Draft" });
    const text = within(form).getByLabelText("Note");
    await userEvent.clear(text);
    await userEvent.type(text, "edited");
    await userEvent.click(within(form).getByRole("button", { name: "Save Draft" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ body: "edited" }));
    await userEvent.click(await within(panel).findByRole("button", { name: "Edit" }));
    const again = within(panel).getByRole("form", { name: "Edit the Draft" });
    await waitFor(() => expect(within(again).getByLabelText(/d-1 description/)).toBeInTheDocument());
    await userEvent.click(within(again).getByLabelText(/d-1 description/));
    await userEvent.click(within(again).getByRole("button", { name: "Save Draft" }));
    await waitFor(() =>
      expect(api.calls.filter((c) => c.method === "PATCH")[1]?.body).toEqual({ document_refs: ["ord-1", "d-1"] }),
    );
  });

  it("delete asks for confirmation; draft_finalised re-reads drafts and the trail", async () => {
    const api = browserApi(
      draftRoutes({ "DELETE /notes/drafts/dr-1": json(409, { detail: { code: "draft_finalised", message: "moved" } }) }),
    );
    renderWithClient(<Notes caseRef={REF} />);
    const panel = await screen.findByRole("region", { name: "My Drafts" });
    await userEvent.click(await within(panel).findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete the Draft" });
    expect(within(dialog).getByText(/the only delete in a case's records/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);
    const before = api.calls.filter((c) => c.path === `${BASE}/notes/drafts`).length;
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(dialog).findByText("This draft became a permanent note when the case moved.")).toBeInTheDocument();
    await waitFor(() => expect(api.calls.filter((c) => c.path === `${BASE}/notes/drafts`).length).toBeGreaterThan(before));
    expect(api.calls.some((c) => c.path.startsWith(`${BASE}/notes?`) || c.path === `${BASE}/notes`)).toBe(true);
  });
});

// ------------------------------------------------------------------------------------------------ uploads and documents

describe("uploads and document actions", () => {
  function docRoutes(d: CaseDetail, items: DocumentItem[] = [], extra: Record<string, unknown> = {}) {
    return {
      "GET /me": me(),
      "GET /documents/types": TYPES,
      [`GET ${BASE}`]: d,
      [`GET ${BASE}/documents`]: (call: { url: string }) =>
        call.url.includes("group=court_filing") ? { items, total: items.length } : { items: [], total: 0 },
      ...extra,
    };
  }

  it("the panel shows only with workflow.upload and says what reaches the Case Assistant", async () => {
    browserApi(docRoutes(detail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false, next_date_report: false, next_date_correct: false, close: false, reopen: false } })));
    const { unmount } = renderWithClient(<Documents caseRef={REF} />);
    await screen.findByText("No documents.");
    expect(screen.queryByRole("form", { name: "Upload a Document" })).toBeNull();
    unmount();
    browserApi(docRoutes(detail()));
    renderWithClient(<Documents caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Upload a Document" });
    expect(within(form).getByText(/Court filings visible to the whole case or shared with counsel are sent/)).toBeInTheDocument();
    for (const radio of within(form).getAllByRole("radio")) expect(radio).not.toBeChecked();
  });

  it("refuses a .txt and an oversized file before sending", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const api = browserApi(docRoutes(detail()));
    renderWithClient(<Documents caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Upload a Document" });
    const input = await within(form).findByLabelText("File (PDF, Word or Image)");
    await waitFor(() => expect(input).toHaveAttribute("accept", ".pdf,.docx,.doc,.jpg,.jpeg,.png"));
    await user.upload(input, new File(["hello"], "notes.txt", { type: "text/plain" }));
    expect(within(form).getByText(/This file type is not accepted/)).toBeInTheDocument();
    await user.upload(input, new File(["x".repeat(51)], "big.pdf", { type: "application/pdf" }));
    expect(within(form).getByText("The file is larger than 50 bytes.")).toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Upload" }));
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
  });

  async function fillUpload(form: HTMLElement) {
    const user = userEvent.setup();
    await user.upload(await within(form).findByLabelText("File (PDF, Word or Image)"), new File(["%PDF"], "petition.pdf", { type: "application/pdf" }));
    await user.selectOptions(within(form).getByLabelText("Document Type"), "petition");
    fireEvent.change(within(form).getByLabelText("Document Date"), { target: { value: "2026-01-03" } });
    await user.type(within(form).getByLabelText("Description"), "Writ petition as filed");
    await user.click(within(form).getByLabelText(/^Everyone with the Case/));
    await user.click(within(form).getByRole("button", { name: "Upload" }));
  }

  it.each([
    ["infected", 422, "Refused: a virus was found; nothing was stored."],
    ["scanner_unavailable", 503, "The virus scanner is not available; try again in a few minutes."],
  ])("puts %s in words", async (code, status, text) => {
    browserApi(docRoutes(detail(), [], { [`POST ${BASE}/documents`]: json(status, { detail: { code, message: "x" } }) }));
    renderWithClient(<Documents caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Upload a Document" });
    await fillUpload(form);
    expect(await within(form).findByText(text)).toBeInTheDocument();
  });

  it("a duplicate links to the document already held, and a success sends the form fields", async () => {
    let answer: Response = json(409, { detail: { code: "duplicate", message: "x", existing_ref_no: "ASLMS/EDU/DOC/2026/000003" } });
    const api = browserApi(docRoutes(detail(), [], { [`POST ${BASE}/documents`]: () => answer }));
    renderWithClient(<Documents caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Upload a Document" });
    await fillUpload(form);
    expect(await within(form).findByText("Refused: this file is already on the case as ASLMS/EDU/DOC/2026/000003.")).toBeInTheDocument();
    expect(within(form).getByRole("link", { name: "Open ASLMS/EDU/DOC/2026/000003" })).toHaveAttribute(
      "href",
      "/api/backend/documents/ASLMS-EDU-DOC-2026-000003/file?disposition=inline",
    );
    const body = api.calls.find((c) => c.method === "POST")!.body as FormData;
    expect(body.get("doc_type")).toBe("petition");
    expect(body.get("doc_date")).toBe("2026-01-03");
    expect(body.get("visibility")).toBe("case_scope");
    expect(body.get("doc_group")).toBeNull();
    answer = json(201, docItem("d-9", { ref_no: "ASLMS/EDU/DOC/2026/000009" }));
  });

  it("Change visibility and Archive only on rows with can_manage; archive needs a reason; already_ingested in words", async () => {
    const api = browserApi(
      docRoutes(detail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false, next_date_report: false, next_date_correct: false, close: false, reopen: false } }), [
        docItem("d-1", { can_manage: true }),
        docItem("d-2"),
      ], {
        "PATCH /documents/d-1": json(409, { detail: { code: "already_ingested", message: "x" } }),
        "POST /documents/d-1/archive": json(200, docItem("d-1", { archived_at: "2026-10-13T10:00:00Z" })),
      }),
    );
    renderWithClient(<Documents caseRef={REF} />);
    const section = await screen.findByRole("region", { name: "Court Filings" });
    expect(within(section).getAllByRole("button", { name: "Change Visibility" })).toHaveLength(1);
    expect(within(section).getAllByRole("button", { name: "Archive" })).toHaveLength(1);
    await userEvent.click(within(section).getByRole("button", { name: "Change Visibility" }));
    const vis = screen.getByRole("dialog", { name: "Change Who May See the Document" });
    expect(within(vis).getByLabelText(/^Everyone with the Case \(current\)/)).toBeInTheDocument();
    await userEvent.click(within(vis).getByLabelText(/^Private to the Office/));
    await userEvent.click(within(vis).getByRole("button", { name: "Change Visibility" }));
    expect(
      await within(vis).findByText("This document is already in the Case Assistant, so it cannot be made private."),
    ).toBeInTheDocument();
    await userEvent.click(within(vis).getByRole("button", { name: "Cancel" }));
    await userEvent.click(within(section).getByRole("button", { name: "Archive" }));
    const arch = screen.getByRole("dialog", { name: "Archive the Document" });
    expect(within(arch).getByText(/there is no unarchive and no delete/)).toBeInTheDocument();
    await userEvent.click(within(arch).getByRole("button", { name: "Archive" }));
    expect(within(arch).getByText("Give a reason of 3 to 500 characters.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/documents/d-1/archive")).toBe(false);
    await userEvent.type(within(arch).getByLabelText("Reason"), "filed twice");
    await userEvent.click(within(arch).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.calls.find((c) => c.path === "/documents/d-1/archive")?.body).toEqual({ reason: "filed twice" }));
  });
});

// ------------------------------------------------------------------------------------------------ case alerts

function alert(extra: Partial<AlertItem> = {}): AlertItem {
  return {
    id: "a-1",
    ref_no: "ASLMS/GOA/ALR/2026/000001",
    kind: "hearing_due",
    kind_label: "Hearing due",
    severity: "critical",
    status: "open",
    title: "Hearing tomorrow",
    body: "Listed as item 5",
    due_at: "2026-10-14T04:30:00Z",
    case: null,
    ticket_ref: null,
    data: {},
    notified_at: null,
    read_at: null,
    acknowledged_by: null,
    acknowledged_at: null,
    closed_at: null,
    created_at: "2026-10-13T04:30:00Z",
    can_act: true,
    case_visible: false,
    ...extra,
    // the server's title without its case number (design portal-screen-fixes-work, decision 19); the title by default
    summary: extra.summary ?? extra.title ?? "Hearing tomorrow",
  };
}

describe("the case alerts tab", () => {
  it("shows the summary with no case link, the case being the page's own (portal-screen-fixes-work, decision 19)", async () => {
    browserApi({
      [`GET ${BASE}`]: detail(),
      [`GET ${BASE}/alerts`]: {
        items: [
          alert({
            title: "Hearing tomorrow: WP(C)/1/2026",
            summary: "Hearing tomorrow",
            case: { id: "c-1", ref_no: "ASLMS/GHC/CASE/2026/000001", cnr: null, case_no_text: "WP(C)/1/2026" },
            case_visible: true,
          }),
        ],
        total: 1,
      },
    });
    renderWithClient(<CaseAlerts caseRef={REF} />);
    const list = await screen.findByRole("list", { name: "Alerts" });
    expect(within(list).getByText("Hearing tomorrow").tagName).toBe("STRONG");
    expect(within(list).queryByText(/WP\(C\)\/1\/2026/)).toBeNull();
    expect(within(list).queryByRole("link", { name: /WP\(C\)/ })).toBeNull();
    await userEvent.click(within(list).getByRole("button", { name: "Acknowledge" }));
    expect(within(await screen.findByRole("dialog")).getByText("Hearing tomorrow: WP(C)/1/2026")).toBeInTheDocument();
  });

  it("a reader who does not work on the case is told why the list is empty", async () => {
    browserApi({ [`GET ${BASE}`]: detail({ access_basis: ["recommended"] }), [`GET ${BASE}/alerts`]: { items: [], total: 0 } });
    renderWithClient(<CaseAlerts caseRef={REF} />);
    expect(await screen.findByText("Alerts of this case are shown to the offices working on it.")).toBeInTheDocument();
  });

  it("each head starts with the kind, the severity and New badges follow, and no alert reference shows (design portal-ui-kit-fixes, decision 13)", async () => {
    browserApi({
      [`GET ${BASE}`]: detail(),
      [`GET ${BASE}/alerts`]: {
        items: [alert({ notified_at: "2026-10-13T04:30:00Z" }), alert({ id: "a-2", title: "Sent to others" })],
        total: 2,
      },
    });
    renderWithClient(<CaseAlerts caseRef={REF} />);
    const list = await screen.findByRole("list", { name: "Alerts" });
    const items = within(list).getAllByRole("listitem");
    const head = items[0]!.querySelector("[data-ui='item-head']") as HTMLElement;
    expect(head.firstElementChild!.firstElementChild!.tagName).toBe("STRONG");
    expect(head.firstElementChild!.firstElementChild!.textContent).toBe("Hearing Due");
    expect(head.lastElementChild!.textContent).toMatch(/^Critical.*New/);
    expect(items[0]!.textContent).not.toContain("ASLMS/GOA/ALR/2026/000001");
    // an alert that never reached the reader is not "New" for them
    expect(within(items[1]!.querySelector("[data-ui='item-head']") as HTMLElement).queryByText("New")).toBeNull();
  });

  it("Acknowledge and Done by can_act and status; the status filter is sent", async () => {
    const api = browserApi({
      [`GET ${BASE}`]: detail(),
      [`GET ${BASE}/alerts`]: {
        items: [
          alert(),
          alert({ id: "a-2", status: "acknowledged", severity: "high", title: "Reply due", acknowledged_by: { id: "u-1", full_name: "Edu Admin" }, acknowledged_at: "2026-10-13T05:00:00Z" }),
          alert({ id: "a-3", can_act: false, severity: "normal", title: "Seen by others" }),
        ],
        total: 3,
      },
      "POST /alerts/a-1/acknowledge": json(409, { detail: { code: "not_open", message: "x" } }),
    });
    renderWithClient(<CaseAlerts caseRef={REF} />);
    const list = await screen.findByRole("list", { name: "Alerts" });
    const items = within(list).getAllByRole("listitem");
    expect(within(items[0]!).getByText("Critical")).toBeInTheDocument();
    expect(within(items[0]!).getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(within(items[0]!).getByRole("button", { name: "Done" })).toBeInTheDocument();
    expect(within(items[1]!).queryByRole("button", { name: "Acknowledge" })).toBeNull();
    expect(within(items[1]!).getByRole("button", { name: "Done" })).toBeInTheDocument();
    expect(within(items[1]!).getByText(/Acknowledged by Edu Admin/)).toBeInTheDocument();
    expect(within(items[2]!).queryByRole("button")).toBeNull();
    await userEvent.click(within(items[0]!).getByRole("button", { name: "Acknowledge" }));
    const dialog = screen.getByRole("dialog", { name: "Acknowledge the Alert" });
    await userEvent.type(within(dialog).getByLabelText("Note (Optional)"), "seen");
    await userEvent.click(within(dialog).getByRole("button", { name: "Acknowledge" }));
    expect(await within(dialog).findByText("Only an open alert can be acknowledged. The list has been read again.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ note: "seen" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await userEvent.selectOptions(screen.getByLabelText("Show"), "all");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("status=all"))).toBe(true));
  });
});

describe("Close Case and Reopen Case (design close-case, decision 19)", () => {
  beforeEach(() => resetNav(BASE));

  const closure = {
    closed_at: "2026-11-02T05:00:00Z",
    closed_as: "holder" as const,
    closed_by: { name: "Officer One", designation: "SO", office_code: "EDU" },
    office_code: "EDU",
    note_ref_no: "ASLMS/EDU/NOTE/2026/000009",
    disposal_date: "2026-10-20",
    reopened_at: null,
    reopen_kind: null,
    reopened_status: null,
    reopened_by: null,
    reopen_note_ref_no: null,
  };

  it("the remark is required and counted, the drafts line shows only with drafts, and it posts /close", async () => {
    const api = browserApi({
      [`POST ${BASE}/close`]: { closure, note_ref_no: closure.note_ref_no, finalised_notes: [], card: card({ closed: true, can_send: false }), visible: true },
    });
    const done: string[] = [];
    const { unmount } = renderWithClient(<CloseCaseDialog open caseRef={REF} drafts={0} onClose={() => undefined} onDone={(t) => done.push(t)} />);
    const dialog = screen.getByRole("dialog", { name: "Close This Case" });
    expect(within(dialog).queryByText("Your drafts on this case become permanent notes.")).toBeNull();
    expect(within(dialog).getByText(/Closing ends this case's movement/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Close Case" }));
    expect(within(dialog).getByText("Give a reason of 3 to 2,000 characters.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByLabelText("Why Is This Case Being Closed?"), "Complied with the order.");
    expect(within(dialog).getByText("24 / 2000 characters")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Close Case" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ remark: "Complied with the order." }));
    await waitFor(() => expect(done).toEqual(["Case closed. The closing remark is note ASLMS/EDU/NOTE/2026/000009."]));
    unmount();
    renderWithClient(<CloseCaseDialog open caseRef={REF} drafts={2} onClose={() => undefined} onDone={() => undefined} />);
    expect(screen.getByText("Your drafts on this case become permanent notes.")).toBeInTheDocument();
  });

  it("a closer who can no longer open the case goes to With Me", async () => {
    browserApi({ [`POST ${BASE}/close`]: { closure, note_ref_no: closure.note_ref_no, finalised_notes: [], card: null, visible: false } });
    renderWithClient(<CloseCaseDialog open caseRef={REF} drafts={0} onClose={() => undefined} onDone={() => undefined} />);
    await userEvent.type(screen.getByLabelText("Why Is This Case Being Closed?"), "Nothing more to do.");
    await userEvent.click(screen.getByRole("button", { name: "Close Case" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/inbox/with-me"));
  });

  it("every refusal shows its plain words", async () => {
    const texts: Record<string, string> = {
      case_closed: "This case is closed. It opens again when the court's status changes or when it is reopened.",
      not_disposed: "The court has not disposed of this case, so it cannot be closed.",
      already_closed: "This case is already closed.",
      not_closer:
        "Only an officer of the owning department who has the case, the Head of Department or the Super Administrator can close it.",
      transfer_open: "A transfer of this case is waiting for a decision. Decide or withdraw it first.",
      not_closed: "This case is not closed.",
      not_reopener: "Only the owning department or the Super Administrator can reopen this case.",
    };
    for (const [code, text] of Object.entries(texts)) {
      browserApi({
        [`POST ${BASE}/close`]: json(409, { detail: { code, message: "x" } }),
        [`POST ${BASE}/reopen`]: json(409, { detail: { code, message: "x" } }),
      });
      const close = code === "not_closed" || code === "not_reopener";
      const { unmount } = renderWithClient(
        close ? (
          <ReopenCaseDialog open caseRef={REF} onClose={() => undefined} onDone={() => undefined} />
        ) : (
          <CloseCaseDialog open caseRef={REF} drafts={0} onClose={() => undefined} onDone={() => undefined} />
        ),
      );
      const field = close ? "Why Is This Case Being Reopened?" : "Why Is This Case Being Closed?";
      await userEvent.type(screen.getByLabelText(field), "a reason");
      await userEvent.click(screen.getByRole("button", { name: close ? "Reopen Case" : "Close Case" }));
      expect(await screen.findByText(text)).toBeInTheDocument();
      unmount();
    }
  });

  it("Reopen: the reason is required, it posts /reopen and the flash names the note", async () => {
    const api = browserApi({
      [`POST ${BASE}/reopen`]: {
        closure: { ...closure, reopened_at: "2026-11-03T05:00:00Z", reopen_kind: "manual", reopened_status: "disposed", reopen_note_ref_no: "ASLMS/EDU/NOTE/2026/000010" },
        note_ref_no: "ASLMS/EDU/NOTE/2026/000010",
        card: card({ holder_user: null, pending_action: "examine" }),
        visible: true,
      },
    });
    const done: string[] = [];
    renderWithClient(<ReopenCaseDialog open caseRef={REF} onClose={() => undefined} onDone={(t) => done.push(t)} />);
    const dialog = screen.getByRole("dialog", { name: "Reopen This Case" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Reopen Case" }));
    expect(within(dialog).getByText("Give a reason of 3 to 2,000 characters.")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Why Is This Case Being Reopened?"), "Compliance is due again.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reopen Case" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ reason: "Compliance is due again." }));
    await waitFor(() => expect(done).toEqual(["Case reopened. The reopening remark is note ASLMS/EDU/NOTE/2026/000010."]));
  });
});
