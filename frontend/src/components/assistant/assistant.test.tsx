import { screen, waitFor, within } from "@testing-library/react";
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
import { highlights, noteText, sourceLink } from "@/lib/assistant";
import { ASSISTANT_ERRORS } from "@/lib/messages";
import { CASE_TABS, navFor, showsAssistant } from "@/lib/routes";
import { caseDetail, REF } from "@/test/claimFixtures";
import { resetNav } from "@/test/nav";
import { browserApi, json, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { AssistantPage, CaseAssistant } from "./Assistant";
import { CourtOrderView } from "./CourtOrderView";

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
  return { id, role: "user", created_at: "2026-10-23T10:12:00Z", content, citations: [] };
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
    expect(screen.getByRole("radiogroup", { name: "Search in" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "My cases" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("radio", { name: "This case" })).toBeNull();
    expect(screen.getByText("Conversations are private to you and cannot be deleted.")).toBeInTheDocument();
    expect(screen.getByText(/26 questions left this hour of 30/)).toBeInTheDocument();
  });

  it("sources open the file at the page, a case the reader cannot open opens the court-record view, related apart", async () => {
    browserApi(pageRoutes([conv()], [question(), answer()]));
    renderWithClient(<AssistantPage />);
    const panel = await screen.findByRole("complementary", { name: "Sources used" });
    const own = await within(panel).findByRole("link", { name: /Open source 1: Order of 12 Mar 2026, No\. 5, page 2/ });
    expect(own).toHaveAttribute("href", "/api/backend/cases/c-1/orders/o-1/file?disposition=inline#page=2");
    expect(own).toHaveAttribute("target", "_blank");
    const related = within(panel).getByRole("list", { name: "Related orders in other cases" });
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
    const panel = screen.getByRole("complementary", { name: "Sources used" });
    expect(within(panel).getByText("This source is no longer available to you")).toBeInTheDocument();
    expect(within(panel).queryByRole("link")).toBeNull();
    expect(panel.textContent).not.toMatch(/Petition|Order of|page/);
  });

  it("a failed answer and a question without an answer are in words", async () => {
    const failed = answer({ outcome: "failed", content: "x", error: { family: "scope", message: "x" }, citations: [] });
    browserApi(pageRoutes([conv()], [question(), failed, question("q-2", "lost question")]));
    renderWithClient(<AssistantPage />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    expect(await within(box).findByText("The answer drew on material outside your reach and was withheld.")).toBeInTheDocument();
    expect(within(box).getByText("Not answered")).toBeInTheDocument();
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
    const chips = await screen.findByRole("group", { name: "Suggested questions" });
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

  it("starts on This case with the scope line, Ask secondary, and opens the latest case conversation", async () => {
    const api = browserApi(caseRoutes());
    resetNav(`${BASE}/assistant`);
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const group = await screen.findByRole("radiogroup", { name: "Search in" });
    expect(within(group).getAllByRole("radio").map((r) => r.textContent)).toEqual(["This case", "My cases", "All court orders"]);
    expect(within(group).getByRole("radio", { name: "This case" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/Searches this case's court orders/)).toBeInTheDocument();
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
    await userEvent.click(await within(box).findByRole("button", { name: "Copy to note" }));
    const dialog = await screen.findByRole("dialog");
    const note = (await within(dialog).findByLabelText("Note")) as HTMLTextAreaElement;
    expect(note.value).toContain("2 passages from 2 documents matched");
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
    expect(within(box).queryByRole("button", { name: "Copy to note" })).toBeNull();
  });

  it("switching the scope searches the last question again there", async () => {
    const api = browserApi(
      caseRoutes({
        "POST /assistant/ask": (call: { body: unknown }) => ({
          conversation: conv({ id: "k-2", scope: (call.body as { scope: "research" }).scope }),
          question: question("q-5"),
          answer: answer({ id: "a-5", reply_to_id: "q-5" }),
        }),
      }),
    );
    resetNav(`${BASE}/assistant`);
    renderWithClient(<CaseAssistant caseRef={REF} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await within(box).findByText("what did the court direct");
    await userEvent.click(screen.getByRole("radio", { name: "All court orders" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    // in the latest conversation of that scope
    expect(post.body).toEqual({ question: "what did the court direct", scope: "research", conversation_id: "k-1", include_related: true });
    expect(screen.getByText(/Searches court orders of all cases in ASLMS/)).toBeInTheDocument();
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
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Court record: WP(C)/202/2026");
    expect(screen.getByText("R. DAS; THE STATE OF ASSAM")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the order" })).toHaveAttribute(
      "href",
      "/api/backend/assistant/court-orders/o-2/file?message=a-1&disposition=inline",
    );
    expect(screen.queryByRole("link", { name: "Open the case page" })).toBeNull();
    expect(primaryActions(document.body)).toEqual(["Open the order"]);
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
