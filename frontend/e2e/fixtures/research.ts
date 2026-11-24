/**
 * The research index states of the browser check (design research-index-portal, decision 22): the answers a state's
 * `variant` gives in place of the default fixtures, typed against the generated schema. Nothing here acts or calls a
 * court; every answer is a `GET`.
 *
 * - `research-building` and `research-timed-out`: the Research Index section of Data Collection → Overview (enabled,
 *   held, 62% coverage, three failures, one earlier model key; then the counts timed out);
 * - `research-filters`: All Court Orders with the index ready and the act choices;
 * - `research-answer`: an answer with removed sentences, a same-words line, a "Text Has Changed" source, the words-only
 *   hint and the question's chips, the passage of S1 and the court-record view of S1;
 * - `research-withheld`: My Cases with a withheld answer and the building notice whose coverage could not be read;
 * - `research-unavailable`: My Cases with the meaning search unavailable (the warning notice, the filters shown).
 */
import type { components } from "@/lib/api/schema";

import { SAMPLE, STRESS, synthFor } from "./synth";

type S = components["schemas"];
type Thread = S["AssistantThreadOut"];
type Citation = S["AssistantCitationOut"];
type Message = S["AssistantMessageOut"];

export const RESEARCH_VARIANTS = [
  "research-building",
  "research-timed-out",
  "research-filters",
  "research-answer",
  "research-withheld",
  "research-unavailable",
] as const;
export type ResearchVariant = (typeof RESEARCH_VARIANTS)[number];

const LIVE_KEY = "embeddinggemma:300m@85462619ee72";
const REMOVED =
  "[Removed by ASLMS: 2 sentences whose quotes, dates, numbers, case numbers, names or outcomes were not found in the records they cite.]";
const NO_ANSWER_TEXT = "No answer supported by the records was found. Open Sources to see the records searched and check them yourself.";
const ANSWER_ID = SAMPLE.messageId;

function researchIndex(timedOut: boolean): S["ResearchIndexStatusOut"] {
  return {
    enabled: true,
    live_model_key: LIVE_KEY,
    readiness: "held",
    chunks: timedOut ? null : { order_body: 361451, case_sheet: 84898, total: 446349 },
    vectors_live: timedOut ? null : 276736,
    waiting: timedOut ? null : 169613,
    coverage: timedOut ? null : 0.62,
    other_keys: timedOut ? null : { "nomic-embed-text:v1.5@0a109f422b47": 120455 },
    failures_open: 3,
    last_run: {
      started_at: "2026-11-24T09:58:00Z",
      finished_at: "2026-11-24T15:21:00Z",
      status: "partial",
      counters: { embedded: 276736, cut: 257141, failed: 3 },
    },
    last_reconcile: { started_at: "2026-11-23T20:15:00Z", finished_at: "2026-11-23T20:19:00Z", status: "succeeded", counters: {} },
    table_sizes: { research_chunks: 1288490188, research_embeddings: 1610612736 },
    timed_out: timedOut ? ["counts"] : [],
  };
}

function status(research: S["AssistantResearchStateOut"]): S["AssistantStatusOut"] {
  return {
    ...(synthFor("/assistant/status")!.body as S["AssistantStatusOut"]),
    mode: "ollama",
    state: "ready",
    banner: null,
    internal_records: "switch",
    engine: { kind: "ollama", model: "qwen3.5:4b", readiness: "ready", reason: null },
    scopes: ["case", "my_cases", "research", "my_work"],
    work_questions: [],
    research,
  };
}

function baseThread(): Thread {
  return synthFor("/assistant/conversations/x")!.body as Thread;
}

function citation(base: Citation, extra: Partial<Citation>): Citation {
  return {
    ...base,
    document_id: "0192a3b4-0000-7000-8000-0000000000d1",
    order_id: SAMPLE.orderId,
    case: { id: SAMPLE.caseRefPath, case_no_text: STRESS.caseNo, cnr: "ASHC010012342025", visible: true },
    source_kind: "court_order",
    doc_type_label: "Order",
    doc_date: "2025-03-12",
    order_no: "7",
    page: 2,
    passage: "The respondents are directed to [[regularise]] the services of the petitioners within three months.",
    related: false,
    available: true,
    unavailable_reason: null,
    open: { kind: "court_order", href: `/assistant/court-orders/${SAMPLE.orderId}?message=${ANSWER_ID}` },
    label: "S1",
    cited: true,
    context: "The respondents are directed to regularise the services of the petitioners within three months.",
    note: null,
    internal: false,
    what: null,
    visibility: null,
    work: null,
    src: [120, 220],
    paragraphs: [3],
    match: "both",
    same_words_in: 0,
    quotes: [],
    text_changed: false,
    ...extra,
  };
}

function message(base: Message, extra: Partial<Message>): Message {
  return {
    ...base,
    hidden_reason: null,
    engine: { kind: "ollama", model: "qwen3.5:4b" },
    internal_used: false,
    suggest_internal: false,
    suggest_work: false,
    work: null,
    mode: "ollama",
    error: null,
    filters: null,
    ...extra,
  };
}

function answerThread(): Thread {
  const base = baseThread();
  const asked = base.messages.find((m) => m.role === "user") ?? base.messages[0]!;
  const said = base.messages.find((m) => m.role === "assistant") ?? base.messages[0]!;
  const cite = said.citations[0] ?? asked.citations[0]!;
  const q = message(asked, {
    id: `${asked.id.slice(0, -2)}r1`,
    role: "user",
    content: "Orders on regularisation of contractual teachers",
    citations: [],
    engine: null,
    checks: null,
    retrieval: null,
    outcome: null,
    mode: null,
    reply_to_id: null,
    filters: { forms: ["judgment"], against_state: true, act: "assam land revenue regulation 1886", from: "2024-01-01" },
  });
  const a = message(said, {
    id: ANSWER_ID,
    role: "assistant",
    outcome: "answered",
    reply_to_id: q.id,
    content: `${STRESS.sentence} [S1]. The same direction was given in an earlier order of the Division Bench [S2].\n${REMOVED}`,
    checks: {
      invalid_markers: 0,
      cut_short: false,
      sentences: 4,
      kept: 2,
      removed: { uncited: 1, quote: 0, date: 1, number: 0, case_no: 0, name: 1, outcome: 0 },
      withheld: null,
    },
    retrieval: { kind: "words_only", reason: "timeout", model_key: LIVE_KEY, embed_ms: 3000, lists: { words: 12 }, fused: 12, stale_dropped: 0 },
    citations: [
      citation(cite, { same_words_in: 3 }),
      citation(cite, {
        label: "S2",
        document_id: "0192a3b4-0000-7000-8000-0000000000d2",
        order_id: "0192a3b4-0000-7000-8000-0000000000o2",
        open: { kind: "court_order", href: `/assistant/court-orders/0192a3b4-0000-7000-8000-0000000000o2?message=${ANSWER_ID}` },
        doc_date: "2024-07-30",
        order_no: "3",
        text_changed: true,
      }),
    ],
  });
  return { ...base, messages: [q, a], has_more: false };
}

function withheldThread(): Thread {
  const base = baseThread();
  const asked = base.messages.find((m) => m.role === "user") ?? base.messages[0]!;
  const said = base.messages.find((m) => m.role === "assistant") ?? base.messages[0]!;
  const cite = said.citations[0] ?? asked.citations[0]!;
  const q = message(asked, {
    id: `${asked.id.slice(0, -2)}w1`,
    role: "user",
    content: "Did the court hold the transfer order illegal in my cases?",
    citations: [],
    engine: null,
    checks: null,
    retrieval: null,
    outcome: null,
    mode: null,
    reply_to_id: null,
  });
  const a = message(said, {
    id: `${said.id.slice(0, -2)}w2`,
    role: "assistant",
    outcome: "no_match",
    reply_to_id: q.id,
    content: NO_ANSWER_TEXT,
    checks: { invalid_markers: 0, cut_short: false, sentences: 3, kept: 0, removed: { uncited: 3 }, withheld: "majority" },
    retrieval: { kind: "hybrid", reason: null, model_key: LIVE_KEY, embed_ms: 140, lists: { words: 6, meaning: 20 }, fused: 20, stale_dropped: 0 },
    citations: [citation(cite, { cited: false })],
  });
  return { ...base, messages: [q, a], has_more: false };
}

function passage(): S["AssistantPassageOut"] {
  const head = "IN THE GAUHATI HIGH COURT\n(HIGH COURT OF ASSAM, NAGALAND, MIZORAM AND ARUNACHAL PRADESH)\n\n";
  const filler = Array.from({ length: 8 }, (_, i) => `${i + 1}. ${STRESS.sentence}`).join("\n");
  const cited =
    "9. In view of the above, the respondents are directed to regularise the services of the petitioners within three months from the date of receipt of a certified copy of this order, with all consequential benefits.";
  const tail = "\n10. The writ petition stands disposed of in the above terms.\n";
  const text = `${head}${filler}\n${cited}${tail}`;
  const start = text.indexOf(cited);
  const quote = text.indexOf("regularise the services of the petitioners");
  return {
    order_id: SAMPLE.orderId,
    document_id: "0192a3b4-0000-7000-8000-0000000000d1",
    page: 2,
    page_count: 4,
    page_text: text,
    highlights: [
      { start, end: start + cited.length, kind: "passage", exact: true },
      { start: quote, end: quote + "regularise the services of the petitioners".length, kind: "quote", exact: true },
    ],
    text_changed: false,
  };
}

function choices(url: URL): S["AssistantFilterChoicesOut"] {
  const kind = url.searchParams.get("kind") === "cites" ? "cites" : "act";
  if (kind === "cites") {
    return {
      kind,
      ready: true,
      items: [{ value: "(2006) 4 SCC 1", label: "(2006) 4 SCC 1", detail: "Secretary, State of Karnataka v. Umadevi (3)", orders: 1840 }],
    };
  }
  return {
    kind,
    ready: true,
    items: [
      { value: "assam land revenue regulation 1886", label: "Assam Land Revenue Regulation, 1886", detail: null, orders: 2210 },
      { value: "assam land revenue regulation", label: "Assam Land Revenue Regulation", detail: null, orders: 640 },
      {
        value: "assam state commission for protection of child rights act 2016",
        label: "Assam State Commission for Protection of Child Rights Act, 2016",
        detail: null,
        orders: 3,
      },
    ],
  };
}

/** The variant's answer for a `GET`, or undefined to fall through to the default fixtures. */
export function researchAnswer(variant: string, apiPath: string, url: URL): unknown {
  const v = variant as ResearchVariant;
  if (apiPath === "/admin/data-health" && (v === "research-building" || v === "research-timed-out")) {
    return { ...(synthFor("/admin/data-health")!.body as Record<string, unknown>), research_index: researchIndex(v === "research-timed-out") };
  }
  if (apiPath === "/assistant/status") {
    if (v === "research-filters" || v === "research-answer") return status({ state: "ready", coverage: 0.9998 });
    if (v === "research-withheld") return status({ state: "building", coverage: null });
    if (v === "research-unavailable") return status({ state: "unavailable", coverage: null });
  }
  if (apiPath === "/assistant/filter-choices" && v === "research-filters") return choices(url);
  if (/^\/assistant\/conversations\/[^/]+$/.test(apiPath)) {
    if (v === "research-answer") return answerThread();
    if (v === "research-withheld") return withheldThread();
  }
  if (/^\/assistant\/messages\/[^/]+\/sources\/[^/]+\/passage$/.test(apiPath) && v === "research-answer") return passage();
  return undefined;
}
