import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type {
  AssistantCitation,
  AssistantConversation,
  AssistantMessage,
  AssistantStatus,
  AssistantThread,
  CaseDetail,
  Me,
  Permission,
} from "@/lib/api/types";
import {
  groupSources,
  highlights,
  kindLabel,
  markers,
  narrowestVisibility,
  noteText,
  pageScopes,
  scopeForTab,
  scopesFor,
  sourceLink,
  WORK_COLUMNS,
  workValue,
} from "@/lib/assistant";
import { ASSISTANT_ERRORS, T } from "@/lib/messages";
import { isTitleCase } from "@/lib/titleCase";
import { nav } from "@/test/nav";
import { CASE_TABS, navFor, showsAssistant } from "@/lib/routes";
import { caseDetail, REF } from "@/test/claimFixtures";
import { resetNav } from "@/test/nav";
import { browserApi, json, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { AssistantPage, CaseAssistant } from "./Assistant";
import { CourtOrderView } from "./CourtOrderView";
import { nb } from "@/test/dates";

const FNS: Permission[] = ["cases.view_scope", "documents.view", "assistant.use", "notes.add"];
const BASE = `/cases/${REF}`;
const PREVIEW =
  "Preview: passages found in the court records, not an AI answer. Questions are searched as words; no AI is used.";

function me(mode: Me["assistant_mode"] = "preview", functions: Permission[] = FNS): Me {
  return makeMe(functions, "dept_officer", { assistant_mode: mode });
}

function status(extra: Partial<AssistantStatus> = {}): AssistantStatus {
  return {
    mode: "preview",
    state: "preview",
    banner: PREVIEW,
    limits: { questions_per_hour: 30, used_last_hour: 4, question_max_chars: 2000, messages_per_conversation: 200 },
    scopes: ["case", "my_cases", "research"],
    engine: null,
    internal_records: "never",
    work_questions: [],
    ...extra,
  };
}

function conv(extra: Partial<AssistantConversation> = {}): AssistantConversation {
  return {
    id: "k-1",
    scope: "research",
    case: null,
    title: "orders on regularisation",
    last_message_at: "2026-10-23T10:12:00Z",
    created_at: "2026-10-23T10:12:00Z",
    message_count: 2,
    ...extra,
  };
}

function cite(extra: Partial<AssistantCitation> = {}): AssistantCitation {
  return {
    document_id: "d-1",
    order_id: "o-1",
    case: { id: "c-1", case_no_text: "WP(C)/1/2026", cnr: "ASHC010001002026", visible: true },
    source_kind: "court_order",
    doc_type_label: "Order",
    doc_date: "2026-03-12",
    order_no: "5",
    page: 2,
    passage: "The respondents shall file an [[affidavit]] within four weeks.",
    related: false,
    available: true,
    open: { kind: "document", href: "/cases/c-1/orders/o-1/file?disposition=inline" },
    label: null,
    cited: true,
    context: null,
    note: null,
    internal: false,
    what: null,
    visibility: null,
    ...extra,
  };
}

const OTHER = cite({
  document_id: "d-2",
  order_id: "o-2",
  case: { id: null, case_no_text: "WP(C)/202/2026", cnr: "ASHC010002022026", visible: false },
  order_no: "2",
  page: 1,
  passage: "Orders on [[regularisation]] of contractual teachers.",
  related: true,
  open: { kind: "court_order", href: "/assistant/court-orders/o-2?message=a-1" },
});

function question(id = "q-1", content = "what did the court direct"): AssistantMessage {
  return {
    id,
    role: "user",
    created_at: "2026-10-23T10:12:00Z",
    content,
    citations: [],
    engine: null,
    checks: null,
    internal_used: false,
    suggest_internal: false,
    suggest_work: false,
  };
}

function answer(extra: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: "a-1",
    role: "assistant",
    created_at: "2026-10-23T10:12:01Z",
    content: "Preview: passages found in the court records, not an AI answer.\n2 passages from 2 documents matched all of the words of your question.",
    mode: "preview",
    outcome: "answered",
    error: null,
    hidden_reason: null,
    engine: null,
    checks: null,
    internal_used: false,
    suggest_internal: false,
    suggest_work: false,
    reply_to_id: "q-1",
    citations: [cite(), OTHER],
    ...extra,
  };
}

function thread(messages: AssistantMessage[], c = conv()): AssistantThread {
  return { conversation: c, messages, has_more: false };
}

function pageRoutes(items: AssistantConversation[], messages: AssistantMessage[], extra: Record<string, unknown> = {}) {
  return {
    "GET /me": me(),
    "GET /assistant/status": status(),
    "GET /assistant/conversations": { total: items.length, items },
    "GET /assistant/conversations/k-1": thread(messages),
    ...extra,
  };
}

beforeEach(() => {
  resetNav("/assistant");
});

describe("where the assistant shows (decision 14)", () => {
  it("the menu entry and the case tab need assistant.use and a mode other than off", () => {
    expect(showsAssistant(me("preview"))).toBe(true);
    expect(showsAssistant(me("sourcetrace"))).toBe(true);
    expect(showsAssistant(me("off"))).toBe(false);
    expect(showsAssistant(me("preview", ["cases.view_scope"]))).toBe(false);
    expect(navFor(me("preview")).map((e) => e.key)).toContain("assistant");
    expect(navFor(me("off")).map((e) => e.key)).not.toContain("assistant");
    const keys = navFor(me("preview")).map((e) => e.key);
    expect(keys.indexOf("assistant")).toBe(keys.indexOf("search") + 1);
    const tabs = CASE_TABS.map((t) => t.key);
    expect(tabs.indexOf("assistant")).toBe(tabs.indexOf("timeline") + 1);
    expect(CASE_TABS.find((t) => t.key === "assistant")?.more).toBe(false);
  });

  it("the page says the assistant is off without the mode", async () => {
    browserApi({ "GET /me": me("off") });
    renderWithClient(<AssistantPage />);
    expect(await screen.findByText("The Case Assistant is not switched on.")).toBeInTheDocument();
  });
});

describe("the Assistant page", () => {
  it("shows the preview banner, the conversation in its labelled box, the Preview badge and one primary (Ask)", async () => {
    browserApi(pageRoutes([conv()], [question(), answer()]));
    renderWithClient(<AssistantPage />);
    expect(await screen.findByText(PREVIEW)).toBeInTheDocument();
    const box = await screen.findByRole("log", { name: "Conversation" });
    expect(box).toHaveAttribute("tabindex", "0");
    await waitFor(() => expect(within(box).getByText("what did the court direct")).toBeInTheDocument());
    expect(within(box).getAllByText("Preview")).toHaveLength(2); // who answered, and the badge
    expect(within(box).getByText("Answered")).toBeInTheDocument();
    expect(primaryActions(document.body)).toEqual(["Ask"]);
    // design assistant-ollama-work, decision 2: the kit Tabs in the address in place of the Search In switch
    expect(screen.queryByRole("radiogroup", { name: "Search In" })).toBeNull();
    const tabs = screen.getByRole("navigation", { name: "Assistant Tabs" });
    expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toEqual(["My Cases", "All Court Orders"]);
    expect(within(tabs).getByRole("link", { name: "My Cases" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "All Court Orders" })).toHaveAttribute("href", "/assistant?tab=court-orders");
    expect(within(tabs).queryByRole("link", { name: "This Case" })).toBeNull();
    expect(screen.getByText("Conversations are private to you and cannot be deleted.")).toBeInTheDocument();
    expect(screen.getByText(/26 questions left this hour of 30/)).toBeInTheDocument();
  });

  it("sources open the file at the page, a case the reader cannot open opens the court-record view, related apart", async () => {
    browserApi(pageRoutes([conv()], [question(), answer()]));
    renderWithClient(<AssistantPage />);
    // design assistant-polish, decision 16: an answer without markers keeps its sources under it
    const box = await screen.findByRole("log", { name: "Conversation" });
    const panel = await within(box).findByRole("group", { name: "Preview 1" });
    const own = await within(panel).findByRole("link", { name: /Open source 1: Order of 12\sMar\s2026, No\. 5, page 2/ });
    expect(own).toHaveAttribute("href", "/api/backend/cases/c-1/orders/o-1/file?disposition=inline#page=2");
    expect(own).toHaveAttribute("target", "_blank");
    const related = within(panel).getByRole("list", { name: "Related Orders in Other Cases" });
    const other = within(related).getByRole("link", { name: /Open source 2/ });
    expect(other).toHaveAttribute("href", "/assistant/orders/o-2?m=a-1");
    expect(within(related).getByText("WP(C)/202/2026")).toBeInTheDocument();
    // the excerpt's [[ ]] are highlights, never shown as brackets
    const mark = within(panel).getByText("affidavit", { selector: "mark" });
    expect(mark.tagName).toBe("MARK");
    expect(panel.textContent).not.toContain("[[");
  });

  it("an answer hidden by a filing the reader can no longer see says so, and the source is unavailable", async () => {
    const hidden = answer({
      content: null,
      hidden_reason: "This answer drew on a document you can no longer see.",
      citations: [
        cite({
          document_id: null,
          order_id: null,
          case: { id: null, case_no_text: null, cnr: null, visible: false },
          source_kind: "court_filing",
          doc_type_label: null,
          doc_date: null,
          order_no: null,
          page: null,
          passage: null,
          available: false,
          unavailable_reason: "This source is no longer available.",
          open: null,
        }),
      ],
    });
    browserApi(pageRoutes([conv()], [question(), hidden]));
    renderWithClient(<AssistantPage />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    expect(await within(box).findByText("This answer drew on a document you can no longer see.")).toBeInTheDocument();
    const panel = within(box).getByRole("group", { name: "Preview 1" });
    expect(within(panel).getByText("This source is no longer available to you")).toBeInTheDocument();
    expect(within(panel).queryByRole("link")).toBeNull();
    expect(panel.textContent?.split("Answered")[1]).not.toMatch(/Petition|Order of|page/);
  });

  it("a failed answer and a question without an answer are in words", async () => {
    const failed = answer({ outcome: "failed", content: "x", error: { family: "scope", message: "x" }, citations: [] });
    browserApi(pageRoutes([conv()], [question(), failed, question("q-2", "lost question")]));
    renderWithClient(<AssistantPage />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    expect(await within(box).findByText("The answer drew on material outside your reach and was withheld.")).toBeInTheDocument();
    expect(within(box).getByText("Not Answered")).toBeInTheDocument();
    expect(within(box).getByText("No answer was recorded for this question.")).toBeInTheDocument();
  });

  it("suggested chips fill the question box on an empty thread; Ask sends it and the answer appears", async () => {
    const api = browserApi(
      pageRoutes([], [], {
        "POST /assistant/ask": {
          conversation: conv({ scope: "my_cases" }),
          question: question("q-9", "Which of my cases have a direction to file an affidavit?"),
          answer: answer({ id: "a-9", reply_to_id: "q-9" }),
        },
      }),
    );
    renderWithClient(<AssistantPage />);
    const chips = await screen.findByRole("group", { name: "Suggested Questions" });
    await userEvent.click(within(chips).getByRole("button", { name: "Which of my cases have a direction to file an affidavit?" }));
    const box = screen.getByLabelText("Question") as HTMLTextAreaElement;
    expect(box.value).toBe("Which of my cases have a direction to file an affidavit?");
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({
      question: "Which of my cases have a direction to file an affidavit?",
      scope: "my_cases",
      include_related: true,
    });
    const log = screen.getByRole("log", { name: "Conversation" });
    expect(await within(log).findByText("Which of my cases have a direction to file an affidavit?")).toBeInTheDocument();
  });

  it("error codes are in words", async () => {
    browserApi(
      pageRoutes([], [], {
        "POST /assistant/ask": json(429, { detail: { code: "assistant_limit", message: "limit", retry_after: 120 } }),
      }),
    );
    renderWithClient(<AssistantPage />);
    await userEvent.type(await screen.findByLabelText("Question"), "orders on transfer");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You have asked the hourly number of questions. Try again in 2 minutes.");
    expect((screen.getByLabelText("Question") as HTMLTextAreaElement).value).toBe("orders on transfer");
  });

  it("a question in flight and control characters are in words", async () => {
    expect(ASSISTANT_ERRORS.question_in_flight!({})).toBe("Your last question is still being answered. Wait for its answer, then ask again.");
    expect(ASSISTANT_ERRORS.bad_question!({ reason: "control_characters" })).toBe(
      "The question holds hidden control characters. Type it again without pasting.",
    );
    expect(ASSISTANT_ERRORS.bad_question!({})).toBe("Write a question of 3 to 2,000 characters.");
  });

  it("the sourcetrace banner reminds to check sources", async () => {
    browserApi({
      ...pageRoutes([], []),
      "GET /me": me("sourcetrace"),
      "GET /assistant/status": status({ mode: "sourcetrace", state: "ready", banner: null }),
    });
    renderWithClient(<AssistantPage />);
    expect(await screen.findByText(/Answers come from SourceTrace\. Check every source/)).toBeInTheDocument();
  });
});

describe("the case Assistant tab", () => {
  function caseRoutes(extra: Record<string, unknown> = {}, detail?: CaseDetail) {
    return {
      "GET /me": me(),
      "GET /assistant/status": status(),
      [`GET ${BASE}`]: detail ?? caseDetail({ workflow: { note_mode: "permanent", upload: true, set_stage: true, next_dates: false } } as Partial<CaseDetail>),
      "GET /assistant/conversations": { total: 1, items: [conv({ scope: "case", case: { id: "c-1", ref_no: REF, case_no_text: "WP(C)/1/2026" } })] },
      "GET /assistant/conversations/k-1": thread([question(), answer()]),
      "GET /workflow/codes": { note_kinds: [{ code: "general", label: "General", selectable: true }], limits: { note_max_chars: 20000, attachments_max_files: 5 } },
      "GET /documents/types": { items: [], upload: { max_bytes: 1000, extensions: [".pdf"] } },
      [`GET ${BASE}/documents`]: { items: [], total: 0 },
      ...extra,
    };
  }

  it("is about This Case only, with the scope line, Open the Assistant, Ask secondary, and the latest case conversation", async () => {
    const api = browserApi(caseRoutes());
    resetNav(`${BASE}/assistant`);
    renderWithClient(<CaseAssistant caseRef={REF} />);
    expect(await screen.findByText(/Searches this case's court orders/)).toBeInTheDocument();
    // design assistant-ollama-work, decision 1: no scope switch, one line and a link in its place
    expect(screen.queryByRole("radiogroup", { name: "Search In" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Assistant Tabs" })).toBeNull();
    expect(
      screen.getByText(/For questions across your cases, about your own work, or across all court orders, open the Assistant\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the Assistant" })).toHaveAttribute("href", "/assistant");
    expect(primaryActions(document.body)).toEqual([]);
    await screen.findByRole("log", { name: "Conversation" });
    const listCall = api.calls.find((c) => c.path.startsWith("/assistant/conversations?"))!;
    const q = new URLSearchParams(listCall.path.split("?")[1]);
    expect(q.get("scope")).toBe("case");
    expect(q.get("case")).toBe(REF);
    expect(q.get("limit")).toBe("1");
  });

  it("Copy to note fills the note dialog with the answer and its references", async () => {
    browserApi(caseRoutes());
    resetNav(`${BASE}/assistant`);
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: "Copy to Note" }));
    const dialog = await screen.findByRole("dialog");
    const note = (await within(dialog).findByLabelText("Note")) as HTMLTextAreaElement;
    expect(note.value).toContain("2 passages from 2 documents matched");
    // a note keeps ordinary spaces (design portal-ui-kit-fixes, decision 5)
    expect(note.value).toContain("[1] Order of 12 Mar 2026, No. 5, page 2 (WP(C)/1/2026): “The respondents shall file an affidavit within four weeks.”");
    expect(note.value).toContain("[2] Order of 12 Mar 2026, No. 2, page 1 (WP(C)/202/2026)");
    expect(note.value).not.toContain("[[");
  });

  it("no Copy to note without a note mode", async () => {
    browserApi(caseRoutes({}, caseDetail({ workflow: { note_mode: null, upload: false, set_stage: false, next_dates: false } } as Partial<CaseDetail>)));
    resetNav(`${BASE}/assistant`);
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await within(box).findByText("Answered");
    expect(within(box).queryByRole("button", { name: "Copy to Note" })).toBeNull();
  });

});

describe("the court-record view (decision 11)", () => {
  it("shows the public facts, says the case cannot be opened, and opens the order through the assistant route", async () => {
    browserApi({
      "GET /me": me(),
      "GET /assistant/court-orders/o-2": {
        order: { id: "o-2", order_no: "2", order_date: "2026-03-01", kind: "interim", judge: "HON'BLE MR JUSTICE A" },
        case: {
          cnr: "ASHC010002022026",
          case_no_text: "WP(C)/202/2026",
          filing_no_text: null,
          court: "Principal Seat",
          bench: null,
          case_type: "WP(C)",
          year: 2026,
          status: "pending",
          parties: ["R. DAS", "THE STATE OF ASSAM"],
          advocates: ["A. ADVOCATE"],
          acts: [],
          last_hearing_date: null,
          next_hearing_date: "2026-11-04",
        },
        case_visible: false,
      },
    });
    resetNav("/assistant/orders/o-2");
    renderWithClient(<CourtOrderView orderId="o-2" messageId="a-1" />);
    expect(await screen.findByText("This is the court's public record. You cannot open this case in ASLMS.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Court Record: WP(C)/202/2026");
    expect(screen.getByText("R. DAS; THE STATE OF ASSAM")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the Order" })).toHaveAttribute(
      "href",
      "/api/backend/assistant/court-orders/o-2/file?message=a-1&disposition=inline",
    );
    expect(screen.queryByRole("link", { name: "Open the Case Page" })).toBeNull();
    // `/assistant/orders` has no page of its own: its crumb is text, so no link (or prefetch) answers 404
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Assistant" })).toHaveAttribute("href", "/assistant");
    expect(within(crumbs).getByText("Orders").closest("a")).toBeNull();
    expect(primaryActions(document.body)).toEqual(["Open the Order"]);
    const text = document.body.textContent ?? "";
    for (const banned of ["ASLMS/", "Owner", "Custody", "Stage", "Notes"]) expect(text).not.toContain(banned);
  });

  it("without a citation in the reader's own answer the page says so", async () => {
    browserApi({ "GET /me": me(), "GET /assistant/court-orders/o-9": json(404, { detail: { code: "not_found", message: "no such order" } }) });
    renderWithClient(<CourtOrderView orderId="o-9" messageId="a-1" />);
    expect(await screen.findByText("This order is not among the sources of your answers.")).toBeInTheDocument();
  });
});

describe("the helpers", () => {
  it("split highlights, build links and the note text", () => {
    expect(highlights("a [[b]] c [[d]]")).toEqual([
      { text: "a ", hit: false },
      { text: "b", hit: true },
      { text: " c ", hit: false },
      { text: "d", hit: true },
    ]);
    expect(sourceLink(cite(), "a-1")).toEqual({
      kind: "document",
      href: "/api/backend/cases/c-1/orders/o-1/file?disposition=inline#page=2",
      newTab: true,
    });
    expect(sourceLink(cite(), "a-1", false)?.href).toBe("/api/backend/cases/c-1/orders/o-1/file?disposition=attachment");
    expect(sourceLink(cite({ page: null, open: { kind: "document", href: "/documents/d-1/file?disposition=attachment" } }), "a-1")?.href).toBe(
      "/api/backend/documents/d-1/file?disposition=attachment",
    );
    expect(sourceLink(cite({ available: false }), "a-1")).toBeNull();
    expect(noteText(answer({ content: "text", citations: [cite()] }))).toBe(
      "text\n\nFrom the court records:\n[1] Order of 12 Mar 2026, No. 5, page 2 (WP(C)/1/2026): “The respondents shall file an affidavit within four weeks.”",
    );
  });
});

// ------------------------------------------------------------------------------------------------ the local model
// design assistant-ollama, round 1 (decisions 4, 8 to 10 and 14)

const OLLAMA_BANNER =
  "Answers are written by a local AI model on the Government's own servers, from the records found. The model can make mistakes: check every answer against the cited order or record before relying on it.";

function ollamaStatus(extra: Partial<AssistantStatus> = {}): AssistantStatus {
  return status({
    mode: "ollama",
    state: "ready",
    banner: OLLAMA_BANNER,
    internal_records: "switch",
    engine: { kind: "ollama", model: "qwen3.5:4b", readiness: "ready", reason: null },
    ...extra,
  });
}

const DETAILS = cite({
  document_id: null,
  order_id: null,
  source_kind: "case_details",
  doc_type_label: null,
  doc_date: null,
  order_no: null,
  page: null,
  passage: null,
  label: "S1",
  cited: true,
  context: "Case number: WP(C)/1/2026; Status: pending",
  open: { kind: "case_tab", href: "/cases/c-1/details" },
});
const ORDER = cite({ label: "S2", cited: true, context: "The respondents shall file an affidavit within four weeks." });
const NOTE = cite({
  document_id: null,
  order_id: null,
  source_kind: "note",
  doc_type_label: null,
  doc_date: "2026-10-01",
  order_no: null,
  page: null,
  passage: null,
  label: "S3",
  cited: true,
  internal: true,
  visibility: "private_to_office",
  note: { id: "n-1", seq_no: 4, kind_label: "General", corrected_by_seq_no: null },
  context: "Note 4, General, 01 Oct 2026, by Under Secretary, EDU\nOur stand is to contest.",
  open: { kind: "case_tab", href: "/cases/c-1/notes#note-4" },
});
const UNCITED = cite({ document_id: "d-9", order_id: "o-9", label: "S4", cited: false, related: true, context: "other text" });

function localAnswer(extra: Partial<AssistantMessage> = {}): AssistantMessage {
  return answer({
    mode: "ollama",
    content: "The court directed an affidavit [S2]. According to the department's note, we contest [S3].",
    engine: { kind: "ollama", model: "qwen3.5:4b" },
    checks: { invalid_markers: 1, cut_short: true },
    internal_used: true,
    citations: [DETAILS, ORDER, NOTE, UNCITED],
    ...extra,
  });
}

const CASE_CONV = conv({ scope: "case", case: { id: "c-1", ref_no: REF, case_no_text: "WP(C)/1/2026" } });

function localRoutes(extra: Record<string, unknown> = {}, c: AssistantConversation = CASE_CONV) {
  return {
    "GET /me": me("ollama"),
    "GET /assistant/status": ollamaStatus(),
    ["GET " + BASE]: caseDetail({ workflow: { note_mode: "permanent", upload: true, set_stage: true, next_dates: false } } as Partial<CaseDetail>),
    "GET /assistant/conversations": { total: 1, items: [c] },
    "GET /assistant/conversations/k-1": thread([question(), localAnswer()], c),
    "GET /workflow/codes": { note_kinds: [{ code: "general", label: "General", selectable: true }], limits: { note_max_chars: 20000, attachments_max_files: 5 } },
    "GET /documents/types": { items: [], upload: { max_bytes: 1000, extensions: [".pdf"] } },
    ["GET " + BASE + "/documents"]: { items: [], total: 0 },
    ...extra,
  };
}

describe("the local model (design assistant-ollama)", () => {
  it("shows the banner, court information only by default and the switch with its confirmation on the case tab", async () => {
    const api = browserApi(
      localRoutes({
        "POST /assistant/internal-records": {
          conversation_id: "k-1",
          case_id: "c-1",
          internal_included_at: "2026-10-27T10:00:00Z",
          new_conversation: false,
        },
      }),
    );
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    expect(await screen.findByText(OLLAMA_BANNER)).toBeInTheDocument();
    expect(screen.getByText(/Court information only\.$/)).toBeInTheDocument();
    const button = await screen.findByRole("button", { name: "Include This Case's Internal Records" });
    await userEvent.click(button);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Drafts are never read\. You cannot switch this off in this conversation/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith("/assistant/internal-records"))).toBe(false); // nothing without Include
    await userEvent.click(within(dialog).getByRole("button", { name: "Include" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path.startsWith("/assistant/internal-records"))).toBe(true));
    const post = api.calls.find((c) => c.path.startsWith("/assistant/internal-records"))!;
    expect(post.body).toEqual({ case: REF, conversation_id: "k-1" });
  });

  it("after the switch: the banner with its time, Start a Court-Only Conversation and the mark in the thread", async () => {
    const c = conv({ ...CASE_CONV, internal_included_at: "2026-10-23T10:12:00Z" });
    browserApi(localRoutes({}, c));
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    expect(await screen.findByText("Internal Records of This Case Included")).toBeInTheDocument();
    expect(screen.getByText(/pending actions and department documents you can open\. Drafts are never read\./)).toBeInTheDocument();
    expect(await screen.findByText("Internal records included from here")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Include This Case's Internal Records" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Start a Court-Only Conversation" }));
    expect(await screen.findByText("Ask a Question")).toBeInTheDocument(); // a new, empty conversation
  });

  it("answers carry the Local Model badge, markers opening their sources, both groups and the text given", async () => {
    browserApi(localRoutes());
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    expect(await within(box).findByText("Local Model")).toBeInTheDocument();
    expect(within(box).getByText("qwen3.5:4b")).toBeInTheDocument();
    expect(within(box).getAllByText("Assistant (Local Model)").length).toBeGreaterThan(0);
    expect(within(box).getByText("Uses internal records of this case")).toBeInTheDocument();
    expect(within(box).getByText("A reference to a source that was not given was removed.")).toBeInTheDocument();
    expect(within(box).getByText("Answer Cut Short")).toBeInTheDocument();
    expect(within(box).getByText("Written by a local AI model from the sources below. Check it against the cited order or record.")).toBeInTheDocument();
    await userEvent.click(within(box).getByRole("button", { name: "Sources (4)" }));
    const panel = await screen.findByRole("dialog", { name: "Sources of This Answer" });
    expect(within(panel).getByRole("list", { name: "Court Record" })).toBeInTheDocument();
    const internal = within(panel).getByRole("list", { name: "Internal Records" });
    expect(within(internal).getByText("Internal")).toBeInTheDocument();
    expect(within(internal).getByRole("link", { name: /Note 4, General/ })).toHaveAttribute("href", "/cases/c-1/notes#note-4");
    expect(within(panel).getByText("Other Sources Given (Not Cited)")).toBeInTheDocument();
    expect(within(panel).getAllByText("Text Given to the Model").length).toBe(4);
  });

  it("the suggestion offers the switch and does nothing without the click", async () => {
    const api = browserApi(
      localRoutes({
        "GET /assistant/conversations/k-1": thread(
          [question(), localAnswer({ suggest_internal: true, internal_used: false, citations: [DETAILS, ORDER] })],
          CASE_CONV,
        ),
      }),
    );
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    expect(await screen.findByText("This may be in your internal records. Include them?")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith("/assistant/internal-records"))).toBe(false);
  });

  it("never offers the switch on the Assistant page", async () => {
    browserApi({ ...pageRoutes([conv()], [question(), localAnswer()]), "GET /me": me("ollama"), "GET /assistant/status": ollamaStatus() });
    renderWithClient(<AssistantPage />);
    expect(await screen.findByText("Court information only. Notes and internal records are never used here.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Include This Case's Internal Records" })).toBeNull();
  });

  it("without the read guard the case tab never shows the switch", async () => {
    browserApi(localRoutes({ "GET /me": me("ollama", ["documents.view", "assistant.use", "notes.add"]) }));
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    await screen.findByText(OLLAMA_BANNER);
    expect(screen.queryByRole("button", { name: "Include This Case's Internal Records" })).toBeNull();
  });

  it("conversation list items switched on are marked", async () => {
    const marked = conv({ internal_included_at: "2026-10-23T10:12:00Z" });
    browserApi({ ...pageRoutes([marked], [question(), localAnswer()]), "GET /me": me("ollama"), "GET /assistant/status": ollamaStatus() });
    renderWithClient(<AssistantPage />);
    const list = await screen.findByRole("complementary", { name: "Conversations" });
    expect(await within(list).findByText("Internal Records Included")).toBeInTheDocument();
  });

  it("readiness notices and the refusals are in words", async () => {
    browserApi({
      ...pageRoutes([], []),
      "GET /me": me("ollama"),
      "GET /assistant/status": ollamaStatus({ engine: { kind: "ollama", model: "qwen3.5:4b", readiness: "loading", reason: "not_loaded" } }),
    });
    renderWithClient(<AssistantPage />);
    expect(await screen.findByText(/The Case Assistant is starting/)).toBeInTheDocument();
    expect(ASSISTANT_ERRORS.assistant_loading!({})).toBe("The Case Assistant is starting. Try again in a minute.");
    expect(ASSISTANT_ERRORS.assistant_unavailable!({})).toBe("The Case Assistant's model is not available at the moment. Try again later.");
    expect(ASSISTANT_ERRORS.assistant_busy!({})).toBe("The Case Assistant is busy with another question. Try again shortly.");
    expect(ASSISTANT_ERRORS.no_internal_records!({})).toBe("There are no internal records of this case that you can open.");
  });

  it("Copy to note presets the narrowest visibility of the cited internal records and warns", async () => {
    browserApi(localRoutes());
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: "Copy to Note" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("This answer draws on internal records. Choose who may read the note with care.")).toBeInTheDocument();
    const checked = within(dialog).getAllByRole("radio").find((r) => (r as HTMLInputElement).checked) as HTMLInputElement;
    expect(checked.value).toBe("private_to_office");
    const note = (await within(dialog).findByLabelText("Note")) as HTMLTextAreaElement;
    expect(note.value).not.toContain("other text"); // uncited sources are not copied
  });

  it("the helpers: markers, groups, kinds and the narrowest visibility", () => {
    expect(markers("a [S1] b [S12].")).toEqual([
      { text: "a " },
      { text: "[S1]", label: "S1" },
      { text: " b " },
      { text: "[S12]", label: "S12" },
      { text: "." },
    ]);
    const g = groupSources([DETAILS, ORDER, NOTE, UNCITED].map((c, i) => ({ c, n: i + 1 })));
    expect([g.court.length, g.internal.length, g.uncited.length]).toEqual([2, 1, 1]);
    expect(kindLabel(cite({ source_kind: "department_document", what: "note_attachment" }))).toBe("Note Attachment");
    expect(kindLabel(NOTE)).toBe("Note");
    expect(narrowestVisibility(localAnswer())).toBe("private_to_office");
    expect(narrowestVisibility(answer())).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ assistant-polish
// design assistant-polish (decisions 1 and 15 to 17)

describe("the composer keys (design assistant-polish, decision 1)", () => {
  function asking() {
    return {
      "POST /assistant/ask": {
        conversation: conv({ scope: "my_cases" }),
        question: question("q-9", "orders on transfer"),
        answer: answer({ id: "a-9", reply_to_id: "q-9" }),
      },
    };
  }
  const posts = (api: { calls: { method: string }[] }) => api.calls.filter((c) => c.method === "POST").length;

  it("enter sends and shift+enter adds a line, on the page", async () => {
    const api = browserApi(pageRoutes([], [], asking()));
    renderWithClient(<AssistantPage />);
    const box = (await screen.findByLabelText("Question")) as HTMLTextAreaElement;
    await userEvent.type(box, "orders on{Shift>}{Enter}{/Shift}transfer");
    expect(box.value).toBe("orders on\ntransfer");
    expect(posts(api)).toBe(0);
    await userEvent.type(box, "{Enter}");
    await waitFor(() => expect(posts(api)).toBe(1));
    expect(api.calls.find((c) => c.method === "POST")!.body).toMatchObject({ question: "orders on\ntransfer" });
  });

  it("enter sends on the case tab too", async () => {
    const api = browserApi({
      ...localRoutes(),
      "GET /assistant/conversations": { total: 0, items: [] },
      "POST /assistant/ask": {
        conversation: CASE_CONV,
        question: question("q-9", "who are the parties"),
        answer: answer({ id: "a-9", reply_to_id: "q-9" }),
      },
    });
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = (await screen.findByLabelText("Question")) as HTMLTextAreaElement;
    await userEvent.type(box, "who are the parties{Enter}");
    await waitFor(() => expect(posts(api)).toBe(1));
    expect(api.calls.find((c) => c.method === "POST")!.body).toMatchObject({ question: "who are the parties", scope: "case" });
  });

  it("ctrl or cmd+enter still sends", async () => {
    const api = browserApi(pageRoutes([], [], asking()));
    renderWithClient(<AssistantPage />);
    const box = (await screen.findByLabelText("Question")) as HTMLTextAreaElement;
    await userEvent.type(box, "orders on transfer{Control>}{Enter}{/Control}");
    await waitFor(() => expect(posts(api)).toBe(1));
    await waitFor(() => expect(box.value).toBe(""));
    await userEvent.type(box, "orders on promotion{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(posts(api)).toBe(2));
  });

  it("no send while composing", async () => {
    const api = browserApi(pageRoutes([], [], asking()));
    renderWithClient(<AssistantPage />);
    const box = (await screen.findByLabelText("Question")) as HTMLTextAreaElement;
    await userEvent.type(box, "orders on transfer");
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    fireEvent.keyDown(box, { key: "Enter", keyCode: 229 });
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(api)).toBe(0);
  });

  it("enter does nothing while busy or too short", async () => {
    const api = browserApi(pageRoutes([], [], { "POST /assistant/ask": () => new Promise(() => {}) }));
    renderWithClient(<AssistantPage />);
    const box = (await screen.findByLabelText("Question")) as HTMLTextAreaElement;
    await userEvent.type(box, "ab{Enter}");
    expect(box.value).toBe("ab"); // no new line either
    expect(posts(api)).toBe(0);
    await userEvent.type(box, "c{Enter}");
    await waitFor(() => expect(posts(api)).toBe(1));
    await screen.findByText("Searching the Court Records…");
    await userEvent.type(box, "{Enter}");
    expect(box.value).toBe("abc");
    expect(posts(api)).toBe(1);
  });

  it("the hint is shown and described", async () => {
    browserApi(pageRoutes([], []));
    renderWithClient(<AssistantPage />);
    const box = await screen.findByLabelText("Question");
    const hint = screen.getByText("Press Enter to send, Shift+Enter for a new line.");
    expect(box.getAttribute("aria-describedby")?.split(" ")).toContain(hint.id);
    expect(box).toHaveAttribute("enterkeyhint", "send");
  });
});

describe("sources opened from their reference (design assistant-polish, decision 16)", () => {
  it("markers are buttons with names; a marker without a citation is plain text", async () => {
    browserApi(
      localRoutes({
        "GET /assistant/conversations/k-1": thread(
          [question(), localAnswer({ content: "The court directed an affidavit [S2]. We contest [S3]. Odd [S9]." })],
          CASE_CONV,
        ),
      }),
    );
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    const s2 = await within(box).findByRole("button", { name: nb("Source S2: Order of 12 Mar 2026, No. 5, page 2") });
    expect(s2).toHaveAttribute("type", "button");
    expect(s2).toHaveTextContent("S2");
    expect(within(box).getByRole("button", { name: nb("Source S3: Note 4, General, 1 Oct 2026 (Internal)") })).toBeInTheDocument();
    expect(within(box).queryByRole("button", { name: /Source S9/ })).toBeNull();
    expect(within(box).getByText(/\[S9\]/)).toBeInTheDocument();
  });

  it("marker opens the source dialog; Escape closes it and the focus returns to the marker", async () => {
    browserApi(localRoutes());
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    const marker = await within(box).findByRole("button", { name: /^Source S2:/ });
    await userEvent.click(marker);
    const dialog = await screen.findByRole("dialog", { name: "Source S2" });
    expect(within(dialog).getByText("Court Order")).toBeInTheDocument();
    expect(within(dialog).getByText("Order of 12 Mar 2026, No. 5, page 2")).toBeInTheDocument();
    expect(within(dialog).getByText("affidavit", { selector: "mark" })).toBeInTheDocument();
    expect(within(dialog).getByText("Text Given to the Model")).toBeInTheDocument();
    const open = within(dialog).getByRole("link", { name: "Open the Order" });
    expect(open).toHaveAttribute("href", "/api/backend/cases/c-1/orders/o-1/file?disposition=inline#page=2");
    expect(open).toHaveAttribute("target", "_blank");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Source S2" })).toBeNull());
    expect(marker).toHaveFocus();
  });

  it("internal source in the dialog, and a source no longer available", async () => {
    const gone = cite({
      document_id: null,
      order_id: null,
      case: { id: null, case_no_text: null, cnr: null, visible: false },
      source_kind: "court_filing",
      doc_type_label: null,
      doc_date: null,
      order_no: null,
      page: null,
      passage: null,
      available: false,
      open: null,
      label: "S4",
      cited: true,
    });
    browserApi(
      localRoutes({
        "GET /assistant/conversations/k-1": thread(
          [question(), localAnswer({ content: "We contest [S3]. Also [S4].", citations: [DETAILS, ORDER, NOTE, gone] })],
          CASE_CONV,
        ),
      }),
    );
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: nb("Source S3: Note 4, General, 1 Oct 2026 (Internal)") }));
    const dialog = await screen.findByRole("dialog", { name: "Source S3" });
    expect(within(dialog).getByText("Internal")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Open the Note" })).toHaveAttribute("href", "/cases/c-1/notes#note-4");
    await userEvent.click(within(dialog).getAllByRole("button", { name: "Close" }).at(-1)!); // the footer's
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Source S3" })).toBeNull());
    await userEvent.click(within(box).getByRole("button", { name: "Source S4: No Longer Available" }));
    const goneDialog = await screen.findByRole("dialog", { name: "Source S4" });
    expect(within(goneDialog).getByText("This source is no longer available.")).toBeInTheDocument();
    expect(within(goneDialog).queryByRole("link")).toBeNull();
  });

  it("no inline list or side panel for marked answers; a preview answer keeps its list under the answer", async () => {
    browserApi(localRoutes());
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await within(box).findByText("Local Model");
    expect(screen.queryByRole("complementary", { name: "Sources Used" })).toBeNull();
    expect(within(box).queryByRole("list")).toBeNull();
    expect(within(box).queryByRole("link")).toBeNull();
    expect(within(box).queryByText("Text Given to the Model")).toBeNull();
  });

  it("a preview answer keeps its list under the answer, with no Sources button", async () => {
    browserApi(pageRoutes([conv()], [question(), answer()]));
    renderWithClient(<AssistantPage />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await waitFor(() => expect(within(box).getAllByRole("list").length).toBeGreaterThan(0));
    expect(within(box).queryByRole("button", { name: /^Sources \(/ })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Sources Used" })).toBeNull();
  });

  it("sources (n) opens the full list, uncited sources collapsed", async () => {
    browserApi(localRoutes());
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: "Sources (4)" }));
    const dialog = await screen.findByRole("dialog", { name: "Sources of This Answer" });
    expect(within(dialog).getByRole("list", { name: "Court Record" })).toBeInTheDocument();
    expect(within(dialog).getByRole("list", { name: "Internal Records" })).toBeInTheDocument();
    const uncited = within(dialog).getByText("Other Sources Given (Not Cited)").closest("details")!;
    expect(uncited).not.toHaveAttribute("open");
  });
});

describe("a quick fact from the case record (design assistant-polish, decision 15)", () => {
  const FACT = answer({
    id: "a-7",
    mode: "ollama",
    content: "DINAR AHMED AND 3 ORS versus THE STATE OF ASSAM AND 4 ORS [S1].",
    engine: { kind: "case_record", model: null },
    checks: null,
    citations: [DETAILS],
  });

  it("carries From the Case Record, with no Local Model badge or line", async () => {
    browserApi({ ...pageRoutes([conv()], [question(), FACT]), "GET /me": me("ollama"), "GET /assistant/status": ollamaStatus() });
    renderWithClient(<AssistantPage />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    expect(await within(box).findByText("From the Case Record")).toBeInTheDocument();
    expect(within(box).getByText("Taken from the court record held for this case, as shown on the case page.")).toBeInTheDocument();
    expect(within(box).getAllByText("Assistant (Case Record)").length).toBeGreaterThan(0);
    expect(within(box).queryByText("Local Model")).toBeNull();
    expect(within(box).queryByText(/Written by a local AI model/)).toBeNull();
    await userEvent.click(within(box).getByRole("button", { name: "Source S1: Case Details" }));
    const dialog = await screen.findByRole("dialog", { name: "Source S1" });
    expect(within(dialog).getByRole("link", { name: "Open Case Details" })).toHaveAttribute("href", "/cases/c-1/details");
  });

  // design assistant-polish-followups, decision 2: no model was called, so the block is renamed and shown open
  it("S1's dialog shows Facts From the Case Record, open, and no Text Given to the Model", async () => {
    browserApi({ ...pageRoutes([conv()], [question(), FACT]), "GET /me": me("ollama"), "GET /assistant/status": ollamaStatus() });
    renderWithClient(<AssistantPage />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: "Source S1: Case Details" }));
    const dialog = await screen.findByRole("dialog", { name: "Source S1" });
    const summary = within(dialog).getByText("Facts From the Case Record");
    expect(summary.closest("details")).toHaveAttribute("open");
    expect(within(dialog).getByText("Case number: WP(C)/1/2026; Status: pending")).toBeVisible();
    expect(within(dialog).queryByText("Text Given to the Model")).toBeNull();
  });

  it("Sources of This Answer of a quick fact uses the same label", async () => {
    browserApi({ ...pageRoutes([conv()], [question(), FACT]), "GET /me": me("ollama"), "GET /assistant/status": ollamaStatus() });
    renderWithClient(<AssistantPage />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: "Sources (1)" }));
    const dialog = await screen.findByRole("dialog", { name: "Sources of This Answer" });
    expect(within(dialog).getByText("Facts From the Case Record").closest("details")).toHaveAttribute("open");
    expect(within(dialog).queryByText("Text Given to the Model")).toBeNull();
  });

  it("a local-model answer's dialog still shows Text Given to the Model, collapsed", async () => {
    browserApi(localRoutes());
    resetNav(BASE + "/assistant");
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: /^Source S2:/ }));
    const dialog = await screen.findByRole("dialog", { name: "Source S2" });
    expect(within(dialog).getByText("Text Given to the Model").closest("details")).not.toHaveAttribute("open");
    expect(within(dialog).queryByText("Facts From the Case Record")).toBeNull();
  });
});

describe("noteText (design assistant-polish, decision 17)", () => {
  it("labels match markers", () => {
    const s2 = cite({ label: "S2", cited: true });
    const s5 = cite({ document_id: "d-5", order_id: "o-5", order_no: "9", label: "S5", cited: true, passage: null });
    const s3 = cite({ document_id: "d-3", label: "S3", cited: false });
    const out = noteText(localAnswer({ content: "First [S2]. Then [S5].", citations: [DETAILS_UNCITED, s2, s3, s5] }));
    const refs = out.split("From the court records:\n")[1]!.split("\n");
    expect(out.startsWith("First [S2]. Then [S5].")).toBe(true);
    expect(refs.map((r) => r.slice(0, 4))).toEqual(["[S2]", "[S5]"]);
    expect(refs[0]).toBe("[S2] Order of 12 Mar 2026, No. 5, page 2 (WP(C)/1/2026): “The respondents shall file an affidavit within four weeks.”");
    const gone = cite({ label: "S3", cited: true, available: false });
    expect(noteText(localAnswer({ content: "A [S3].", citations: [gone] }))).toBe("A [S3].\n\nFrom the court records:\n[S3] No longer available");
    // a preview answer keeps 1..n
    expect(noteText(answer({ content: "text", citations: [cite(), OTHER] }))).toContain("\n[1] Order of 12 Mar 2026, No. 5");
  });
});

const DETAILS_UNCITED = { ...DETAILS, cited: false };


describe("My Work and the three tabs (design assistant-ollama-work)", () => {
  const QUESTIONS = [
    ["pending_actions", "Pending Actions With Me", "Which of my cases has a pending action due this week?"],
    ["cases_with_me", "Files With Me", "Which case files are with me?"],
    ["sent_by_me", "Files I Sent or Recalled", "Cases I sent in the last 7 days"],
    ["my_hearings", "Hearings of My Cases", "My hearings next week"],
    ["listed_tomorrow", "My Cases Listed Tomorrow", "Which of my cases are listed tomorrow?"],
    ["my_due_dates", "My Due Dates", "What are my due dates this week?"],
    ["unread_alerts", "My Unread Alerts", "Do I have unread alerts?"],
    ["new_orders", "New Orders in My Cases", "Any new orders in my cases this week?"],
    ["claimed_by_me", "Cases I Claimed", "How many cases were claimed by me?"],
  ].map(([key, label, example]) => ({ key: key!, label: label!, example: example! }));

  function workStatus(extra: Partial<AssistantStatus> = {}): AssistantStatus {
    return status({ scopes: ["case", "my_cases", "research", "my_work"], work_questions: QUESTIONS, ...extra });
  }

  function workRow(extra: Partial<AssistantCitation> = {}): AssistantCitation {
    return cite({
      document_id: null,
      order_id: null,
      source_kind: "work_row",
      doc_type_label: null,
      doc_date: null,
      order_no: null,
      page: null,
      passage: null,
      label: "S1",
      case: { id: "c-7", case_no_text: "WP(C)/7/2026", cnr: "ASHC010000072026", visible: true },
      open: { kind: "case_tab", href: "/cases/c-7" },
      work: {
        list_label: "Case Inbox · My Cases · Claimed by Me",
        as_of: "2026-11-14T05:00:00Z",
        fields: { case_no: "WP(C)/7/2026", claimed_on: "2026-11-10", via: "Claimed", department: "EDU", status: "pending" },
      },
      ...extra,
    });
  }

  function workAnswer(extra: Partial<AssistantMessage> = {}): AssistantMessage {
    return answer({
      id: "a-w",
      reply_to_id: "q-w",
      content: "You have claimed 2 cases in all.\nCounted as on your Case Inbox's My Cases tab.\nShowing all 2.",
      citations: [
        workRow(),
        workRow({
          label: "S2",
          available: false,
          unavailable_reason: "A case you can no longer open",
          case: { id: null, case_no_text: null, cnr: null, visible: false },
          open: null,
          work: { list_label: "Case Inbox · My Cases · Claimed by Me", as_of: "2026-11-14T05:00:00Z", fields: {} },
        }),
      ],
      work: {
        question: "claimed_by_me",
        label: "Cases I Claimed",
        chosen_by: "keyword",
        total: 2,
        shown: 2,
        list_label: "Case Inbox · My Cases · Claimed by Me",
        full_list_href: "/inbox/my-cases",
        scan_capped: false,
      },
      ...extra,
    });
  }

  function workRoutes(messages: AssistantMessage[], extra: Record<string, unknown> = {}) {
    return {
      "GET /me": me(),
      "GET /assistant/status": workStatus(),
      "GET /reference/offices": { items: [{ code: "EDU", name: "Education" }] },
      "GET /assistant/conversations": (call: { path: string }) => {
        const scope = new URLSearchParams(call.path.split("?")[1]).get("scope");
        const items = scope === "my_work" ? [conv({ id: "k-1", scope: "my_work", title: "my claims" })] : [];
        return { total: items.length, items };
      },
      "GET /assistant/conversations/k-1": thread(messages, conv({ scope: "my_work" })),
      ...extra,
    };
  }

  it("the helpers: the case tab's one scope, the page's tabs by status and the fallback", () => {
    expect(scopesFor("case")).toEqual(["case"]);
    expect(scopesFor("page")).toEqual(["my_work", "my_cases", "research"]);
    expect(pageScopes(workStatus())).toEqual(["my_work", "my_cases", "research"]);
    expect(pageScopes(status({ scopes: ["case", "my_cases", "research"] }))).toEqual(["my_cases", "research"]);
    expect(pageScopes(undefined)).toEqual([]);
    const all = pageScopes(workStatus());
    expect(scopeForTab("court-orders", all)).toBe("research");
    expect(scopeForTab(null, all)).toBe("my_work");
    expect(scopeForTab("nonsense", all)).toBe("my_work");
    expect(scopeForTab("my-work", ["my_cases", "research"])).toBe("my_cases");
    expect(workValue("claimed_on", "2026-11-10")).toBe(nb("10 Nov 2026"));
    expect(workValue("due_soon", true)).toBe("Yes");
    expect(workValue("overdue_days", 0)).toBeNull();
    expect(workValue("overdue_days", 3)).toBe("3 days");
    expect(workValue("sent_by", { name: "Off One", designation: "Under Secretary", office_name: "Education" })).toBe(
      "Off One, Under Secretary, Education",
    );
    expect(workValue("status", "pending")).toBe("Pending");
    expect(workValue("next_hearing", { date: "2026-12-01", kind: "around" })).toBe(`Around ${nb("1 Dec 2026")}`);
  });

  it("the labels guard: every work field has a Title Case label, and no field names text, remarks or reasons", () => {
    for (const [question, fields] of Object.entries(WORK_COLUMNS)) {
      for (const field of fields) {
        const label = T.assistant.workFields[field];
        expect(label, `${question}.${field}`).toBeTruthy();
        expect(isTitleCase(label!), label).toBe(true);
        expect(["remark", "body", "note", "text", "reasons", "ref_no", "score_signals"]).not.toContain(field);
      }
    }
  });

  it("the sidebar's tabs come from the scopes, My Work first and opened by default", async () => {
    browserApi(workRoutes([]));
    renderWithClient(<AssistantPage />);
    const tabs = await screen.findByRole("navigation", { name: "Assistant Tabs" });
    await waitFor(() => expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toEqual(["My Work", "My Cases", "All Court Orders"]));
    expect(within(tabs).getByRole("link", { name: "My Work" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "My Work" })).toHaveAttribute("href", "/assistant?tab=my-work");
    expect(
      await screen.findByText(
        "Answers from your own lists: Case Inbox, Case Claim, My Calendar, Alerts and your dashboard. Note text, remarks and documents are never used here.",
      ),
    ).toBeInTheDocument();
  });

  it("missing in sourcetrace mode, and ?tab= honoured with its fallback", async () => {
    browserApi({ ...workRoutes([]), "GET /assistant/status": status({ mode: "sourcetrace", state: "ready", banner: null }) });
    const first = renderWithClient(<AssistantPage tab="my-work" />);
    const tabs = await screen.findByRole("navigation", { name: "Assistant Tabs" });
    expect(within(tabs).queryByRole("link", { name: "My Work" })).toBeNull();
    expect(within(tabs).getByRole("link", { name: "My Cases" })).toHaveAttribute("aria-current", "page");
    first.unmount();
    browserApi(workRoutes([]));
    renderWithClient(<AssistantPage tab="court-orders" />);
    const again = await screen.findByRole("navigation", { name: "Assistant Tabs" });
    await waitFor(() => expect(within(again).getByRole("link", { name: "All Court Orders" })).toHaveAttribute("aria-current", "page"));
  });

  it("switching tabs asks nothing again and puts the tab in the address", async () => {
    const api = browserApi(workRoutes([question("q-w", "how many cases were claimed by me?"), workAnswer()]));
    renderWithClient(<AssistantPage />);
    const tabs = await screen.findByRole("navigation", { name: "Assistant Tabs" });
    await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(within(tabs).getByRole("link", { name: "All Court Orders" }));
    expect(nav.replace).toHaveBeenCalledWith("/assistant?tab=court-orders");
    await waitFor(() => expect(within(tabs).getByRole("link", { name: "All Court Orders" })).toHaveAttribute("aria-current", "page"));
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    const lists = api.calls.filter((c) => c.path.startsWith("/assistant/conversations?"));
    expect(lists.map((c) => new URLSearchParams(c.path.split("?")[1]).get("scope"))).toContain("research");
  });

  it("a failed status read shows the error with Try Again, not the loading lines for ever; Try Again opens the tabs", async () => {
    let fail = true;
    const api = browserApi({
      ...workRoutes([]),
      "GET /assistant/status": () => (fail ? json(500, { detail: "boom" }) : workStatus()),
    });
    renderWithClient(<AssistantPage />);
    const alert = await screen.findByRole("alert");
    const retry = within(alert).getByRole("button", { name: "Try Again" });
    expect(screen.getByRole("heading", { name: "Assistant" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Assistant Tabs" })).toBeNull();
    expect(screen.queryByRole("log", { name: "Conversation" })).toBeNull();
    expect(api.calls.some((c) => c.path.startsWith("/assistant/conversations"))).toBe(false);
    fail = false;
    await userEvent.click(retry);
    const tabs = await screen.findByRole("navigation", { name: "Assistant Tabs" });
    await waitFor(() => expect(within(tabs).getByRole("link", { name: "My Work" })).toHaveAttribute("aria-current", "page"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a network failure of the status shows the same error; the case tab goes on without the status", async () => {
    const down = () => {
      throw new TypeError("Failed to fetch");
    };
    browserApi({ ...workRoutes([]), "GET /assistant/status": down });
    const page = renderWithClient(<AssistantPage />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("button", { name: "Try Again" })).toBeInTheDocument();
    page.unmount();
    browserApi({
      "GET /me": me(),
      "GET /assistant/status": down,
      [`GET ${BASE}`]: caseDetail(),
      "GET /assistant/conversations": { total: 1, items: [conv({ scope: "case" })] },
      "GET /assistant/conversations/k-1": thread([question(), answer()]),
    });
    resetNav(`${BASE}/assistant`);
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const log = await screen.findByRole("log", { name: "Conversation" });
    await within(log).findByText("what did the court direct");
  });

  it("six example chips, then More Examples (n) for the rest", async () => {
    browserApi({ ...workRoutes([]), "GET /assistant/conversations": { total: 0, items: [] } });
    renderWithClient(<AssistantPage tab="my-work" />);
    const chips = await screen.findByRole("group", { name: "Suggested Questions" });
    expect(within(chips).getAllByRole("button")).toHaveLength(6);
    const more = screen.getByRole("button", { name: "More Examples (3)" });
    await userEvent.click(more);
    expect(within(chips).getAllByRole("button")).toHaveLength(9);
    await userEvent.click(within(chips).getByRole("button", { name: "How many cases were claimed by me?" }));
    expect((screen.getByLabelText("Question") as HTMLTextAreaElement).value).toBe("How many cases were claimed by me?");
  });

  it("a work answer: From Your Lists, the chosen-by line, the count first, the rows with case links, as of and the full list", async () => {
    browserApi(workRoutes([question("q-w", "how many cases were claimed by me?"), workAnswer()]));
    renderWithClient(<AssistantPage tab="my-work" />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    const card = await within(box).findByRole("group", { name: "Assistant (Your Lists) 1" });
    expect(within(card).getByText("From Your Lists")).toBeInTheDocument();
    expect(within(card).getByText("Matched by Keywords")).toBeInTheDocument();
    expect(within(card).getByText(/^You have claimed 2 cases in all\./)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "WP(C)/7/2026" })).toHaveAttribute("href", "/cases/c-7");
    expect(within(card).getByText("A case you can no longer open")).toBeInTheDocument();
    expect(within(card).getByText(/^As of /)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open the Full List" })).toHaveAttribute("href", "/inbox/my-cases");
    expect(within(card).getByText("Claimed")).toBeInTheDocument();
    // no markers, no Sources button, no Copy to Note
    expect(within(card).queryByRole("button", { name: /^S\d/ })).toBeNull();
    expect(within(card).queryByRole("button", { name: /Sources/ })).toBeNull();
    expect(within(card).queryByRole("button", { name: "Copy to Note" })).toBeNull();
  });

  it("the suggestion line's Ask in My Work opens the My Work tab and asks there, only on the click", async () => {
    const flagged = answer({ id: "a-s", reply_to_id: "q-s", suggest_work: true });
    const api = browserApi({
      ...workRoutes([]),
      "GET /assistant/conversations": (call: { path: string }) => {
        const scope = new URLSearchParams(call.path.split("?")[1]).get("scope");
        const items = scope === "my_cases" ? [conv({ id: "k-1", scope: "my_cases" })] : [];
        return { total: items.length, items };
      },
      "GET /assistant/conversations/k-1": thread([question("q-s", "how many cases were claimed by me?"), flagged], conv({ scope: "my_cases" })),
      "POST /assistant/ask": {
        conversation: conv({ id: "k-9", scope: "my_work" }),
        question: question("q-9", "how many cases were claimed by me?"),
        answer: workAnswer({ id: "a-9", reply_to_id: "q-9" }),
      },
    });
    renderWithClient(<AssistantPage tab="my-cases" />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    expect(await within(box).findByText("This looks like a question about your own work. Ask it in My Work?")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(box).getByRole("button", { name: "Ask in My Work" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ question: "how many cases were claimed by me?", scope: "my_work", include_related: true });
    expect(nav.replace).toHaveBeenCalledWith("/assistant?tab=my-work");
    const tabs = screen.getByRole("navigation", { name: "Assistant Tabs" });
    await waitFor(() => expect(within(tabs).getByRole("link", { name: "My Work" })).toHaveAttribute("aria-current", "page"));
  });
});
