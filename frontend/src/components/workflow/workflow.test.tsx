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
import { CustodyActions } from "./CustodyDialogs";
import { CustodyTab } from "./CustodyTab";

const REF = "ASLMS-GOA-CASE-2026-000001";
const BASE = `/cases/${REF}`;
const READ: Permission[] = ["cases.view_scope", "documents.view", "documents.download", "notes.add", "documents.upload"];

function card(extra: Partial<CustodyCard> = {}): CustodyCard {
  return {
    due_soon: false,
    can_recall: false,
    can_send: true,
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
  return {
    id: "c-1",
    ref_no: "ASLMS/GOA/CASE/2026/000001",
    access_basis: ["owner"],
    counts: { documents: 0, hearings: 0, links: 0, listings: 0, my_drafts: 0, notes: 0, orders: 0, timeline: 0 },
    workflow: { note_mode: "permanent", upload: true, set_stage: true, next_dates: false },
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
    expect(screen.getByRole("button", { name: "Send case" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recall case" })).toBeInTheDocument();
    unmount();
    renderWithClient(<CustodyActions caseRef={REF} detail={detail()} card={card({ can_send: false, can_recall: false })} />);
    expect(screen.queryByRole("button", { name: /Send case|Recall case/ })).toBeNull();
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
    await userEvent.click(screen.getByRole("button", { name: "Send case" }));
    const dialog = screen.getByRole("dialog", { name: "Send the case" });
    // step 1: who receives it (the stepper says where we are)
    expect(within(dialog).getByText("Step 1 of 3 · Who receives it")).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "HEALTH — Health" })).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).getByText("Required.")).toBeInTheDocument();
    expect(within(dialog).getByText("Step 1 of 3 · Who receives it")).toBeInTheDocument();
    await userEvent.selectOptions(within(dialog).getByLabelText("Department"), "HEALTH");
    await waitFor(() => expect(within(dialog).getByRole("radio", { name: /Health Off/ })).toBeInTheDocument());
    await userEvent.type(within(dialog).getByLabelText("Search by name or designation"), "dir");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("department=HEALTH") && c.url.includes("q=dir"))).toBe(true));
    // the people are cards with their initials
    expect(within(dialog).getAllByText("HO").length).toBeGreaterThan(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).getByText("Choose the person who receives the case.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("radio", { name: /Health Off/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    // step 2: what they should do — the sendable actions only, nothing pre-selected; the stage with the flag
    expect(within(dialog).getByText("Step 2 of 3 · What they should do")).toBeInTheDocument();
    const action = within(dialog).getByLabelText("Pending action") as HTMLSelectElement;
    await waitFor(() => expect(within(action).getByRole("option", { name: "Parawise comments" })).toBeInTheDocument());
    expect(action.value).toBe("");
    expect(within(action).queryByRole("option", { name: "None" })).toBeNull();
    expect(within(dialog).getByLabelText("Stage (optional)")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).getByText("Required.")).toBeInTheDocument();
    await userEvent.selectOptions(action, "parawise_comments");
    // Back keeps what was entered
    await userEvent.click(within(dialog).getByRole("button", { name: "Back" }));
    expect(within(dialog).getByRole("radio", { name: /Health Off/ })).toBeChecked();
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect((within(dialog).getByLabelText("Pending action") as HTMLSelectElement).value).toBe("parawise_comments");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    // step 3: the remark is required; the drafts notice and the summary line
    expect(within(dialog).getByText("Step 3 of 3 · Remark and confirm")).toBeInTheDocument();
    expect(within(dialog).getByText("Your 2 draft notes become permanent notes of the case when you send.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Send case" }));
    expect(within(dialog).getByText("Give a remark of 3 to 2,000 characters.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByLabelText("Remark"), "please comment");
    expect(within(dialog).getByText("Send to Health Off, Under Secretary, HEALTH — Parawise comments")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Send case" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
        to_membership: "m-h1",
        pending_action: "parawise_comments",
        due_date: null,
        remark: "please comment",
        stage: null,
      }),
    );
    expect(await screen.findByText("Case sent to Health Off, Under Secretary, HEALTH.")).toBeInTheDocument();
  });

  it("offers no stage without workflow.set_stage", async () => {
    browserApi({
      "GET /workflow/codes": CODES,
      "GET /custody/recipients": (call: { url: string }) => (call.url.includes("department=HEALTH") ? HEALTH_PEOPLE : DEPTS),
    });
    renderWithClient(
      <CustodyActions caseRef={REF} detail={detail({ workflow: { note_mode: "draft", upload: true, set_stage: false, next_dates: false } })} card={card()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Send case" }));
    const dialog = screen.getByRole("dialog", { name: "Send the case" });
    await chooseHealthOff(dialog);
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "Examine" })).toBeInTheDocument());
    expect(within(dialog).queryByLabelText("Stage (optional)")).toBeNull();
    await userEvent.selectOptions(within(dialog).getByLabelText("Pending action"), "examine");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).queryByText(/draft notes? become/)).toBeNull();
  });

  async function chooseHealthOff(dialog: HTMLElement) {
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "HEALTH — Health" })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog).getByLabelText("Department"), "HEALTH");
    await waitFor(() => expect(within(dialog).getByRole("radio", { name: /Health Off/ })).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("radio", { name: /Health Off/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
  }

  async function fillAndSend(dialog: HTMLElement) {
    await chooseHealthOff(dialog);
    await userEvent.selectOptions(within(dialog).getByLabelText("Pending action"), "examine");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    await userEvent.type(within(dialog).getByLabelText("Remark"), "over to you");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send case" }));
  }

  it("a card: null answer goes to Cases → Sent by me with the notice and the finalised notes", async () => {
    browserApi({
      "GET /workflow/codes": CODES,
      "GET /custody/recipients": (call: { url: string }) => (call.url.includes("department=HEALTH") ? HEALTH_PEOPLE : DEPTS),
      [`POST ${BASE}/custody/send`]: moved(null, ["ASLMS/HEALTH/NOTE/2026/000001"]),
    });
    renderWithClient(<CustodyActions caseRef={REF} detail={detail()} card={card()} />);
    await userEvent.click(screen.getByRole("button", { name: "Send case" }));
    await fillAndSend(screen.getByRole("dialog", { name: "Send the case" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/cases/sent"));
    expect(sessionStorage.getItem("aslms.flash")).toBe(
      "Case sent to Health Off, Under Secretary, HEALTH. It is no longer with you. Made permanent: ASLMS/HEALTH/NOTE/2026/000001",
    );
  });

  it("sending the case away does not fetch it again before Cases → Sent by me (no not-found flash)", async () => {
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
    await userEvent.click(screen.getByRole("button", { name: "Send case" }));
    await fillAndSend(screen.getByRole("dialog", { name: "Send the case" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/cases/sent"));
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
    await userEvent.click(screen.getByRole("button", { name: "Send case" }));
    await fillAndSend(screen.getByRole("dialog", { name: "Send the case" }));
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
    await userEvent.click(screen.getByRole("button", { name: "Send case" }));
    const dialog = screen.getByRole("dialog", { name: "Send the case" });
    await fillAndSend(dialog);
    expect(await within(dialog).findByText("the case is already with that officer")).toBeInTheDocument();
    answer = json(403, { detail: { code: "not_in_control", message: "x" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send case" }));
    expect(
      await within(dialog).findByText("The case is not with you, and you do not control the office it is with."),
    ).toBeInTheDocument();
  });

  it("the recall dialog names the holder and needs a remark", async () => {
    const api = browserApi({ [`POST ${BASE}/custody/recall`]: moved(card({ can_recall: false })) });
    renderWithClient(<CustodyActions caseRef={REF} detail={detail()} card={card({ can_send: false, can_recall: true })} />);
    await userEvent.click(screen.getByRole("button", { name: "Recall case" }));
    const dialog = screen.getByRole("dialog", { name: "Recall the case" });
    expect(within(dialog).getByText("The case is with Officer One, SO, EDU-DSE — Secondary Education.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Recall case" }));
    expect(within(dialog).getByText("Give a remark of 3 to 2,000 characters.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByLabelText("Remark"), "needed back");
    await userEvent.click(within(dialog).getByRole("button", { name: "Recall case" }));
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
      [`GET ${BASE}/custody`]: { card: d.custody, legs, total: 2 },
      [`GET ${BASE}/stages`]: stagesBody,
      ...extra,
    };
  }

  it("CustodyTab renders a DataTable with a primary cell (design portal-ui-polish, decision 15)", async () => {
    browserApi(routes(detail()));
    renderWithClient(<CustodyTab caseRef={REF} />);
    expectDataTable(await screen.findByRole("table", { name: "Movement record" }));
  });

  it("lists the legs, hides a remark the API does not send, and shows the stage gaps", async () => {
    browserApi(routes(detail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false } })));
    renderWithClient(<CustodyTab caseRef={REF} />);
    const table = await screen.findByRole("table", { name: "Movement record" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]!).getByText("Not shown")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("comments within a week")).toBeInTheDocument();
    expect(await screen.findByText("Not recorded: Reply due")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set stage" })).toBeNull();
  });

  it("Set stage shows only with the flag and puts 409 unchanged in words", async () => {
    const api = browserApi(
      routes(detail(), {
        [`POST ${BASE}/stages`]: json(409, { detail: { code: "unchanged", message: "the case is already at Reply filed" } }),
      }),
    );
    renderWithClient(<CustodyTab caseRef={REF} />);
    const block = await screen.findByRole("region", { name: "Stage" });
    await userEvent.click(await within(block).findByRole("button", { name: "Set stage" }));
    const dialog = screen.getByRole("dialog", { name: "Set the stage" });
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "Reply filed (current)" })).toBeInTheDocument());
    expect((within(dialog).getByLabelText("Response mode") as HTMLSelectElement).value).toBe("department");
    await userEvent.selectOptions(within(dialog).getByLabelText("Stage"), "reply_filed");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set stage" }));
    expect(await within(dialog).findByText("the case is already at Reply filed")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ stage: "reply_filed", response_mode: "department", note: null });
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
      noteRoutes(detail({ workflow: { note_mode: "draft", upload: true, set_stage: true, next_dates: false } }), [], {
        [`POST ${BASE}/notes`]: json(201, draft({ documents: [] })),
      }),
    );
    renderWithClient(<Notes caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Write a note" });
    expect(within(form).getByText(/This case is with you. Your notes are drafts/)).toBeInTheDocument();
    expect(within(form).queryByLabelText("Attach new files")).toBeNull();
    expect(within(form).getByText("Notes and their attachments are internal and are never sent to the Case Assistant.")).toBeInTheDocument();
    // the drafts panel shows for the holder
    expect(await screen.findByRole("region", { name: "My drafts" })).toBeInTheDocument();
    // archived documents are not offered as links
    await waitFor(() => expect(within(form).getByLabelText(/d-1 description/)).toBeInTheDocument());
    expect(within(form).queryByLabelText(/d-2 description/)).toBeNull();
    await userEvent.selectOptions(within(form).getByLabelText("Kind"), "general");
    await userEvent.type(within(form).getByLabelText("Note"), "draft text");
    await userEvent.click(within(form).getByLabelText(/d-1 description/));
    await userEvent.click(within(form).getByRole("button", { name: "Save draft" }));
    // visibility is required and nothing was pre-selected
    expect(within(form).getAllByText("Required.").length).toBeGreaterThan(0);
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(form).getByLabelText(/^Shared with counsel/));
    await userEvent.click(within(form).getByRole("button", { name: "Save draft" }));
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
    const form = await screen.findByRole("form", { name: "Write a note" });
    expect(within(form).getByText(/becomes part of the case record at once/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "My drafts" })).toBeNull();
    for (const radio of within(form).getAllByRole("radio")) expect(radio).not.toBeChecked();
    expect((within(form).getByLabelText("Kind") as HTMLSelectElement).value).toBe("");
    const input = await within(form).findByLabelText("Attach new files");
    await user.upload(input, [new File(["%PDF-1"], "reply.pdf", { type: "application/pdf" })]);
    await waitFor(() => expect(within(form).getByLabelText("Document type for reply.pdf")).toBeInTheDocument());
    expect((within(form).getByLabelText("Document type for reply.pdf") as HTMLSelectElement).value).toBe("correspondence");
    await user.selectOptions(within(form).getByLabelText("Document type for reply.pdf"), "office_note");
    // a wrong type is refused before sending
    await user.upload(input, [new File(["x"], "notes.txt", { type: "text/plain" })]);
    expect(within(form).getByText(/notes\.txt: This file type is not accepted/)).toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText("Kind"), "opinion");
    await user.type(within(form).getByLabelText("Note"), "final view");
    await user.click(within(form).getByLabelText(/^Everyone with the case/));
    await user.click(within(form).getByRole("button", { name: "Add note" }));
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
    const form = screen.getByRole("form", { name: "Write a note" });
    expect(within(form).getByText("Corrects ASLMS/EDU/NOTE/2026/000001")).toBeInTheDocument();
    expect(within(form).getByLabelText("Kind")).toBeDisabled();
    expect((within(form).getByLabelText("Kind") as HTMLSelectElement).value).toBe("opinion");
    expect(within(form).getByLabelText(/^Shared with counsel/)).toBeChecked();
    expect(within(form).getByLabelText(/^Shared with counsel/)).toBeDisabled();
    await userEvent.type(within(form).getByLabelText("Note"), "corrected text");
    await userEvent.click(within(form).getByRole("button", { name: "Add note" }));
    expect(await within(form).findByText("Someone corrected this note first. Correct the latest note instead.")).toBeInTheDocument();
    const body = api.calls.find((c) => c.method === "POST")!.body as FormData;
    expect(body.get("supersedes")).toBe("ASLMS/EDU/NOTE/2026/000001");
    expect(body.get("kind")).toBeNull();
    expect(body.get("visibility")).toBe("counsel_shared");
  });

  it("no composer without note_mode", async () => {
    browserApi(noteRoutes(detail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false } }), [note(1)]));
    renderWithClient(<Notes caseRef={REF} />);
    await screen.findByText("body 1");
    expect(screen.queryByRole("form", { name: "Write a note" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Correct" })).toBeNull();
  });
});

describe("the drafts panel", () => {
  function draftRoutes(extra: Record<string, unknown> = {}) {
    return noteRoutes(
      detail({ workflow: { note_mode: "draft", upload: true, set_stage: false, next_dates: false }, counts: { ...detail().counts, my_drafts: 1 } }),
      [],
      { [`GET ${BASE}/notes/drafts`]: { items: [draft()] }, ...extra },
    );
  }

  it("edit sends only the changed fields, links as ids", async () => {
    const api = browserApi(draftRoutes({ "PATCH /notes/drafts/dr-1": draft({ body: "edited" }) }));
    renderWithClient(<Notes caseRef={REF} />);
    const panel = await screen.findByRole("region", { name: "My drafts" });
    await userEvent.click(await within(panel).findByRole("button", { name: "Edit" }));
    const form = within(panel).getByRole("form", { name: "Edit the draft" });
    const text = within(form).getByLabelText("Note");
    await userEvent.clear(text);
    await userEvent.type(text, "edited");
    await userEvent.click(within(form).getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ body: "edited" }));
    await userEvent.click(await within(panel).findByRole("button", { name: "Edit" }));
    const again = within(panel).getByRole("form", { name: "Edit the draft" });
    await waitFor(() => expect(within(again).getByLabelText(/d-1 description/)).toBeInTheDocument());
    await userEvent.click(within(again).getByLabelText(/d-1 description/));
    await userEvent.click(within(again).getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(api.calls.filter((c) => c.method === "PATCH")[1]?.body).toEqual({ document_refs: ["ord-1", "d-1"] }),
    );
  });

  it("delete asks for confirmation; draft_finalised re-reads drafts and the trail", async () => {
    const api = browserApi(
      draftRoutes({ "DELETE /notes/drafts/dr-1": json(409, { detail: { code: "draft_finalised", message: "moved" } }) }),
    );
    renderWithClient(<Notes caseRef={REF} />);
    const panel = await screen.findByRole("region", { name: "My drafts" });
    await userEvent.click(await within(panel).findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete the draft" });
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
    browserApi(docRoutes(detail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false } })));
    const { unmount } = renderWithClient(<Documents caseRef={REF} />);
    await screen.findByText("No documents.");
    expect(screen.queryByRole("form", { name: "Upload a document" })).toBeNull();
    unmount();
    browserApi(docRoutes(detail()));
    renderWithClient(<Documents caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Upload a document" });
    expect(within(form).getByText(/Court filings visible to the whole case or shared with counsel are sent/)).toBeInTheDocument();
    for (const radio of within(form).getAllByRole("radio")) expect(radio).not.toBeChecked();
  });

  it("refuses a .txt and an oversized file before sending", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const api = browserApi(docRoutes(detail()));
    renderWithClient(<Documents caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Upload a document" });
    const input = await within(form).findByLabelText("File (PDF, Word or image)");
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
    await user.upload(await within(form).findByLabelText("File (PDF, Word or image)"), new File(["%PDF"], "petition.pdf", { type: "application/pdf" }));
    await user.selectOptions(within(form).getByLabelText("Document type"), "petition");
    fireEvent.change(within(form).getByLabelText("Document date"), { target: { value: "2026-01-03" } });
    await user.type(within(form).getByLabelText("Description"), "Writ petition as filed");
    await user.click(within(form).getByLabelText(/^Everyone with the case/));
    await user.click(within(form).getByRole("button", { name: "Upload" }));
  }

  it.each([
    ["infected", 422, "Refused: a virus was found; nothing was stored."],
    ["scanner_unavailable", 503, "The virus scanner is not available; try again in a few minutes."],
  ])("puts %s in words", async (code, status, text) => {
    browserApi(docRoutes(detail(), [], { [`POST ${BASE}/documents`]: json(status, { detail: { code, message: "x" } }) }));
    renderWithClient(<Documents caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Upload a document" });
    await fillUpload(form);
    expect(await within(form).findByText(text)).toBeInTheDocument();
  });

  it("a duplicate links to the document already held, and a success sends the form fields", async () => {
    let answer: Response = json(409, { detail: { code: "duplicate", message: "x", existing_ref_no: "ASLMS/EDU/DOC/2026/000003" } });
    const api = browserApi(docRoutes(detail(), [], { [`POST ${BASE}/documents`]: () => answer }));
    renderWithClient(<Documents caseRef={REF} />);
    const form = await screen.findByRole("form", { name: "Upload a document" });
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
      docRoutes(detail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false } }), [
        docItem("d-1", { can_manage: true }),
        docItem("d-2"),
      ], {
        "PATCH /documents/d-1": json(409, { detail: { code: "already_ingested", message: "x" } }),
        "POST /documents/d-1/archive": json(200, docItem("d-1", { archived_at: "2026-10-13T10:00:00Z" })),
      }),
    );
    renderWithClient(<Documents caseRef={REF} />);
    const section = await screen.findByRole("region", { name: "Court filings" });
    expect(within(section).getAllByRole("button", { name: "Change visibility" })).toHaveLength(1);
    expect(within(section).getAllByRole("button", { name: "Archive" })).toHaveLength(1);
    await userEvent.click(within(section).getByRole("button", { name: "Change visibility" }));
    const vis = screen.getByRole("dialog", { name: "Change who may see the document" });
    expect(within(vis).getByLabelText(/^Everyone with the case \(current\)/)).toBeInTheDocument();
    await userEvent.click(within(vis).getByLabelText(/^Private to the office/));
    await userEvent.click(within(vis).getByRole("button", { name: "Change visibility" }));
    expect(
      await within(vis).findByText("This document is already in the Case Assistant, so it cannot be made private."),
    ).toBeInTheDocument();
    await userEvent.click(within(vis).getByRole("button", { name: "Cancel" }));
    await userEvent.click(within(section).getByRole("button", { name: "Archive" }));
    const arch = screen.getByRole("dialog", { name: "Archive the document" });
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
  };
}

describe("the case alerts tab", () => {
  it("a reader who does not work on the case is told why the list is empty", async () => {
    browserApi({ [`GET ${BASE}`]: detail({ access_basis: ["recommended"] }), [`GET ${BASE}/alerts`]: { items: [], total: 0 } });
    renderWithClient(<CaseAlerts caseRef={REF} />);
    expect(await screen.findByText("Alerts of this case are shown to the offices working on it.")).toBeInTheDocument();
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
    const dialog = screen.getByRole("dialog", { name: "Acknowledge the alert" });
    await userEvent.type(within(dialog).getByLabelText("Note (optional)"), "seen");
    await userEvent.click(within(dialog).getByRole("button", { name: "Acknowledge" }));
    expect(await within(dialog).findByText("Only an open alert can be acknowledged. The list has been read again.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ note: "seen" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await userEvent.selectOptions(screen.getByLabelText("Show"), "all");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("status=all"))).toBe(true));
  });
});
