import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CaseDetail, CustodyCard, CustodyHistory, CustodyLeg, Note } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, makeMe, renderWithClient, type BrowserCall } from "@/test/render";

import { CaseFrame } from "./CaseFrame";
import { RemarksPanel } from "./Remarks";

const REF = "ASLMS-GOA-CASE-2026-000001";
const BASE = `/cases/${REF}`;

function card(extra: Partial<CustodyCard> = {}): CustodyCard {
  return {
    due_soon: false,
    can_recall: false,
    can_send: true,
    due_date: null,
    holder_office: { code: "EDU", name: "Education" },
    holder_user: { id: "u-1", full_name: "Anita Sharma", designation: "Under Secretary" },
    leg_seq_no: 3,
    overdue: false,
    overdue_days: 0,
    pending_action: "examine",
    pending_action_label: "Examine",
    reason: "sent",
    remark: null,
    sent_by: null,
    since: "2026-10-20T10:00:00Z",
    ...extra,
  };
}

function leg(seq: number, extra: Partial<CustodyLeg> = {}): CustodyLeg {
  return {
    seq_no: seq,
    holder_office: { code: "EDU-DSE", name: "Secondary Education" },
    holder_user: { id: `u-${seq}`, full_name: `Officer ${seq}` },
    holder_designation: "Section Officer",
    reason: "sent",
    reason_label: "Sent",
    pending_action: "parawise_comments",
    pending_action_label: "Parawise comments",
    due_date: "2026-11-05",
    remark: `Line one of remark ${seq}\nline two\nline three\nline four\nline five\nline six\nline seven`,
    started_at: "2026-10-20T10:00:00Z",
    actor_name: "Edu Head",
    actor_designation: "Joint Secretary",
    actor_office_code: "EDU",
    ...extra,
  };
}

function note(seq: number, extra: Partial<Note> = {}): Note {
  return {
    id: `n-${seq}`,
    ref_no: `ASLMS/EDU/NOTE/2026/00000${seq}`,
    seq_no: seq,
    kind: "remark",
    kind_label: "Remark",
    body: `Body of note ${seq}`,
    author: { name: `Author ${seq}`, designation: "Under Secretary", office_code: "EDU", role: "dept_officer" },
    created_at: `2026-10-0${seq}T10:00:00Z`,
    visibility: "case_scope",
    attachments: [],
    supersedes: null,
    superseded_by: null,
    custody_leg_seq_no: null,
    drafted_at: null,
    can_correct: false,
    draft: false,
    ...extra,
  } as unknown as Note;
}

const CODES = {
  note_kinds: [
    { code: "file_noting", label: "Office note", selectable: true },
    { code: "remark", label: "Remark", selectable: true },
    { code: "correction", label: "Correction", selectable: false },
  ],
  pending_actions: [],
  stages: [],
  response_modes: [],
  custody_reasons: [],
  limits: { note_max_chars: 4000, attachments_max_files: 5, note_drafts_max: 10 },
};

const C = { counts: { notes: 3 } } as unknown as CaseDetail;

function history(legs: CustodyLeg[], total: number, remarks_shown = true): CustodyHistory {
  return { card: card(), legs, total, remarks_shown };
}

beforeEach(() => resetNav(BASE));

describe("the remarks history (case-workspace-admin, decision 15)", () => {
  it("Remarks: newest first, who to whom, when, the action asked, the due date and the full remark", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      [`GET ${BASE}/custody`]: history(
        [
          leg(3),
          leg(2, { reason: "recalled", reason_label: "Recalled", due_date: null, remark: null }),
          leg(1, { reason: "claimed", reason_label: "Claimed", actor_designation: null, actor_name: null, actor_office_code: "EDU" }),
        ],
        3,
      ),
    });
    renderWithClient(<RemarksPanel caseRef={REF} c={C} open onClose={() => {}} />);
    const panel = await screen.findByRole("dialog", { name: "Remarks and Notes" });
    expect(panel).toHaveAttribute("data-panel", "wide");
    expect(await within(panel).findByRole("tab", { name: "Remarks (3)" })).toHaveAttribute("aria-selected", "true");
    const list = within(panel).getByRole("list", { name: "Remarks (3)" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((li) => li.querySelector("[data-lead='date']"))).not.toContain(null);
    expect(within(items[0]!).getByText("Sent by Joint Secretary, EDU to Section Officer, Secondary Education")).toBeInTheDocument();
    expect(within(items[0]!).getByText("Action asked: Parawise comments")).toBeInTheDocument();
    expect(within(items[0]!).getByText("Due by: 5 Nov 2026")).toBeInTheDocument();
    // the full remark, never clamped: all seven lines in one pre-wrapped block
    expect(within(items[0]!).getByText(/Line one of remark 3[\s\S]*line seven/)).toBeInTheDocument();
    expect(within(items[1]!).getByText("Recalled by Joint Secretary, EDU")).toBeInTheDocument();
    expect(within(items[1]!).getByText("No due date")).toBeInTheDocument();
    expect(within(items[1]!).queryByText(/Line one/)).toBeNull();
    expect(within(items[2]!).getByText("Claimed by EDU — With Section Officer, Secondary Education (you)")).toBeInTheDocument();
    expect(within(panel).queryByText("Remarks are shown only to the people working on the case.")).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Show More" })).toBeNull();
  });

  it("without remarks for the caller the panel says so once and lists the movements", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all"]),
      [`GET ${BASE}/custody`]: history([leg(2, { remark: null }), leg(1, { remark: null })], 2, false),
    });
    renderWithClient(<RemarksPanel caseRef={REF} c={C} open onClose={() => {}} />);
    const panel = await screen.findByRole("dialog", { name: "Remarks and Notes" });
    expect(await within(panel).findAllByText("Remarks are shown only to the people working on the case.")).toHaveLength(1);
    expect(within(panel).getAllByText(/^Sent by/)).toHaveLength(2);
  });

  it("Show more pages 50 at a time from the newest", async () => {
    const page = (offset: number, n: number) => Array.from({ length: n }, (_, i) => leg(60 - offset - i, { remark: null }));
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      [`GET ${BASE}/custody`]: (call: BrowserCall) => {
        const offset = Number(new URL(call.url, "http://x").searchParams.get("offset"));
        return history(offset === 0 ? page(0, 50) : page(50, 10), 60);
      },
    });
    renderWithClient(<RemarksPanel caseRef={REF} c={C} open onClose={() => {}} />);
    const panel = await screen.findByRole("dialog", { name: "Remarks and Notes" });
    await waitFor(() => expect(within(panel).getAllByText(/^Sent by/)).toHaveLength(50));
    await userEvent.click(within(panel).getByRole("button", { name: "Show More" }));
    await waitFor(() => expect(within(panel).getAllByText(/^Sent by/)).toHaveLength(60));
    expect(within(panel).queryByRole("button", { name: "Show More" })).toBeNull();
    const urls = api.calls.filter((c) => c.path.startsWith(`${BASE}/custody`)).map((c) => c.path);
    expect(urls).toEqual([`${BASE}/custody?order=desc&limit=50&offset=0`, `${BASE}/custody?order=desc&limit=50&offset=50`]);
  });

  it("Notes: in seq_no order with corrected notes, the kind filter passes kind", async () => {
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /workflow/codes": CODES,
      [`GET ${BASE}/custody`]: history([], 0),
      [`GET ${BASE}/notes`]: (call: BrowserCall) =>
        call.path.includes("kind=file_noting")
          ? { items: [note(2, { kind: "file_noting", kind_label: "Office note" })], total: 1 }
          : { items: [note(1), note(2, { kind: "file_noting", kind_label: "Office note" }), note(3)], total: 3 },
    });
    renderWithClient(<RemarksPanel caseRef={REF} c={C} open onClose={() => {}} />);
    const panel = await screen.findByRole("dialog", { name: "Remarks and Notes" });
    await userEvent.click(within(panel).getByRole("tab", { name: "Notes (3)" }));
    const list = await within(panel).findByRole("list", { name: "Notes (3)" });
    expect(within(list).getAllByText(/^Body of note/).map((n) => n.textContent)).toEqual(["Body of note 1", "Body of note 2", "Body of note 3"]);
    const first = within(list).getAllByRole("listitem")[0]!;
    expect(within(first).getByText("Under Secretary, EDU")).toHaveAttribute("title", "Author 1");
    expect(within(first).getByText("Everyone with the Case")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.startsWith(`${BASE}/notes`))!.path).toContain("include_superseded=true");
    const kind = within(panel).getByLabelText("Kind");
    await waitFor(() => expect(within(kind).getAllByRole("option").map((o) => o.textContent)).toEqual(["All Kinds", "Office note", "Remark"]));
    await userEvent.selectOptions(kind, "file_noting");
    await waitFor(() => expect(within(panel).getAllByText(/^Body of note/)).toHaveLength(1));
    expect(api.calls.some((c) => c.path.startsWith(`${BASE}/notes`) && c.path.includes("kind=file_noting"))).toBe(true);
  });

  it("a correction shows the note it corrects folded under it; the corrected note links to its correction", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /workflow/codes": CODES,
      [`GET ${BASE}/custody`]: history([], 0),
      [`GET ${BASE}/notes`]: {
        items: [
          note(1, { body: "The original text", superseded_by: { ref_no: "ASLMS/EDU/NOTE/2026/000002", seq_no: 2 } }),
          note(2, { body: "The corrected text", supersedes: { ref_no: "ASLMS/EDU/NOTE/2026/000001", seq_no: 1 } }),
        ],
        total: 2,
      },
    });
    renderWithClient(<RemarksPanel caseRef={REF} c={C} open onClose={() => {}} />);
    const panel = await screen.findByRole("dialog", { name: "Remarks and Notes" });
    await userEvent.click(within(panel).getByRole("tab", { name: /Notes/ }));
    const list = await within(panel).findByRole("list", { name: "Notes (2)" });
    const [original, correction] = within(list).getAllByRole("listitem");
    expect(within(original!).getByRole("link", { name: "Corrected by ASLMS/EDU/NOTE/2026/000002" })).toHaveAttribute(
      "href",
      "#remarks-note-2",
    );
    expect(within(correction!).getByText("Corrects ASLMS/EDU/NOTE/2026/000001")).toBeInTheDocument();
    const fold = within(correction!).getByRole("button", { name: "Show the Corrected Note" });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(fold);
    const shown = within(correction!).getByLabelText("Corrected Note");
    expect(within(shown).getByText("The original text")).toBeInTheDocument();
  });

  it("a corrected note outside the loaded page is read from GET /notes/{note}", async () => {
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /workflow/codes": CODES,
      [`GET ${BASE}/custody`]: history([], 0),
      [`GET ${BASE}/notes`]: (call: BrowserCall) =>
        call.path.includes("kind=remark")
          ? { items: [note(9, { body: "Correction", supersedes: { ref_no: "ASLMS/EDU/NOTE/2026/000001", seq_no: 1 } })], total: 1 }
          : { items: [], total: 0 },
      "GET /notes/ASLMS-EDU-NOTE-2026-000001": note(1, { body: "Fetched original", kind: "file_noting", kind_label: "Office note" }),
    });
    renderWithClient(<RemarksPanel caseRef={REF} c={C} open onClose={() => {}} />);
    const panel = await screen.findByRole("dialog", { name: "Remarks and Notes" });
    await userEvent.click(within(panel).getByRole("tab", { name: /Notes/ }));
    await userEvent.selectOptions(await within(panel).findByLabelText("Kind"), "remark");
    await userEvent.click(await within(panel).findByRole("button", { name: "Show the Corrected Note" }));
    expect(await within(panel).findByText("Fetched original")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/notes/ASLMS-EDU-NOTE-2026-000001")).toBe(true);
  });

  it("nothing in the panel writes", async () => {
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /workflow/codes": CODES,
      [`GET ${BASE}/custody`]: history([leg(1)], 1),
      [`GET ${BASE}/notes`]: { items: [note(1)], total: 1 },
    });
    renderWithClient(<RemarksPanel caseRef={REF} c={C} open onClose={() => {}} />);
    const panel = await screen.findByRole("dialog", { name: "Remarks and Notes" });
    await userEvent.click(within(panel).getByRole("tab", { name: /Notes/ }));
    await within(panel).findByText("Body of note 1");
    expect(api.calls.every((c) => c.method === "GET")).toBe(true);
  });
});

describe("?remarks=all on the case page (decision 15)", () => {
  function pageRoutes() {
    return {
      "GET /me": makeMe(["cases.view_scope"]),
      [`GET ${BASE}`]: {
        id: "c-1",
        ref_no: "ASLMS/GOA/CASE/2026/000001",
        identity: { case_no_text: "WP(C)/1234/2026" },
        custody: card(),
        workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false },
        status: { status: "pending", next_hearing_date: null },
        counts: { notes: 0 },
        ownership: { primary: null, watchers: [] },
        parties_as_printed: { petitioner_summary: null, respondent_summary: null },
        portal: { is_provisional: false },
        dossier_status: "fetched",
        stage: null,
        merged_into_ref_no: null,
      },
      [`GET ${BASE}/custody`]: history([leg(1)], 1),
      [`GET ${BASE}/listings`]: { items: [], total: 0 },
    };
  }

  it("See all remarks pushes ?remarks=all; the address opens the panel and Close takes it away", async () => {
    browserApi(pageRoutes());
    const { unmount } = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    await userEvent.click(await screen.findByRole("button", { name: "See All Remarks (1)" }));
    expect(nav.push).toHaveBeenCalledWith(`${BASE}?remarks=all`);
    expect(screen.queryByRole("dialog", { name: "Remarks and Notes" })).toBeNull();
    unmount();
    resetNav(BASE, "remarks=all");
    browserApi(pageRoutes());
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const panel = await screen.findByRole("dialog", { name: "Remarks and Notes" });
    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    expect(nav.replace).toHaveBeenCalledWith(BASE);
  });
});
