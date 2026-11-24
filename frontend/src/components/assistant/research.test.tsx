/**
 * Design research-index-portal, "Tests" (frontend): the research notice, the filters shown only when served, the
 * address round trip, the body sent, the field checks, the choice field, the refusals in words, the question chips, the
 * passage view, Text Has Changed, Show the Passage, the court-record passage, the removal block, the withheld reason,
 * the retrieval hint and the same-words line, the Research Index section of Data Collection and `formatBytes`.
 */
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ResearchIndexBody, ResearchIndexSection } from "@/components/data/ResearchIndexSection";
import type {
  AssistantCitation,
  AssistantConversation,
  AssistantMessage,
  AssistantPassage,
  AssistantStatus,
  Me,
  Permission,
  ResearchIndexStatus,
} from "@/lib/api/types";
import { sourceLink } from "@/lib/assistant";
import { formatBytes } from "@/lib/format";
import { ASSISTANT_ERRORS } from "@/lib/messages";
import {
  actKey,
  checkFilters,
  filterChips,
  filtersBody,
  filtersServed,
  NO_FILTERS,
  passageRuns,
  readFilters,
  removedReasons,
  researchNotice,
  splitRemoved,
  storedFilters,
  withheldLine,
  writeFilters,
} from "@/lib/research";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, makeMe, renderWithClient } from "@/test/render";

import actCases from "./actKeyCases.json";
import { AssistantPage, FILTER_ADDRESS_DEBOUNCE_MS } from "./Assistant";
import { CourtOrderView } from "./CourtOrderView";
import { PassageView } from "./PassageView";
import { ChoiceField } from "./ResearchFilters";

const FNS: Permission[] = ["cases.view_scope", "documents.view", "assistant.use"];

function me(functions: Permission[] = FNS): Me {
  return makeMe(functions, "dept_officer", { assistant_mode: "ollama" });
}

type Research = NonNullable<AssistantStatus["research"]>;

function status(research: Research | null = { state: "ready", coverage: 1 }, extra: Partial<AssistantStatus> = {}): AssistantStatus {
  return {
    mode: "ollama",
    state: "ready",
    banner: null,
    limits: { questions_per_hour: 30, used_last_hour: 0, question_max_chars: 2000, messages_per_conversation: 200 },
    scopes: ["case", "my_cases", "research", "my_work"],
    engine: { kind: "ollama", model: "qwen3.5:4b", readiness: "ready", reason: null },
    internal_records: "switch",
    work_questions: [],
    ...(research ? { research } : {}),
    ...extra,
  };
}

function conv(extra: Partial<AssistantConversation> = {}): AssistantConversation {
  return {
    id: "k-1",
    scope: "research",
    case: null,
    title: "orders on regularisation",
    last_message_at: "2026-11-24T10:12:00Z",
    created_at: "2026-11-24T10:12:00Z",
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
    passage: "The respondents shall [[regularise]] the teachers.",
    related: false,
    available: true,
    open: { kind: "document", href: "/cases/c-1/orders/o-1/file?disposition=inline" },
    label: "S1",
    cited: true,
    context: "The respondents shall regularise the teachers.",
    note: null,
    internal: false,
    what: null,
    visibility: null,
    quotes: [],
    text_changed: false,
    src: [100, 160],
    ...extra,
  };
}

function question(extra: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: "q-1",
    role: "user",
    created_at: "2026-11-24T10:12:00Z",
    content: "orders on regularisation of contractual teachers",
    citations: [],
    engine: null,
    checks: null,
    internal_used: false,
    suggest_internal: false,
    suggest_work: false,
    filters: null,
    ...extra,
  };
}

const REMOVED_LINE =
  "[Removed by ASLMS: 2 sentences whose quotes, dates, numbers, case numbers, names or outcomes were not found in the records they cite.]";

function answer(extra: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: "a-1",
    role: "assistant",
    created_at: "2026-11-24T10:12:01Z",
    content: "The court directed regularisation [S1].",
    mode: "ollama",
    outcome: "answered",
    error: null,
    hidden_reason: null,
    engine: { kind: "ollama", model: "qwen3.5:4b" },
    checks: { invalid_markers: 0, cut_short: false, sentences: 3, kept: 1, removed: { uncited: 0 }, withheld: null },
    retrieval: { kind: "hybrid" },
    internal_used: false,
    suggest_internal: false,
    suggest_work: false,
    reply_to_id: "q-1",
    citations: [cite()],
    filters: null,
    ...extra,
  };
}

const PASSAGE: AssistantPassage = {
  order_id: "o-1",
  document_id: "d-1",
  page: 2,
  page_count: 5,
  page_text: "1. Heard counsel.\n2. The respondents shall regularise the teachers within 3 months.\n3. Disposed.",
  highlights: [
    { start: 18, end: 82, kind: "passage", exact: true },
    { start: 37, end: 61, kind: "quote", exact: true },
  ],
  text_changed: false,
};

function routes(messages: AssistantMessage[], extra: Record<string, unknown> = {}, st: AssistantStatus = status()) {
  return {
    "GET /me": me(),
    "GET /assistant/status": st,
    "GET /assistant/conversations": { total: 1, items: [conv()] },
    "GET /assistant/conversations/k-1": { conversation: conv(), messages, has_more: false },
    ...extra,
  };
}

beforeEach(() => {
  resetNav("/assistant", "tab=court-orders");
});

afterEach(() => {
  vi.useRealTimers();
});

// ------------------------------------------------------------------------------------------------ research notice

describe("research notice (decision 4)", () => {
  it("no notice for ready; building with a whole percent and under 1%", () => {
    expect(researchNotice(status({ state: "ready", coverage: 1 }), "research")).toBeNull();
    expect(researchNotice(status({ state: "building", coverage: 0.627 }), "research")?.text).toBe(
      "The meaning search is still being built: 62% of court orders are in it so far. Orders not yet in it are found by their words.",
    );
    expect(researchNotice(status({ state: "building", coverage: 0.004 }), "my_cases")?.text).toContain("under 1% of court orders");
  });

  it("building with null coverage says it could not be read: no percent, no 0%, no ready", () => {
    const n = researchNotice(status({ state: "building", coverage: null }), "research")!;
    expect(n.tone).toBe("hint");
    expect(n.text).toBe(
      "The meaning search is on. How much of it is built could not be read just now; orders not yet in it are found by their words.",
    );
    expect(n.text).not.toMatch(/%|\b0\b|ready/i);
    expect(n.text).not.toMatch(/unavailable|not available/i);
  });

  it("the warning for unavailable; nothing for off and nothing on the case tab", () => {
    expect(researchNotice(status({ state: "unavailable", coverage: null }), "research")).toEqual({
      tone: "warning",
      text: "The meaning search is not available right now, so answers are found by their words only. Filters still apply.",
    });
    expect(researchNotice(status({ state: "off", coverage: null }), "research")).toBeNull();
    expect(researchNotice(status({ state: "building", coverage: 0.5 }), "case")).toBeNull();
    expect(researchNotice(status({ state: "building", coverage: 0.5 }), "my_work")).toBeNull();
  });

  it("the page shows the warning notice and the filters for unavailable", async () => {
    browserApi(routes([], {}, status({ state: "unavailable", coverage: null })));
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    expect(await screen.findByText(/The meaning search is not available right now/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Search Filters" })).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------ filters shown

describe("filters shown only when served (decision 3)", () => {
  it("hidden for off, preview and sourcetrace, on My Work and the case tab; shown for building, ready, unavailable", () => {
    expect(filtersServed(status({ state: "off", coverage: null }), "research")).toBe(false);
    expect(filtersServed(status(null, { mode: "preview", state: "preview" }), "research")).toBe(false);
    expect(filtersServed(status({ state: "ready", coverage: 1 }, { mode: "sourcetrace" }), "research")).toBe(false);
    expect(filtersServed(status(), "my_work")).toBe(false);
    expect(filtersServed(status(), "case")).toBe(false);
    for (const state of ["building", "ready", "unavailable"] as const) {
      expect(filtersServed(status({ state, coverage: 0.5 }), "research")).toBe(true);
      expect(filtersServed(status({ state, coverage: 0.5 }), "my_cases")).toBe(true);
    }
  });

  it("the page has no filters on My Work", async () => {
    browserApi(routes([]));
    renderWithClient(<AssistantPage tab="my-work" params={{ tab: "my-work" }} />);
    await screen.findByRole("log", { name: "Conversation" });
    await waitFor(() => expect(screen.getByRole("link", { name: "My Work" })).toHaveAttribute("aria-current", "page"));
    expect(screen.queryByRole("button", { name: /Search Filters/ })).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ the address

describe("filters round-trip the address (decision 8)", () => {
  it("parameters are read and written; unknown values are dropped", () => {
    const f = readFilters(
      new URLSearchParams("forms=final,judgment,odd&substantive=1&outcomes=dismissed,won&against_state=1&cites=(2006) 4 SCC 1&act=arms act&from=2024-01-01&to=2024-02-30"),
    );
    expect(f.forms).toEqual(["judgment", "final"]);
    expect(f.outcomes).toEqual(["dismissed"]);
    expect(f.substantive && f.againstState).toBe(true);
    expect(f.from).toBe("2024-01-01");
    expect(f.to).toBe(""); // not a calendar day
    expect(f.dateMode).toBe("range");
    expect(writeFilters(f)).toEqual({
      forms: "judgment,final",
      substantive: "1",
      outcomes: "dismissed",
      against_state: "1",
      cites: "(2006) 4 SCC 1",
      act: "arms act",
      from: "2024-01-01",
    });
    expect(readFilters({ from: "2025-03-01", to: "2025-03-01" }).dateMode).toBe("date");
  });

  it("a change goes into the address with router.replace; the tab change drops them", async () => {
    browserApi(routes([]));
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders", forms: "judgment" }} />);
    const button = await screen.findByRole("button", { name: "Search Filters (1)" });
    expect(screen.getByRole("list", { name: "Applied Filters" })).toHaveTextContent("Judgment");
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(screen.getByRole("checkbox", { name: "Substantive Orders Only" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/assistant?tab=court-orders&forms=judgment&substantive=1", { scroll: false });
    await userEvent.click(screen.getByRole("link", { name: "My Cases" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/assistant?tab=my-cases");
    await waitFor(() => expect(screen.getByRole("button", { name: "Search Filters" })).toBeInTheDocument());
    expect(screen.queryByRole("list", { name: "Applied Filters" })).toBeNull();
  });

  it("typing in Cites a Judgment writes the address once the typing pauses, not per keystroke; a tab change drops it", async () => {
    browserApi(routes([], { "GET /assistant/filter-choices": { ready: true, items: [] } }));
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Search Filters" }));
    const field = screen.getByRole("combobox", { name: "Cites a Judgment" });
    await userEvent.type(field, "2006 4");
    const citesWrites = () => nav.replace.mock.calls.filter(([href]) => String(href).includes("cites="));
    expect(citesWrites()).toHaveLength(0);
    expect(field).toHaveValue("2006 4");
    await waitFor(() => expect(citesWrites()).toHaveLength(1), { timeout: FILTER_ADDRESS_DEBOUNCE_MS * 4 });
    expect(nav.replace).toHaveBeenLastCalledWith("/assistant?tab=court-orders&cites=2006+4", { scroll: false });

    // a write still waiting when the tab changes never lands on the new tab's address
    await userEvent.type(field, "x");
    await userEvent.click(screen.getByRole("link", { name: "My Cases" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/assistant?tab=my-cases");
    await act(() => new Promise((r) => setTimeout(r, FILTER_ADDRESS_DEBOUNCE_MS * 2)));
    expect(nav.replace).toHaveBeenLastCalledWith("/assistant?tab=my-cases");
    expect(citesWrites()).toHaveLength(1);
  });

  it("filters in the address while the panel is hidden: the notice with Clear Filters, and nothing is sent", async () => {
    const api = browserApi(
      routes([], {
        "POST /assistant/ask": { conversation: conv(), question: question({ id: "q-9" }), answer: answer({ id: "a-9", reply_to_id: "q-9" }) },
      }, status({ state: "off", coverage: null })),
    );
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders", forms: "judgment" }} />);
    expect(await screen.findByText("The filters in this address are not used: the meaning search is switched off.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Search Filters/ })).toBeNull();
    await userEvent.type(screen.getByLabelText("Question"), "orders on transfer");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect((api.calls.find((c) => c.method === "POST")!.body as Record<string, unknown>).filters).toBeUndefined();
    await userEvent.click(screen.getByRole("button", { name: "Clear Filters" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/assistant?tab=court-orders", { scroll: false });
    await waitFor(() => expect(screen.queryByText(/The filters in this address are not used/)).toBeNull());
  });
});

// ------------------------------------------------------------------------------------------------ the body

describe("ask sends exactly the filters in view (decision 9)", () => {
  it("uses the keys from and to; omitted when none is set", () => {
    expect(filtersBody(NO_FILTERS)).toBeUndefined();
    expect(filtersBody({ ...NO_FILTERS, forms: ["final", "judgment"], dateMode: "range", from: "2024-01-01", to: "2024-12-31" })).toEqual({
      forms: ["judgment", "final"],
      from: "2024-01-01",
      to: "2024-12-31",
    });
    expect(filtersBody({ ...NO_FILTERS, dateMode: "date", from: "2024-05-01" })).toEqual({ from: "2024-05-01", to: "2024-05-01" });
    expect(filtersBody({ ...NO_FILTERS, cites: "  (2006)   4 SCC 1 " })).toEqual({ cites: "(2006) 4 SCC 1" });
  });

  it("the page sends the filters of the address; My Work never sends any", async () => {
    const api = browserApi(
      routes([], {
        "POST /assistant/ask": {
          conversation: conv(),
          question: question({ id: "q-9", filters: { forms: ["judgment"], against_state: true } }),
          answer: answer({ id: "a-9", reply_to_id: "q-9" }),
        },
      }),
    );
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders", forms: "judgment", against_state: "1" }} />);
    await screen.findByRole("button", { name: "Search Filters (2)" });
    await userEvent.type(screen.getByLabelText("Question"), "orders on regularisation");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const body = api.calls.find((c) => c.method === "POST")!.body as Record<string, unknown>;
    expect(body).toEqual({
      question: "orders on regularisation",
      scope: "research",
      conversation_id: "k-1",
      include_related: true,
      filters: { forms: ["judgment"], against_state: true },
    });
    // the question shows its chips (decision 9)
    const chips = await screen.findByRole("list", { name: "Asked with These Filters" });
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Judgment", "Against the State (Read by Rule)"]);
  });
});

// ------------------------------------------------------------------------------------------------ field checks

describe("field checks (decision 7)", () => {
  it("From after To and a citation over 80 characters show their errors", () => {
    expect(checkFilters({ ...NO_FILTERS, dateMode: "range", from: "2025-02-01", to: "2025-01-01" }).to).toBe("From must be on or before To");
    expect(checkFilters({ ...NO_FILTERS, cites: "x".repeat(81) }).cites).toBe("At most 80 characters");
    expect(checkFilters({ ...NO_FILTERS, cites: "x".repeat(80) })).toEqual({});
  });

  it("Ask stays disabled while a field is in error", async () => {
    browserApi(routes([]));
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders", from: "2025-02-01", to: "2025-01-01" }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Search Filters (1)" }));
    expect(await screen.findByText("From must be on or before To")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Question"), "orders on regularisation");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });
});

// ------------------------------------------------------------------------------------------------ choice field

function Harness({ kind = "act" as "act" | "cites", onPick = vi.fn() }) {
  return <ChoiceHarness kind={kind} onPick={onPick} />;
}

function ChoiceHarness({ kind, onPick }: { kind: "act" | "cites"; onPick: (o: unknown) => void }) {
  const [text, setText] = useState("");
  return <ChoiceField kind={kind} label="Act" text={text} onText={setText} onPick={onPick} />;
}


const CHOICES = {
  kind: "act",
  ready: true,
  items: [
    { value: "assam land revenue regulation 1886", label: "Assam Land Revenue Regulation, 1886", detail: null, orders: 12 },
    { value: "arms act", label: "Arms Act", detail: null, orders: 1 },
  ],
};

describe("choice field (decision 10)", () => {
  it("waits for 2 characters and a 250 ms pause; arrow keys, Enter and Escape; options read label · n orders", async () => {
    const api = browserApi({ "GET /assistant/filter-choices": CHOICES });
    const picked = vi.fn();
    renderWithClient(<Harness onPick={picked} />);
    const box = screen.getByRole("combobox", { name: "Act" });
    await userEvent.type(box, "a");
    expect(await screen.findByText("Type at least 2 characters")).toBeInTheDocument();
    expect(api.calls.length).toBe(0);
    await userEvent.type(box, "s");
    expect(api.calls.length).toBe(0); // still inside the pause
    const first = await screen.findByRole("option", { name: "Assam Land Revenue Regulation, 1886 · 12 orders" });
    expect(screen.getByRole("option", { name: "Arms Act · 1 order" })).toBeInTheDocument();
    expect(api.calls[0]!.url).toContain("kind=act");
    expect(api.calls[0]!.url).toContain("q=as");
    expect(first).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: "Arms Act · 1 order" })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Enter}");
    expect(picked).toHaveBeenCalledWith(CHOICES.items[1]);
    await userEvent.type(box, "x");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("ready false shows its line and typing still works", async () => {
    browserApi({ "GET /assistant/filter-choices": { kind: "act", ready: false, items: [] } });
    renderWithClient(<Harness />);
    const box = screen.getByRole("combobox", { name: "Act" });
    await userEvent.type(box, "assam");
    expect((await screen.findAllByText("The list is being prepared; type the name, or try again in a minute.")).length).toBeGreaterThan(0);
    expect(box).toHaveValue("assam");
  });

  it("the error state with Try Again; Enter retries only then", async () => {
    let calls = 0;
    browserApi({
      "GET /assistant/filter-choices": () => {
        calls += 1;
        return calls === 1 ? json(500, { detail: { code: "internal", message: "x" } }) : CHOICES;
      },
    });
    const picked = vi.fn();
    renderWithClient(<Harness onPick={picked} />);
    const box = screen.getByRole("combobox", { name: "Act" });
    await userEvent.type(box, "as");
    expect(await screen.findByRole("button", { name: "Try Again" })).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("option", { name: /Assam Land Revenue/ })).toBeInTheDocument();
    expect(picked).not.toHaveBeenCalled();
    expect(calls).toBe(2);
  });

  it("a typed act is normalised by row 250's rule (the table shared with the backend)", () => {
    for (const [raw, key] of actCases as [string, string][]) expect(actKey(raw)).toBe(key);
  });
});

// ------------------------------------------------------------------------------------------------ refusals

describe("filter errors in words (decision 11)", () => {
  it("the three codes", () => {
    expect(ASSISTANT_ERRORS.filters_unavailable!({})).toBe(
      "Filters cannot be used right now: the meaning search is switched off. Clear the filters to ask.",
    );
    expect(ASSISTANT_ERRORS.bad_filter!({})).toBe("One of the filters is not recognised. Choose the act from the list and keep From on or before To.");
    expect(ASSISTANT_ERRORS.filters_not_allowed!({})).toBe("Filters are for My Cases and All Court Orders only.");
  });

  it("filters_unavailable fetches the status again and keeps the question", async () => {
    let reads = 0;
    browserApi(
      routes([], {
        "GET /assistant/status": () => {
          reads += 1;
          return reads === 1 ? status() : status({ state: "off", coverage: null });
        },
        "POST /assistant/ask": json(400, { detail: { code: "filters_unavailable", message: "x" } }),
      }),
    );
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders", forms: "judgment" }} />);
    await screen.findByRole("button", { name: "Search Filters (1)" });
    await userEvent.type(screen.getByLabelText("Question"), "orders on transfer");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/Filters cannot be used right now/)).toBeInTheDocument();
    expect(screen.getByLabelText("Question")).toHaveValue("orders on transfer");
    await waitFor(() => expect(reads).toBeGreaterThan(1));
    expect(await screen.findByRole("button", { name: "Clear Filters" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Search Filters/ })).toBeNull();
  });

  it("bad_filter on a typed act says so in the act field", async () => {
    browserApi(routes([], { "POST /assistant/ask": json(400, { detail: { code: "bad_filter", message: "no such act key" } }) }));
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders", act: "no such act" }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Search Filters (1)" }));
    await userEvent.type(screen.getByLabelText("Question"), "orders on transfer");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("No order names this act. Choose one from the list.")).toBeInTheDocument();
    expect(screen.getByText(/One of the filters is not recognised/)).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------ question chips

describe("question chips (decision 9)", () => {
  it("the stored filters show under the question after a reload; an act key goes through Title Case", async () => {
    const q = question({
      filters: { forms: ["judgment"], against_state: true, cites: "(2006) 4 SCC 1", act: "assam land revenue regulation 1886", from: "2024-01-01" },
    });
    browserApi(routes([q, answer()]));
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    const chips = await screen.findByRole("list", { name: "Asked with These Filters" });
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent?.replace(/ /g, " "))).toEqual([
      "Judgment",
      "Against the State (Read by Rule)",
      "Cites (2006) 4 SCC 1",
      "Act: Assam Land Revenue Regulation 1886",
      "From 1 Jan 2024",
    ]);
    expect(storedFilters(null)).toBeNull();
    expect(storedFilters({})).toBeNull();
    expect(filterChips({ ...NO_FILTERS, act: "arms act" }, new Map([["arms act", "The Arms Act, 1959"]]))[0]!.label).toBe("Act: The Arms Act, 1959");
  });
});

// ------------------------------------------------------------------------------------------------ passage view

describe("passage view (decisions 12 to 14)", () => {
  it("runs: passage and quote, nested and clipped", () => {
    const runs = passageRuns("abcdefghij", [
      { start: 2, end: 8, kind: "passage", exact: true },
      { start: 4, end: 6, kind: "quote", exact: true },
      { start: 9, end: 99, kind: "passage", exact: true },
      { start: -5, end: 1, kind: "quote", exact: true },
    ]);
    expect(runs).toEqual([
      { text: "a", passage: false, quote: true },
      { text: "b", passage: false, quote: false },
      { text: "cd", passage: true, quote: false },
      { text: "ef", passage: true, quote: true },
      { text: "gh", passage: true, quote: false },
      { text: "i", passage: false, quote: false },
      { text: "j", passage: true, quote: false },
    ]);
  });

  it("the legend only for the parts present; the inexact line; scrolled to the first mark", () => {
    const scrolled = vi.fn();
    const proto = HTMLElement.prototype as unknown as { scrollTo?: unknown };
    const old = proto.scrollTo;
    proto.scrollTo = scrolled;
    try {
      const { unmount } = renderWithClient(<PassageView passage={PASSAGE} />);
      expect(screen.getByText("Page 2 of 5, as ASLMS stored the order's text")).toBeInTheDocument();
      expect(screen.getByText("Shaded: the passage the answer cites.")).toBeInTheDocument();
      expect(screen.getByText("Underlined: words the answer quotes.")).toBeInTheDocument();
      const marks = document.querySelectorAll("mark");
      expect([...marks].map((m) => m.getAttribute("data-kind"))).toEqual(["passage", "quote", "passage"]);
      expect(marks[1]!.textContent).toBe(PASSAGE.page_text.slice(37, 61));
      const box = screen.getByRole("region", { name: "Page Text" });
      expect(box).toHaveAttribute("data-scroll-y");
      expect(scrolled.mock.calls.length + (box.scrollTop >= 0 ? 1 : 0)).toBeGreaterThan(0);
      unmount();
      renderWithClient(
        <PassageView passage={{ ...PASSAGE, highlights: [{ start: 18, end: 82, kind: "passage", exact: false }] }} />,
      );
      expect(screen.queryByText("Underlined: words the answer quotes.")).toBeNull();
      expect(screen.getByText("The quoted words were not found exactly; the whole passage is marked.")).toBeInTheDocument();
    } finally {
      proto.scrollTo = old;
    }
  });

  it("fetched only for an available court-order source with src, once per message and label; a 404 line", async () => {
    const api = browserApi(
      routes([question(), answer({ citations: [cite(), cite({ label: "S2", src: null, document_id: "d-2", order_id: "o-2" })] })], {
        "GET /assistant/messages/a-1/sources/S1/passage": PASSAGE,
        "GET /assistant/messages/a-1/sources/S2/passage": json(404, { detail: { code: "not_found", message: "x" } }),
      }),
    );
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: /^Source S1:/ }));
    const dialog = await screen.findByRole("dialog", { name: "Source S1" });
    expect(await within(dialog).findByText("Page 2 of 5, as ASLMS stored the order's text")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Open the Order" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Source S1" })).toBeNull());
    await userEvent.click(within(box).getByRole("button", { name: /^Source S1:/ }));
    await screen.findByRole("dialog", { name: "Source S1" });
    expect(api.calls.filter((c) => c.path.endsWith("/sources/S1/passage")).length).toBe(1);
    expect(api.calls.some((c) => c.path.endsWith("/sources/S2/passage"))).toBe(false);
  });

  it("a 404 shows the muted line; a failure shows Try Again", async () => {
    browserApi(
      routes([question(), answer()], {
        "GET /assistant/messages/a-1/sources/S1/passage": json(404, { detail: { code: "not_found", message: "x" } }),
      }),
    );
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: /^Source S1:/ }));
    const dialog = await screen.findByRole("dialog", { name: "Source S1" });
    expect(await within(dialog).findByText("The passage cannot be shown for this source.")).toBeInTheDocument();
    expect(within(dialog).getByText("Text Given to the Model")).toBeInTheDocument();
  });

  it("a failed read offers Try Again", async () => {
    browserApi(
      routes([question(), answer()], {
        "GET /assistant/messages/a-1/sources/S1/passage": json(500, { detail: { code: "internal", message: "x" } }),
      }),
    );
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: /^Source S1:/ }));
    const dialog = await screen.findByRole("dialog", { name: "Source S1" });
    expect(await within(dialog).findByRole("button", { name: "Try Again" })).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------ text changed

describe("text changed (decision 15)", () => {
  it("the badge and line in the list and the dialog; the marker's name; the notice without page text; the link kept", async () => {
    const api = browserApi(routes([question(), answer({ citations: [cite({ text_changed: true })] })]));
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    const marker = await within(box).findByRole("button", { name: /^Source S1: .*\(Text Has Changed\)$/ });
    await userEvent.click(within(box).getByRole("button", { name: "Sources (1)" }));
    const list = await screen.findByRole("dialog", { name: "Sources of This Answer" });
    expect(within(list).getByText("Text Has Changed")).toBeInTheDocument();
    expect(within(list).getByText(/This order's stored text has changed since this answer was written/)).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Sources of This Answer" })).toBeNull());
    await userEvent.click(marker);
    const dialog = await screen.findByRole("dialog", { name: "Source S1" });
    const view = within(dialog).getByRole("region", { name: "The Cited Passage" });
    expect(within(view).getByText("Text Has Changed")).toBeInTheDocument();
    expect(view.querySelector("mark")).toBeNull();
    expect(within(view).queryByText(/Page \d+ of/)).toBeNull();
    expect(within(dialog).getByRole("link", { name: "Open the Order" })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.includes("/passage"))).toBe(false);
  });
});

describe("show the passage from the lists (decision 12)", () => {
  it("the ghost button opens that source's dialog", async () => {
    browserApi(routes([question(), answer()], { "GET /assistant/messages/a-1/sources/S1/passage": PASSAGE }));
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    await userEvent.click(await within(box).findByRole("button", { name: "Sources (1)" }));
    const list = await screen.findByRole("dialog", { name: "Sources of This Answer" });
    await userEvent.click(within(list).getByRole("button", { name: "Show the Passage" }));
    const dialog = await screen.findByRole("dialog", { name: "Source S1" });
    expect(await within(dialog).findByText("Page 2 of 5, as ASLMS stored the order's text")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------ court record

describe("court record passage (decision 13)", () => {
  const VIEW = {
    order: { id: "o-2", order_no: "2", order_date: "2026-03-01", kind: "interim", judge: null },
    case: {
      cnr: "ASHC010002022026",
      case_no_text: "WP(C)/202/2026",
      filing_no_text: null,
      court: null,
      bench: null,
      case_type: null,
      year: 2026,
      status: "pending",
      parties: [],
      advocates: [],
      acts: [],
      last_hearing_date: null,
      next_hearing_date: null,
    },
    case_visible: false,
  };

  it("sourceLink adds s only with src", () => {
    const other = cite({ order_id: "o-2", open: { kind: "court_order", href: "/assistant/court-orders/o-2?message=a-1" } });
    expect(sourceLink(other, "a-1")?.href).toBe("/assistant/orders/o-2?m=a-1&s=S1");
    expect(sourceLink({ ...other, src: null }, "a-1")?.href).toBe("/assistant/orders/o-2?m=a-1");
  });

  it("the card shows with s; no card without it or on a 404", async () => {
    browserApi({
      "GET /me": me(),
      "GET /assistant/court-orders/o-2": VIEW,
      "GET /assistant/messages/a-1/sources/S1/passage": { ...PASSAGE, order_id: "o-2" },
    });
    const { unmount } = renderWithClient(<CourtOrderView orderId="o-2" messageId="a-1" sourceLabel="S1" />);
    expect(await screen.findByRole("heading", { name: "The Cited Passage" })).toBeInTheDocument();
    expect(await screen.findByText("Page 2 of 5, as ASLMS stored the order's text")).toBeInTheDocument();
    unmount();
    renderWithClient(<CourtOrderView orderId="o-2" messageId="a-1" />);
    await screen.findByText("This is the court's public record. You cannot open this case in ASLMS.");
    expect(screen.queryByRole("heading", { name: "The Cited Passage" })).toBeNull();
  });

  it("a passage of another order gives no card (an edited s never shows one order's passage under another)", async () => {
    const api = browserApi({ "GET /me": me(), "GET /assistant/court-orders/o-2": VIEW, "GET /assistant/messages/a-1/sources/S1/passage": PASSAGE });
    renderWithClient(<CourtOrderView orderId="o-2" messageId="a-1" sourceLabel="S1" />);
    await screen.findByText("This is the court's public record. You cannot open this case in ASLMS.");
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith("/sources/S1/passage"))).toBe(true));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "The Cited Passage" })).toBeNull());
    expect(screen.queryByText("Page 2 of 5, as ASLMS stored the order's text")).toBeNull();
  });

  it("a 404 gives no card", async () => {
    browserApi({
      "GET /me": me(),
      "GET /assistant/court-orders/o-2": VIEW,
      "GET /assistant/messages/a-1/sources/S1/passage": json(404, { detail: { code: "not_found", message: "x" } }),
    });
    renderWithClient(<CourtOrderView orderId="o-2" messageId="a-1" sourceLabel="S1" />);
    await screen.findByText("This is the court's public record. You cannot open this case in ASLMS.");
    await waitFor(() => expect(screen.queryByRole("heading", { name: "The Cited Passage" })).toBeNull());
  });
});

// ------------------------------------------------------------------------------------------------ check notes

describe("removal block (decision 16)", () => {
  const checks = { invalid_markers: 0, cut_short: false, sentences: 4, kept: 2, removed: { uncited: 1, date: 1, name: 1, quote: 0 }, withheld: null };

  it("the exact server line is split off and never parsed for markers; counts in words with plurals", () => {
    const note = splitRemoved(`The court directed regularisation [S1].\n${REMOVED_LINE}`, checks)!;
    expect(note.body).toBe("The court directed regularisation [S1].");
    expect(note.count).toBe(2);
    expect(note.reasons).toEqual(["Not found in the records they cite: 1 date, 1 name.", "1 stated a fact without a source."]);
    expect(removedReasons({ date: 2, case_no: 3 })).toEqual(["Not found in the records they cite: 2 dates, 3 case numbers."]);
  });

  it("the server line as written when the counts are missing; text that only resembles it is left alone", () => {
    const note = splitRemoved(`Answer.\n${REMOVED_LINE}`, null)!;
    expect(note.reasons).toBeNull();
    expect(note.line).toBe(REMOVED_LINE);
    expect(splitRemoved(`Answer.\n[Removed by ASLMS: some sentences.]`, checks)).toBeNull();
    expect(splitRemoved(`${REMOVED_LINE}\nmore text`, checks)).toBeNull();
  });

  it("the page draws the block; Copy to Note keeps the line (noteText uses the stored text)", async () => {
    browserApi(routes([question(), answer({ content: `The court directed regularisation [S1].\n${REMOVED_LINE}`, checks })]));
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    const block = await within(box).findByRole("note");
    expect(block).toHaveTextContent("ASLMS Removed 2 Sentences");
    expect(block).toHaveTextContent("Not found in the records they cite: 1 date, 1 name.");
    expect(block).toHaveTextContent("These checks cannot catch a wrong reading of correctly quoted text: check the sources.");
    expect(box.textContent).not.toContain("[Removed by ASLMS");
    const { noteText } = await import("@/lib/assistant");
    expect(noteText(answer({ content: `Text [S1].\n${REMOVED_LINE}`, checks }))).toContain(REMOVED_LINE);
  });
});

describe("withheld reason (decision 17)", () => {
  it("one sentence per value, nothing when null", () => {
    const c = (w: "first_sentence" | "majority" | "none_cited" | null) => ({ invalid_markers: 0, cut_short: false, withheld: w });
    expect(withheldLine("no_match", c("first_sentence"))).toBe(
      "ASLMS held back the model's answer: its main point was not found in the records it cites.",
    );
    expect(withheldLine("no_match", c("majority"))).toContain("most of its sentences");
    expect(withheldLine("no_match", c("none_cited"))).toBe("ASLMS held back the model's answer: no sentence cited a record.");
    expect(withheldLine("no_match", c(null))).toBeNull();
    expect(withheldLine("answered", c("majority"))).toBeNull();
  });
});

describe("retrieval hint and same words (decision 5)", () => {
  it("words_only gives its hint, the other kinds none; same_words_in gives its line", async () => {
    browserApi(
      routes([
        question(),
        answer({ retrieval: { kind: "words_only", reason: "timeout" }, citations: [cite({ same_words_in: 3 })] }),
        question({ id: "q-2" }),
        answer({ id: "a-2", reply_to_id: "q-2", retrieval: { kind: "hybrid" } }),
      ]),
    );
    renderWithClient(<AssistantPage tab="court-orders" params={{ tab: "court-orders" }} />);
    const box = await screen.findByRole("log", { name: "Conversation" });
    expect(await within(box).findAllByText("Found by words only this time: the meaning search did not answer in time.")).toHaveLength(1);
    await userEvent.click(within(box).getAllByRole("button", { name: "Sources (1)" })[0]!);
    const list = await screen.findByRole("dialog", { name: "Sources of This Answer" });
    expect(within(list).getByText("The same words are in 3 other orders.")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------ data collection

function block(extra: Partial<ResearchIndexStatus> = {}): ResearchIndexStatus {
  return {
    enabled: true,
    live_model_key: "embeddinggemma:300m@85462619ee72",
    readiness: "held",
    chunks: { order_body: 361451, case_sheet: 84898, total: 446349 },
    vectors_live: 276736,
    waiting: 169613,
    coverage: 0.62,
    other_keys: { "nomic-embed-text@1234": 1200 },
    failures_open: 3,
    last_run: { started_at: "2026-11-24T15:28:00Z", finished_at: "2026-11-24T20:51:00Z", status: "succeeded", counters: { embedded: 446291, cut: 257141 } },
    last_reconcile: null,
    table_sizes: { research_chunks: 1288490188, research_embeddings: 1610612736 },
    timed_out: [],
    ...extra,
  };
}

const HEALTH_FNS: Permission[] = ["reports.state"];

describe("data collection research section (decisions 18 and 19)", () => {
  it("hidden without a health-reader function; one shared data-health query", async () => {
    const api = browserApi({ "GET /me": makeMe(["admin.data_load"], "central_operator") });
    renderWithClient(<ResearchIndexSection />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.queryByRole("heading", { name: "Research Index" })).toBeNull();
    expect(api.calls.some((c) => c.path === "/admin/data-health")).toBe(false);
  });

  it("the section with readiness, live key, coverage, failures link, earlier models, runs and sizes", async () => {
    browserApi({ "GET /me": makeMe(HEALTH_FNS, "state_oversight"), "GET /admin/data-health": { research_index: block() } });
    const { client } = renderWithClient(<ResearchIndexSection />);
    expect(await screen.findByRole("heading", { name: "Research Index" })).toBeInTheDocument();
    expect(await screen.findByText("Not Loaded")).toBeInTheDocument();
    expect(screen.getByText("It loads at the next question", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("embeddinggemma:300m@85462619ee72")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Coverage" });
    expect(bar.getAttribute("aria-valuetext")).toMatch(/^62% embedded · 1,69,613 waiting$/);
    expect(bar.querySelector("[data-tone='done']")).toBeNull();
    expect(screen.getByRole("link", { name: "3 chunks could not be embedded" })).toHaveAttribute("href", "/data/problems#failed");
    expect(screen.getByRole("table", { name: "Earlier Models" })).toBeInTheDocument();
    expect(screen.getByText(/446,291 embedded, 2,57,141 chunk sets cut|4,46,291 embedded, 2,57,141 chunk sets cut/)).toBeInTheDocument();
    expect(screen.getByText("Not Yet")).toBeInTheDocument();
    expect(screen.getByText("1.2 GB")).toBeInTheDocument();
    expect(screen.getByText("1.5 GB")).toBeInTheDocument();
    expect(client.getQueryData(["data-health"])).toBeTruthy();
  });

  it("the coverage bar turns success at 99%; None failed; no earlier models table when none", () => {
    renderWithClient(<ResearchIndexBody r={block({ coverage: 0.9999, vectors_live: 446291, waiting: 58, failures_open: 0, other_keys: {}, readiness: "ready" })} />);
    expect(screen.getByRole("progressbar", { name: "Coverage" }).querySelector("[data-tone='done']")).not.toBeNull();
    expect(screen.getByText("None failed.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Earlier Models" })).toBeNull();
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("Not Known Right Now and the muted line for timed-out counts, never 0", () => {
    renderWithClient(
      <ResearchIndexBody r={block({ timed_out: ["counts"], chunks: null, vectors_live: null, waiting: null, coverage: null, other_keys: null })} />,
    );
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getAllByText("Not Known Right Now").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("Some counts took too long to read and are left out; press Refresh to try again.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/\b0 waiting|0%/);
  });

  it("the switched-off line shows only the chunk counts", () => {
    renderWithClient(<ResearchIndexBody r={block({ enabled: false, readiness: "off" })} />);
    expect(screen.getByText("The meaning search is switched off; the Assistant uses word search. Chunks cut so far are shown below.")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getAllByText("Off").length).toBe(2);
  });

  it("a missing block says so with Try Again", async () => {
    browserApi({ "GET /me": makeMe(HEALTH_FNS, "state_oversight"), "GET /admin/data-health": { research_index: null } });
    renderWithClient(<ResearchIndexSection />);
    expect(await screen.findByText("The research index status could not be read.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try Again" })).toBeInTheDocument();
  });

  it("formatBytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(3482)).toBe("3.4 KB");
    expect(formatBytes(12 * 1024 * 1024)).toBe("12.0 MB");
    expect(formatBytes(2.7 * 1024 ** 3)).toBe("2.7 GB");
    expect(formatBytes(null)).toBe("—");
  });
});

