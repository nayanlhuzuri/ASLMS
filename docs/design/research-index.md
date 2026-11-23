# Design: Meaning search for research (the research index)

```
slug: research-index
status: awaiting-approval
author: architect
date: 2026-11-23
approved_by: (awaiting the owner)
```

## Context
Backlog row 251. Decisions log entry "Case research plan (owner, 12 Nov 2026)". It is the second of four research rows
(250 `order-sections`, done and live since 17 Nov 2026; 251 this row; 252 `similar-and-summaries`; 253
`precedent-notes`), built one at a time. In the build order of 13 Nov 2026 it comes after rows 258 to 260, which are
deployed.

**What the owner asked for (row 251, 12 Nov 2026).**
- A meaning search for research, built on two kinds of text:
  - the order bodies read by row 250, cut into chunks that follow the order's structure;
  - one case sheet per case, written from its NAPIX details.
- Embeddings from a local embedding model served by the same Ollama, reached only through
  `backend/aslms/integration/ollama/`. The model is chosen by a test on 200 orders. The candidates are bge-m3,
  nomic-embed-text, embeddinggemma and qwen3-embedding. It is pinned by name and version, and the pin is stored with
  every vector, so a model change re-embeds.
- pgvector inside PostgreSQL 16 (a pinned build), with tables `research_chunks` and `research_embeddings` and an HNSW
  index. `docs/DB_STANDARD.md` and `docs/schema/schema.md` are amended first, reversing the schema's "not carried over"
  line for pgvector and chunk tables.
- Hybrid retrieval: word search and meaning search merged by reciprocal rank fusion, with substantive orders and
  judgments above procedural ones. It serves the Assistant's All Court Orders, My Cases and related-orders searches.
  The case tab's own-case search is unchanged.
- A background backfill behind the court work, with new orders embedded within minutes of their text. Progress shows
  on Data Collection and System Health. `aslms research-index status|run|rebuild`.
- **Chunking by structure** (owner, 12 Nov 2026):
  - an interim order's body is one chunk;
  - a judgment's chunk is a run of whole paragraphs within one part;
  - a paragraph is split at a sentence end only when it is longer than the model's input limit;
  - each chunk carries a context line from the held data;
  - the search matches small, and the model is given the surrounding part;
  - results are grouped by order;
  - outcome, directions, acts and cited judgments serve as filters;
  - identical bodies are embedded once.
- **Traceability and answer checks** (owner, 12 Nov 2026: "I don't want you to cite wrong answers at all"):
  - every chunk keeps its section, page, offsets, PDF fingerprint, parser version and model version;
  - a chunk whose PDF changed is replaced, re-embedded and never cited;
  - every Assistant answer built on the index is checked on the server, sentence by sentence;
  - each citation opens the stored PDF at its page with the passage highlighted.
- **Documentation** (owner): chapter 6 and Annexure E gain the chunking, the case sheet, the embedding, the retrieval
  and the checks, with one worked question.

**Plan.** The plan holds the research index in SourceTrace (§3.2, §5.9, §7: "the research index itself is held in
SourceTrace"). Building it locally is a **deviation** from the plan. The owner approved it in direction on 12 Nov 2026
("local first, then SourceTrace"; the decisions log's case research plan extends the local-model allowance of
27 Oct 2026 to embeddings). It is flagged again here for the owner's confirmation (decision 1).

**What is in place.**
- **`order_sections`** (row 250, migration 0038): one current reading per court order. It holds:
  - `body_text` and `body_sha256`;
  - the paragraphs with `page`, `page_to`, `src` and `txt` offsets and `part`;
  - the parts;
  - the facts (outcome, directions, acts, judgments);
  - the `procedural` and `registrar` tags, `form`, `parser_version`, `pdf_sha256` and `text_sha256`;
  - `order_sections.src_text`, which refuses a span when the text's hash no longer matches.
- **`integration/ollama/client.py`**: `chat`, `load`, `loaded`, `models`, `version` and the cloud rules. Guards in
  `tests/unit/test_assistant_ollama.py` limit who imports it and where `/api/chat` appears.
- **`services/assistant_ollama.py`**: retrieval through `assistant_preview.search_passages` (page-level full-text
  search), sources numbered `S1..Sn`, `check_citations` (assistant-ollama decision 8) and `PROMPT_VERSION = 2`.
- **`services/assistant_sources.py`**: the court-order and court-filing corpora, `case_contexts` and `case_details`
  (court-public facts only).
- The live setup: `ASSISTANT_MODE=ollama` with `qwen3.5:4b` on the owner's machine, loaded with 5.2 GB of GPU memory.
  An embedding call to it answers "This server does not support embeddings", so an embedding model has to be pulled.
  Since the model test of 23 Nov 2026, Ollama 0.40.11 holds `qwen3.5:4b` and the chosen `embeddinggemma:300m`; the
  other three candidates were removed after the test.
- PostgreSQL `postgres:16.15` (Debian trixie), with extensions `plpgsql` and `btree_gist`. `vector` is not available.
  PGDG's `postgresql-16-pgvector` candidate is `0.8.7-1.pgdg13+2`. Its control file has no `trusted` line, so only a
  superuser can create it. `migrate` connects as the cluster superuser.

**What the dev data says** (read-only, 23 Nov 2026, inside `BEGIN READ ONLY`):
- **Current readings:** 313,387, with 247,062 distinct bodies (162,848 procedural, 84,490 substantive).

  | form | readings | distinct bodies | median body | p99 body | paragraphs |
  |---|---:|---:|---:|---:|---:|
  | interim | 289,014 | 226,401 | 372 chars | 3,728 chars | 855,772 |
  | final | 20,983 | 18,740 | 1,582 chars | 25,903 chars | 168,609 |
  | judgment | 3,390 | 2,510 | 18,597 chars | 238,237 chars | 161,129 |

- **Bodies:** 249 million characters in all (1,008 per distinct body). Seven bodies are empty.
- **Cases:** 84,898 live cases. 81,606 have a category and 49,683 a short order. A case has a median of 5 current
  parties (p99 57, max 1,855) and at most 4 acts.
- **New orders:** 200 to 1,700 a day in the last week.
- **Chunk counts.** The chunking of decision 9 was simulated on the stored paragraph spans: interim whole up to the
  cap, other forms as runs of whole paragraphs within one part grown to at least 1,000 characters, and a cap of 6,000
  characters. The result is 336,521 order chunks:

  | form | chunks | median | p99 |
  |---|---:|---:|---:|
  | interim | 229,783 | 392 chars | 3,385 chars |
  | final | 69,481 | 656 chars | 3,118 chars |
  | judgment | 37,257 | 1,273 chars | 4,912 chars |

  418 paragraphs and 623 interim bodies exceed 6,000 characters. With a minimum of 600 characters there would be
  361,631 chunks.

**Not covered** (stated so nobody widens it):
- similar cases, summaries and precedent notes (rows 252 and 253);
- court filings in the index: uploaded filings keep today's page word search;
- notes, file remarks, internal documents and drafts, which are never read;
- any change to the preview mode (model-free) or the sourcetrace mode;
- OCR;
- any NAPIX call: this row reads stored data only;
- the portal screens, which are round 2 (decision 4).

## Decisions

### A. Scope and boundary

1. **The index is local: a deviation the owner approved in direction.**
   - The plan puts the research index in SourceTrace. Building it inside ASLMS follows the owner's case research plan
     of 12 Nov 2026 ("local first, then SourceTrace"). The local-model allowance covers embeddings: local only
     (Ollama, never inside the backend; `no_local_model` stays fatal) and court information only.
   - When SourceTrace's API arrives (row 36), its design decides whether the chunks and case sheets go there too.
   - This amends `docs/design/assistant-ollama.md`, "Not covered" ("embeddings or vector search"). The scribe adds an
     "Amended by `research-index`" line there.
   - *Alternative:* waiting for SourceTrace (rejected: row 36 is blocked on its documentation).

2. **Court information only.**
   - Order chunks come from `order_sections.body_text` of current readings: court orders only, never uploads. The
     header (cause title with addresses, advocates, coram) is not indexed. The NAPIX data already holds those facts.
   - Case sheets come only from court-public case fields (decision 11).
   - The research modules read only these tables: `order_sections`, `orders`, `documents` (hash and nature columns),
     `document_text` (for the hash and the page text of a cited passage), `cases`, `case_parties`, `case_acts`,
     `case_hearings` and `courts`. A unit test scans their SQL and imports for any other table and refuses notes,
     custody, internal documents, drafts and the assistant's internal module. This follows the reader check of
     court-data-freshness.
   - Visibility follows `assistant` decision 3 (owner, 23 Oct 2026): every assistant user may search, cite and open
     the court orders of every case. A case sheet holds only what `assistant_sources.case_contexts` already gives
     every assistant user. It never holds the next hearing, a confirmed or manual date, the owner, custody, the stage
     or a `ref_no`.

3. **Where the meaning search is used.**
   - **Mode:** `ASSISTANT_MODE=ollama` only. Preview stays exactly as it is: its own rule is "no embedding, no model of
     any kind". Sourcetrace mode is unchanged.
   - **Scopes:** All Court Orders (`research`), My Cases (`my_cases`), and the related orders of other cases in This
     Case (`include_related`).
   - **Unchanged:** This Case's search of its own orders (the owner's words), the case tab's internal records, quick
     facts and My Work.
   - When `RESEARCH_INDEX_ENABLED` is false, or the index cannot be reached for a question, retrieval is today's word
     search (decision 21).

4. **Two rounds.** Round 1 is this row, the backend. Round 2 is a new row, `research-index-portal`, added on approval.
   This follows the approved split of state-insights.
   - **Round 1 (this row):**
     - the migration, the image and the chunker;
     - embedding through Ollama, the job and the CLI;
     - hybrid retrieval inside the Assistant, the sentence checks and the prompt version 3;
     - the API fields of the API section;
     - the System Health check, which the portal already draws from the server's list of checks;
     - the data-health block.
     - Every answer is checked from this round, and a removed sentence or a withheld answer shows as plain text in
       today's portal (decision 28).
   - **Round 2 (portal):**
     - the Research Index section on Data Collection;
     - the filters (decision 20) on All Court Orders and My Cases;
     - the passage view of a cited order with the exact passage highlighted;
     - the "Text Has Changed" note on an old citation;
     - the styling of removed-sentence notes;
     - uicheck at four widths.
   - *Alternative:* one row (rejected: about twice the size of row 250, with a second technology, pgvector, to
     review).

### B. The embedding model

5. **The model is `embeddinggemma:300m`, chosen by the owner's test (run 23 Nov 2026; results under "The model
   test").**
   - The four candidates as pulled into Ollama 0.40.11 (tags, digests and sizes from `/api/tags`):
     - `bge-m3:567m`: 1.16 GB (F16), 1,024 dimensions, input up to 8,192 tokens, no prefix;
     - `nomic-embed-text:latest` (v1.5): 0.27 GB (F16), 768 dimensions, input up to 2,048 tokens, needs
       `search_query:` and `search_document:` prefixes;
     - `embeddinggemma:latest`, the same digest as `embeddinggemma:300m`: 0.62 GB (BF16), 768 dimensions, input up to
       2,048 tokens, prompt prefixes;
     - `qwen3-embedding:0.6b`: 0.64 GB (Q8_0), 1,024 dimensions, input up to 32,768 tokens, an instruction on queries.

     Every tag existed as named. The 4b and 8b sizes of qwen3-embedding were left out: 2,560 and 4,096 dimensions, and
     too large beside the chat model on an 8 GB GPU.
   - **The test, as run** (read-only on the dev database, no NAPIX call, a script in the scratchpad, not application
     code; the details and figures are under "The model test"):
     1. **The orders.** 200 current readings, chosen at random with a fixed seed: 80 substantive interim, 60 final and
        60 judgments. They are cut by decision 9's chunker. Distractors of the same mix were drawn (3,800 orders,
        about 22,650 chunks) and then scaled down evenly to one tenth of the orders of each form (150 interim, 115
        final, 115 judgments; 2,276 chunks), because the measured CPU speeds put the full set at about 16 hours for
        the four models. Every chunk of the 200 test orders was kept.
     2. **Questions by the chat model.** For each order, one target chunk: the body of an interim order, or a
        substantive chunk of a final order or judgment chosen at random. `qwen3.5:4b` wrote one question an officer
        might ask that the passage answers, in other words. Any shared run of 4 or more words was regenerated, twice at
        most, then dropped (199 kept).
     3. **Questions by hand.** 20 questions on common subjects (regularisation, pension, transfer, recovery, land
        acquisition, contempt compliance, disciplinary action, provincialisation). The architect judged the pooled
        top 5 of every model by reading them.
     4. **Each candidate** embedded the test set on CPU (`options.num_gpu = 0`), so the live chat model was never
        evicted. Recorded: vector-only and fused recall@10 and MRR@10, hand precision@5, chunks per second on CPU,
        dimensions.
     5. **The rule.** The model with the best fused recall@10 wins. Within 2 points, the faster on CPU wins, because the
        pilot machine is not settled (assistant-ollama, open question 14). A model whose input limit is under
        2,048 tokens is kept only if its recall leads by more than 2 points, because it would need a smaller cap.
     6. **The judgment context** (decision 8) was tested on the 60 judgments in the same run.
   - **The result.** `embeddinggemma` had the best fused recall@10 (86.4, against 83.4 for qwen3-embedding, 77.4 for
     bge-m3 and 64.3 for nomic-embed-text). It leads by 3.0 points, more than the 2-point margin, so the speed tie-break
     does not apply; it is also the second fastest on CPU (4.07 chunks per second, nomic-embed-text 4.12). Its input
     limit is 2,048 tokens, not under 2,048, so the input-limit clause does not apply. Its hand precision@5 (46) is
     level with qwen3-embedding and 3 points below bge-m3 (49); the rule does not use it.
   - **Pinned as `embeddinggemma:300m`**, the explicit tag of the same digest
     (`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`), so the live key is
     `embeddinggemma:300m@85462619ee72`. `RESEARCH_EMBED_MODEL=embeddinggemma:300m`.
   - **What follows from the choice:** 768 dimensions (the index is `halfvec(768)`, Data), an input limit of 2,048
     tokens and so a cap of 5,120 characters (decision 9), and the profile in decision 6.
   - *Alternative:* choosing from published benchmarks (rejected: the owner asked for a test on our orders).

6. **Ollama only, through `integration/ollama/`, on the same server.**
   - `OllamaClient` gains `embed(model, inputs, *, options, keep_alive, timeout)` (`POST /api/embed`, `truncate:
     false`) and a synchronous twin `embed_sync`. The reply is parsed by `parse_embed` for `embeddings` (one list of
     floats per input), `model` and `prompt_eval_count`.
     - Field names follow Ollama's published API. Confirmed on 0.40.11 by the model test (23 Nov 2026): the request
       takes `model`, `input` (a list), `truncate`, `options` and `keep_alive`; the reply holds `model`,
       `embeddings` (one list of floats per input, in input order), `total_duration`, `load_duration` and
       `prompt_eval_count`. The developer checks them again with the chosen model (Verification 2).
     - The errors are the client's existing mapping. An input too long with `truncate: false` is
       `SourceTraceRejected`. On 0.40.11 it answers **400 or 413**, both with the body `{"error": "the input length
       exceeds the context length"}`: 400 when the input passes `num_ctx`, 413 when it passes `num_batch` (seen in
       the test). Both are treated as "too long" (decision 9's second split).
   - **Why `truncate: false`:** a text cut short in silence would be indexed under a hash of words the model never
     read. A refused input is split again (decision 9) or recorded as a failure (decision 34).
   - **The address** is `ASSISTANT_OLLAMA_URL`, the same server as the chat model (owner: "served by the same Ollama").
     There is no second address setting.
   - **The model** is `RESEARCH_EMBED_MODEL`. `model_name_ok` and the `no_cloud_model` preflight check cover it as they
     cover `ASSISTANT_OLLAMA_MODEL`. Readiness needs the model held locally (`/api/tags` size of at least 100 MB),
     as the chat model's does.
   - **Options:** `num_ctx` **and `num_batch`** both set to the profile's input limit. `RESEARCH_EMBED_ON_CPU=true`
     adds `num_gpu: 0` for a machine whose GPU cannot hold both models.
     - *Why `num_batch` too (found by the model test):* Ollama 0.40.11 embeds an input in one batch, so an input
       longer than `num_batch` (2,048 tokens by default) is refused with 413 even when `num_ctx` allows it. In the
       test bge-m3 with `num_ctx` 8,192 refused every input above about 2,030 tokens until `num_batch` was raised to
       8,192. The options are the same on every call, so the model is never reloaded for a different setting.
   - **Keep-alive:** `RESEARCH_EMBED_KEEP_ALIVE`, default `-1`.
   - **Guards extended:**
     - `/api/embed` appears only in `client.py`;
     - the importers allowed are `services/research_embed.py`, `services/research_search.py`, `cli/research.py` and
       `services/service_checks.py`, beside today's three;
     - no Python vector or model library is added (`numpy`, `pgvector` and `sentence-transformers` are refused by a
       lock test).
   - **Profiles.** A code table `EMBED_PROFILES` holds, per model family, the document prefix, the query prefix, the
     input limit in tokens and the dimensions. The document prefix is part of the embedded input and of its hash.
     - The chosen model's profile `embeddinggemma`, as used in the model test: document prefix `title: none | text: `,
       query prefix `task: search result | query: `, input limit 2,048 tokens, 768 dimensions. These are the model's
       published prompts; Ollama does not add them, so the client does.
     - Other families get a profile only when a model change needs one (decision 7); the test's profiles for the
       three others are recorded under "The model test".

7. **Pinned by name and digest.**
   - **The model key** is `<full name>@<first 12 hex digits of the digest>`, for example
     `embeddinggemma:300m@85462619ee72`. The digest comes from `/api/tags`, read once per run. Every vector stores `model`, `model_digest` and
     `model_key`.
   - **The live key** is read from the server. A question uses only vectors of the live key.
   - **A changed digest** (a re-pull) or a new `RESEARCH_EMBED_MODEL` makes a new live key:
     - the old vectors stop being used at once, because a query embedded by one model cannot be compared with
       vectors of another;
     - until the new key's vectors are written, the words list carries the search;
     - the job embeds under the new key, the status shows the coverage of each key, and `aslms research-index
       rebuild --embeddings` retires the old key's vectors (audited).
   - A model of a different dimension also needs a migration that adds its index (decision 15). The runbook says so.

8. **An AI-written context sentence per judgment chunk: tested, not adopted.**
   - The owner left it optional, "decided in the design after a test".
   - **The test (run 23 Nov 2026):** on the 60 test judgments, `qwen3.5:4b` wrote one sentence per chunk (what the
     passage is about in the judgment, given the judgment's first 8,000 characters), 1,013 sentences at about 0.75 s
     each on the GPU. The judgments' chunks were embedded again by `embeddinggemma` with the sentence as a second line,
     and the 59 judgment questions were scored with and without it.
   - **The rule:** adopt only if judgment recall@10 rises by 5 points or more.
   - **The result:** judgment recall@10 stayed at 91.5 with and without the sentence (vector-only and fused alike);
     MRR@10 moved from 0.676 to 0.685 (fused). Not adopted: no context sentence, no AI text in the index, no extra
     version.
   - **What it would have cost:** about 37,000 chat calls for the judgment chunks, about 7.8 hours of GPU at the
     measured speed, or several days on CPU.
   - *Limit stated:* only the test judgments' own chunks carried the sentence, and recall was already 91.5, so a
     small gain could hide in the remaining 8.5 points; the rule's 5 points were still reachable and were not reached.

### C. Chunks

9. **Chunk sets follow row 250's structure. Identical bodies are cut once.**
   - **The key.** A chunk set belongs to the key (`body_sha256`, `form`, `parser_version`, `chunker_version`).
     - Row 250's parts depend on the body and the form under one parser version, so every current reading with the
       same key has the same paragraphs, parts and chunks.
     - Every order holding a routine body ("List after four weeks.") shares one chunk set.
     - `CHUNKER_VERSION = 1`.
   - **Interim and off-template readings** (one `body` part): the whole body is one chunk, up to the cap.
   - **Final orders and judgments:** runs of whole paragraphs inside one part, in order.
     - A run closes when the next paragraph belongs to another part, or when the run has reached
       `CHUNK_MIN_CHARS = 1,000`, or when adding the next paragraph would pass the cap.
     - Short numbered paragraphs ("2. Heard.") join their neighbours, while the match stays small: about a paragraph,
       median 656 characters for final orders and 1,273 for judgments.
     - A run never crosses a part boundary.
   - **The cap** is the profile's input limit in tokens × 2.5 characters (a conservative ratio for digits and Indian
     names), at most 20,000 characters. For `embeddinggemma:300m` (2,048 tokens) that is **5,120 characters**.
     - The model test measured 4.1 to 4.5 characters per token on these orders (4.29 for embeddinggemma), so a
       5,120-character chunk is about 1,200 tokens and none was refused.
     - On the dev data a cap of 5,120 instead of the 6,000 of the simulation in Context adds about 700 split pieces,
       under 0.3% of the chunks (read-only count, 23 Nov 2026).
     - Only a paragraph, or an interim body, above the cap is split. It is split at the last sentence end
       (`order_parse_rules.SENTENCE_END`) before the cap, else at the last space. Each piece is marked `split`.
     - If Ollama still refuses an input as too long, it is split once more at the middle sentence end, then recorded
       as a failure.
   - **Empty bodies** (the 7 with `empty_body`) get no chunk.
   - **No overlap between chunks.** The owner's first wording had "about 1,000 tokens with overlap". His chunking rule
     of 12 Nov 2026 replaced it. Context comes from small-to-big reading (decision 19), not from repeated text.
   - Each chunk stores:
     - `part`, `para_first` and `para_last` (row 250's paragraph indices);
     - `txt_start` and `txt_end` (offsets in `body_text`);
     - `split`;
     - the exact text (`body_text[txt_start:txt_end]`, tested equal).

     Pages and `src` offsets differ between orders that share a body, so they are read from each order's own reading
     when a chunk is cited (decision 13).
   - *Alternatives:* fixed token windows (rejected by the owner); one chunk per paragraph without merging (rejected:
     361,631 or more chunks and many three-word chunks); one chunk per part (rejected: reasoning parts run to
     100,000 characters).

10. **The context line: a short one in the embedded text, the full one when the chunk is read. Small deviation.**
    - **The owner's list:** case number and type, date, judge, judgment or order, which part, the case's subject.
      Those values differ between the orders that share a body. Putting them in the embedded text would break
      "identical bodies embedded once" (5,000 orders of "List after four weeks." would need 5,000 vectors).
    - **The embedded context line** holds only what every order with the key shares: the form label ("Judgment",
      "Final Order", "Order") and, for final orders and judgments, the part label and paragraph labels, for example
      `Judgment · Reasoning · paragraphs 14 to 16`.
    - **The full context line** is built from held data every time a chunk is read and given to the model: order date,
      case number and case type, the court's category and sub-category, the judge (`orders.order_judge_name`, else
      the case's coram), the form, the part, the paragraphs and the pages, for example `Order dated 12.03.2024 ·
      WP(C)/7013/2024 · Service: Regularisation · Hon'ble Mr Justice A · Judgment · Reasoning · paragraphs 14 to 16 ·
      pages 7 to 8`.
    - **The subject** is carried in the meaning search by the case sheet (decision 11). The identifiers are matched by
      words, where an embedding is weak.
    - **Deviation** from the letter of the owner's list for the embedded text only, flagged for the owner.
    - *Alternative:* the full line embedded per order (rejected: about 66,000 extra vectors today and a re-embed
      whenever a shared body gains a case).

11. **One case sheet per case, from court-public fields.**
    - **Text, in this order:**
      - `Case details · <case type> · <year> · Gauhati High Court`;
      - category and sub-category as the court prints them;
      - acts and sections (`case_acts`, as listed);
      - the petitioners and respondents: current `case_parties` names in party order, else
        `petitioner_summary` / `respondent_summary`;
      - status and disposal nature;
      - `cases.short_order`;
      - the distinct short-order texts of the last 5 hearings (`case_hearings.short_order_text`).
    - Advocates are left out: their names do not carry meaning and are matching data.
    - **Caps:** parties at most 40 per side, then "and N more"; the whole sheet at most 4,000 characters (most are a
      few hundred).
    - **Kept current:** a new sheet when its text hash changes. The old one is retired (`sheet_changed`).
    - No CNR, `ref_no`, next hearing, owner or internal value.
    - **Use:** a sheet that matches brings its case's Case Details source and that case's best order chunk
      (decision 18).

12. **Vectors are keyed by what was embedded.**
    - `research_embeddings` is unique on (`input_sha256`, `model_key`) among rows not retired. `input_sha256` is the
      SHA-256 of the exact text sent: the profile's document prefix, the embedded context line, a newline and the
      chunk's text.
    - A chunk finds its vector by `research_chunks.embed_sha256 = research_embeddings.input_sha256`. So:
      - a new parser version that leaves a body's chunks word-for-word the same needs no model call;
      - the same paragraph in two bodies is embedded once.
    - `first_chunk_id` (FK, RESTRICT) names the chunk the vector was first made for, which keeps the chain by key.
    - Identical input gives the same vector from a pinned model, so sharing one is exact.

13. **The traceability chain, and nothing cited from a changed text.**
    - **The chain by keys:** vector → chunk (`embed_sha256`) → chunk set key → current reading (`order_sections`,
      `body_sha256` + `form` + `parser_version`) → order (`order_id`) → stored PDF (`document_id`, `pdf_sha256`) →
      the verbatim NAPIX answer (`orders.raw` and the dossier in `napix_responses`) → case (CNR).
    - **A changed PDF or text** makes a new reading (row 250 decisions 4 and 18):
      - same body: the same chunk set serves the new reading, and pages and offsets come from the new reading;
      - changed body: a new chunk set is cut and embedded. The old set is retired once no current reading holds its
        key (`reading_gone`), and its vectors are retired with it.
    - **A hit is cited only through a current reading** whose `text_sha256` equals the SHA-256 of today's
      `document_text.full_text` (`order_sections.text_matches`). Otherwise that order is dropped from the answer and
      counted (`stale_dropped`).
    - **Each court-order citation stores** `chunk_id`, `reading_id`, `paragraphs`, `src` (the passage's offsets in the
      order's stored text), `page`, `pdf_sha256`, `text_sha256`, `parser_version`, `chunker_version`, `model_key`
      and `match`.
    - **When a stored answer is read again**, a citation whose order now has another text hash is flagged
      `text_changed`. The answer stays readable: the source shown is the court's own order.

### D. Storage: pgvector

14. **pgvector 0.8.7 in our own PostgreSQL image, the same everywhere.**
    - **The image:** `infra/postgres/Dockerfile`: `FROM postgres:16.15` plus `apt-get install
      postgresql-16-pgvector=0.8.7-1.pgdg13+2` from the PGDG repository already in the image. The build uses no
      cache, and nothing else is installed.
    - **Compose:** `postgres` builds it as `aslms/postgres:16.15-pgvector0.8.7`. The data volume and the server major
      version are unchanged. The server binary is the same 16.15 package, so the cluster starts on the same volume.
    - **Why our own image:** an upstream `pgvector/pgvector` image would also change the server build.
    - **CI** keeps the `postgres:16.15` service container. One step installs the same pinned package as root
      (`docker exec -u root`) before the tests. A guard test reads both pins and refuses a difference.
    - **The extension:** `vector` is not marked trusted. `CREATE EXTENSION IF NOT EXISTS vector` runs in migration
      0042, applied by `migrate` as the cluster superuser, as `btree_gist` was by 0028. The test database gets it
      the same way.
    - **Backups:** a dump now needs the image to restore. `aslms ops backup` and the restore check run against the same
      server, so nothing changes there. The runbook says a restore elsewhere needs this image.
    - **Pin withdrawn:** if PGDG withdraws the pinned build (as Alpine withdrew a PgBouncer client on 13 Nov 2026), CI
      fails loudly and the pin is moved in one commit.
    - *Alternatives:* a vector service outside PostgreSQL (rejected: the owner chose pgvector, and a second database
      to back up); vectors in a `real[]` column with distances in Python (rejected: no index, and the scan would cost
      seconds).

15. **halfvec, an HNSW index per dimension, exact search for small sets.**
    - **The column.** `embedding halfvec NOT NULL` holds half-precision values (2 bytes each), half the size of
      `vector`. The column carries no typmod. `dims smallint` and CHECK `vector_dims(embedding) = dims` keep each row
      honest.
    - **The index.** One partial expression index per dimension, created by the migration for the chosen model:
      `USING hnsw ((embedding::halfvec(768)) halfvec_cosine_ops) WITH (m = 16, ef_construction = 64) WHERE dims =
      768 AND retired_at IS NULL` (768 is the dimension of `embeddinggemma:300m`, decision 5).
      - Cosine distance needs no unit length.
      - It is built empty and kept by every insert, so no large `maintenance_work_mem` is needed.
      - A model of another dimension needs a migration adding its index (decision 7).
    - **Large sets** (All Court Orders, related orders) use the index:
      - `SET LOCAL hnsw.ef_search = RESEARCH_EF_SEARCH` (100);
      - `SET LOCAL hnsw.iterative_scan = relaxed_order` (pgvector 0.8), so the filters on the live key, current
        chunks and the asker's filters still yield enough rows.
    - **Small sets** use an exact scan with no index, which is exact and fast below `RESEARCH_EXACT_MAX` (20,000)
      vectors: the chunks of My Cases (at most 1,000 cases), and a filtered set (decision 20) whose chunk count is at
      or under the limit.
    - **PgBouncer:** every setting is `SET LOCAL` inside the question's read-only transaction, which the PgBouncer
      source scan allows.
    - **Binding:** a vector is sent as a text literal, `CAST(:v AS halfvec)`, and never read back: only distances are
      selected. The model column is a small `UserDefinedType` `HalfVec` in `db/base.py` that binds a list of floats as
      that literal. So there is no `pgvector` Python package and no `numpy`.

16. **Size and time (estimates; the test measures the speed).**
    - **Rows:** about 336,500 order chunks plus 84,900 case sheets, so about 421,000 chunks. Slightly fewer vectors,
      because identical texts share one.
    - **Size:**
      - `research_chunks` with text, tsvector and GIN: about 0.9 GB;
      - `research_embeddings` at halfvec(768): about 0.7 GB of heap;
      - the HNSW index: about 0.8 to 0.9 GB.

      In all about 2.4 to 2.5 GB, inside the owner's 2 to 4 GB. The two new `order_sections` GIN indexes
      (decision 20) are a few tens of MB.
    - **Backfill time:** at the test's CPU rate for `embeddinggemma:300m` (4.07 chunks per second, with the chat model
      loaded on the GPU and answering meanwhile), 421,000 chunks take about 29 hours on CPU. The GPU figure is measured
      in Verification 5. The owner's expectation was 2 to 3 hours on a GPU and about a day on CPU.
    - **New work:** about 2,000 chunks on a busy day.

### E. Retrieval

17. **Hybrid: two to four ranked lists merged by reciprocal rank fusion.**
    - Each list is computed in the question's read-only transaction, within the existing search budget
      (`ASSISTANT_PREVIEW_SQL_MS` per statement, the whole within `ASSISTANT_TIMEOUT_SECONDS` less the model's share).
      Each list takes at most `RESEARCH_CANDIDATES` (100) items.
    - **(a) Words:** `research_chunks.search_vector @@ websearch_to_tsquery('english', question)` over current chunks
      of the scope, ranked by `ts_rank_cd`. Order chunks and case sheets both take part.
    - **(b) Meaning:** the question's vector against the live key's vectors of current chunks of the scope, nearest
      first (decision 15).
    - **(c) Court filings** (My Cases and This Case only, as today): `search_passages` over the allow-list, unchanged.
    - **(d) Orders not yet in the index:** court orders of the scope that have no current reading or whose key has no
      current chunk set (new orders in their first minutes, or text not yet read), searched by today's page word
      search. So nothing new is missing.
    - **The fusion:** score = Σ 1 / (60 + rank) over the lists an item appears in (k = 60, the usual constant).
      - A court-order item is (chunk, order).
      - A chunk set held by several orders in scope is expanded to those orders first (decision 18).
      - `match` records `words`, `meaning` or `both`.
    - **What the model test showed about the words list** (stated plainly; no decision changed):
      - `websearch_to_tsquery` joins every word of the question with AND, so a question in plain sentences rarely
        matches a chunk: 11 of the 219 test questions matched any chunk at all, and the words list alone found the
        target in the top 10 for 1 of the 199 generated questions.
      - Fused recall@10 was therefore within half a point of meaning-only recall for every model. For natural
        questions the meaning list carries the search; the words list is there for case numbers, citations and
        section numbers, which Verification 6 checks.
      - A looser words list (every word joined with OR) was tried in the same run: it lowered fused recall@10 by 18
        to 27 points (for embeddinggemma 63.3 instead of 86.4), because RRF gives its many weak matches the same
        weight as the meaning list. It is not used.
    - *Alternatives:* vector only (rejected: case numbers, citations and section numbers are found by words); a
      weighted sum of raw scores (rejected: ts_rank and cosine distance are not on one scale, which is why RRF is
      used); an OR words list (rejected by the model test, above).

18. **Ranking weights and grouping by order.**
    - **Weights** after fusion, by the order's own reading: procedural × 0.5, judgment or final × 1.2, other
      substantive × 1.0. Procedural orders still count in every case's history and are still found, but lower. This
      ranks substantive orders and judgments above procedural ones.
    - **Shared bodies.** A chunk held by several orders in scope gives one item per order before fusion. Then only the
      newest order in scope is kept, with `same_words_in` = the number of the others. The focus cases' orders come
      first in My Cases.
    - **Grouping by order.** At most 2 passages per order. Adjacent chunks of one order become one passage. Sources
      are filled in fused order until `ASSISTANT_OLLAMA_SOURCES` (6), so one judgment cannot take every slot.
    - **Case sheet hits** add their case's Case Details (Court Record) source (`case_details`, compact, as today) and
      that case's best-ranked order chunk, if any. A sheet counts as one source.

19. **Small-to-big: match small, read the surrounding part.**
    - **For each passage the model gets:**
      - the full context line (decision 10);
      - the matched paragraphs;
      - neighbouring paragraphs of the same part, taken one after and one before in turn, until
        `ASSISTANT_OLLAMA_SOURCE_CHARS` (4,000).
    - An interim body goes whole, up to that limit.
    - **The text** is taken from the current reading's `body_text`, the cleaned text the chunk was cut from. It is
      stored as the citation's `context`, as today.
    - **The prompt's source header** names the kind, as today: "S3 (Court Record): <full context line>".
    - **The citation's `page`** is the first page of the matched paragraphs in that order. **Its `src`** spans from the
      first matched paragraph's `src` start to the last one's end.

20. **Filters, on the server, for All Court Orders and My Cases.**
    - **`POST /assistant/ask` gains `filters`** (optional, refused for `case` and `my_work` with 400
      `filters_not_allowed`):
      - `forms` (`judgment`, `final`, `interim`);
      - `substantive_only` (bool);
      - `outcomes` (row 250's `order_outcome` values);
      - `against_state` (bool);
      - `cites` (a citation, at most 80 characters, compared after row 250's citation normalisation);
      - `act` (an `act_key` from row 250's act table);
      - `from` and `to` (order dates).
    - The filters are kept in the question's `scope_info.filters` and in `assistant.asked`. They are court-public
      values the asker typed.
    - **`against_state` (by rule; flagged for the owner).** Read from the order's own outcome and the parties:
      - `allowed` or `partly_allowed` when a current respondent names the State (`insights_rules.STATE_PARTY_RE`);
      - `dismissed` when a current petitioner names it.

      "Disposed of", "withdrawn" and "closed" count neither way. The label says "Outcome Against the State (Read by
      Rule)". It serves the owner's example "only judgments the State lost".
    - **Applying them:**
      - forms, substantive-only, outcomes and dates join on the reading and the order;
      - `cites` and `act` use two new GIN indexes on `order_sections` (Data);
      - `against_state` is applied after the candidate step, on at most the fused candidates.
    - **Small filtered sets.** When the filtered orders' chunks number at most `RESEARCH_EXACT_MAX`, the meaning list is
      an exact scan of those chunks. So "every order citing (2006) 4 SCC 1" ranks all of them, and none is lost to
      the index.
    - *Alternative:* filters as words in the question (rejected: the model and the word search would read them as
      text).

21. **The question's vector: made in the api, in a few seconds, or words only.**
    - **When:** after the readiness checks and before transaction A, the api embeds the question (with the profile's
      query prefix) through `embed` within `RESEARCH_QUERY_EMBED_SECONDS` (5).
    - **Failure** (unreachable, not loaded, timeout, wrong dimension): the answer is built from the word lists only.
      `model_info.retrieval.kind` is `words_only`, with the reason. The question is never refused for this.
    - **Readiness of the embedding model** is cached for 5 s per process. A held model that is not loaded starts one
      background load, at most every 150 s, as for the chat model, so the next question has it.
    - **The budget:** the 5 s come out of the search's share. The model's share (`min(30 s, total − 5)`) is unchanged.

22. **The person first, the court work untouched.**
    - The embedding job and the CLI never touch `fetch_queue` or NAPIX.
    - Ollama runs one request per model at a time (`OLLAMA_NUM_PARALLEL=1`), so a question's embedding could wait
      behind a backfill batch. To prevent it:
      - while a question holds an assistant slot, the api sets a Redis key `aslms:assistant:asking` (30 s expiry,
        renewed, deleted at release);
      - the job and the CLI check it before each batch and pause, in 2 s steps, up to 120 s per batch;
      - `RESEARCH_EMBED_BATCH` is 16 on a GPU, and the profile halves it on CPU, so one batch is short.
    - The chat model is never evicted in the default setup (both should fit on the owner's 8 GB GPU: 5.2 GB plus
      `embeddinggemma:300m`'s 0.62 GB of weights and its working memory; the test ran the embedding model on CPU only,
      so Verification 5 measures the GPU memory and the rate). Otherwise `RESEARCH_EMBED_ON_CPU=true` keeps the
      embedding model off the GPU.

### F. Answer checks

23. **Every local-model answer is checked, sentence by sentence, after `check_citations`.**
    - **Applies to** every ollama answer in the scopes `case`, `my_cases` and `research`, whether or not the index was
      used. That includes the case tab and its internal records, because one rule is safer than two.
    - **Does not apply to** My Work answers and quick facts, which ASLMS writes itself from fixed templates.
    - **Where:** a pure module, `services/answer_checks.py`, with its rule tables in
      `services/answer_check_rules.py`. No database and no network. `CHECKS_VERSION = 1` is stored in `model_info`.
    - **Input:** the answer after `check_citations`, and, for each source number, the exact text given to the model
      (header plus text).
    - **Always on.** There is no setting to switch it off. The owner's rule is no wrong citations.

24. **Sentences.**
    - The answer is split at `.`, `?`, `!` or a line break, when followed by a space or line break and an upper-case
      letter, a digit, a quote or the end.
    - **It is not split after** abbreviations (`No.`, `Nos.`, `Sri.`, `Smt.`, `Dr.`, `Mr.`, `Mrs.`, `Ms.`, `vs.`,
      `v.`, `u/s.`, `i.e.`, `e.g.`, `viz.`, `Rs.`, `Hon'ble`, `Art.`, `Sec.`, `Cl.`, `para.`, `paras.`, `pp.`,
      `p.`), single-letter initials (`A. K. Das`), inside case numbers (`W.P.(C)`, `Crl.A.`) and inside brackets.
    - The `[Sn]` markers at a sentence's end belong to it.
    - `answer_check_rules.ABBREVIATIONS` is the list.

25. **Quotes must match the source, character for character.**
    - **What is checked:** every run inside double quotes (`"…"` or `“…”`) of 3 words or more must appear in the text
      of a source the sentence cites.
    - **The only normalisation:** whitespace runs read as one space; curly quotes and apostrophes read as straight
      ones; en and em dashes read as hyphens. Case, punctuation, digits and spelling must match.
    - **What a match records:** the quote's position in that source. For a court order this maps to `src` offsets in
      the stored text (decision 29).

26. **A citation on every sentence that states a fact.**
    - A sentence with no valid marker is removed when it has a checkable token (decision 27) or a quote, or is longer
      than 12 words.
    - A short sentence with nothing checkable is kept ("Two orders deal with this.").
    - The prompt already tells the model to cite every factual sentence (rule 1).

27. **Dates, numbers, case numbers, names and outcomes must be in the text the sentence cites** (the union of its
    cited sources, header included).
    - **Dates:** every date in the sentence, in the formats `order_parse_rules.DATE` reads plus "12 March 2024",
      "March 12, 2024" and "12th March, 2024", must equal a date read the same way from the source.
    - **Numbers** of two or more digits, and any number with a unit (Rs., %, days, weeks, months, years), outside
      dates and case numbers:
      - must appear in the source as digits, or as English words for 1 to 100 ("four weeks" backs "4 weeks");
      - amounts compare without commas ("Rs. 1,50,000" backs "Rs 150000").
    - **Case numbers and citations:**
      - case numbers by the printed-case-number pattern, compacted as `ix_cases_case_no_compact` compacts them (upper
        case, no spaces, `No.` and `of` read as `/`);
      - CNRs as 16 characters;
      - law-report citations by row 250's reporter patterns.

      Each must appear compacted in the source.
    - **Names:** a run of two or more capitalised words, not all in `answer_check_rules.NAME_STOP` (High Court, State,
      Assam, Government, Petitioner, Respondent, Hon'ble, Justice, Court, Section, Article, Act, Rule, month names,
      and so on). Every non-stop word of the run must appear in the source as a whole word, ignoring case. The model
      may reorder a name but not invent one.
    - **Outcomes:** each outcome word (allowed, partly allowed, dismissed, disposed of, withdrawn, closed, quashed,
      set aside, stayed, granted, rejected, upheld, remanded) must appear in the cited text in some form, or equal
      that order's rule-read outcome.
    - **Not checked:** negation. "Was not dismissed" passes if "dismissed" is in the text (decision 29).

28. **What happens to a failing sentence, and when the whole answer is withheld.**
    - **A failing sentence is removed.** At the end of the answer, ASLMS adds one line: "[Removed by ASLMS: n sentences
      whose quotes, dates, numbers, case numbers, names or outcomes were not found in the records they cite.]" It
      appears as text in today's portal. Round 2 styles it.
    - **The answer is withheld** when:
      - the first sentence is removed (the main point; the prompt's new rule 9 puts the direct answer first);
      - or more than half of the sentences are removed;
      - or no cited sentence remains.

      The text is then today's `NO_ANSWER_TEXT` ("No answer supported by the records was found. Open Sources to see
      the records searched and check them yourself."), with outcome `no_match`.
    - The model's own reply stays, unseen, in `response`, as today.
    - **Prompt version 3** adds:
      - rule 9: "Put the direct answer in the first sentence.";
      - rule 10: "When you quote, copy the words exactly and put them in double quotes."

      Rules 1 to 8 are unchanged.
    - *Alternative:* flagging failing sentences instead of removing them (rejected: the owner asked that wrong answers
      are never shown).

29. **What is stored, re-checked and shown.**
    - **`model_info.checks`:** `{version, sentences, kept, removed: {uncited, quote, date, number, case_no, name,
      outcome}, withheld: null | "first_sentence" | "majority" | "none_cited"}`. Counts only.
    - **`model_info.retrieval`:** `{kind: "hybrid" | "words_only" | "words", reason?, model_key?, embed_ms?,
      lists: {words, meaning, filings, unindexed}, fused, stale_dropped}`. Counts only.
    - **Court-order citations** carry the decision 13 fields. A matched quote is added as `quotes: [{src: [s, e], page,
      exact}]`:
      - the quote is searched in the stored text inside its paragraph's `src` span, by its words joined by any
        whitespace, giving `exact: true`;
      - failing that, the whole paragraph is marked, `exact: false`.
    - **The passage endpoint** (API) gives round 2 the page's stored text with these offsets made page-relative, so
      the portal can show the exact passage highlighted beside "Open PDF at Page n". Highlighting inside the PDF
      viewer itself is not attempted: the portal opens PDFs in the browser's viewer at `#page=n` (row 250). This is
      stated as a limit.
    - **The limit stated to users** (owner): rules cannot catch a wrong reading of correctly quoted text. Answers stay
      labelled as AI answers, and every source stays shown beside the answer.

### G. Jobs, operations and documents

30. **The work: a 5-minute job for new material, a backfill outside the app services, a daily reconcile.**
    - **Job `research-index`** (scheduler, `crontab(minute="4-59/5")`, after `order-sections` at minute 3). Its
      budget is `RESEARCH_JOB_SECONDS` (60) of wall time, because the scheduler runs one task at a time. In order:
      1. cut chunk sets for current readings created since the last watermark whose key has none;
      2. retire chunk sets whose key lost its last current reading since the watermark;
      3. new case sheets for cases changed since the watermark;
      4. embed waiting chunks, newest first.

      The watermark is kept in the run's counters (the insights pattern), minus 60 s of slack.
    - **The daily reconcile at 01:45 IST** (after row 250's 01:30 full check) compares every current key with the
      current readings and every case's sheet hash, and fixes what the watermark missed.
    - **The backfill:** `docker compose run -d --rm api aslms research-index run --backfill`, outside the app services
      (as `aslms orders parse --backfill`).
      - It commits every batch, can be stopped and resumed, and pauses `--pause-ms` (200) between batches and for the
        asking flag.
      - Order: judgments, then final orders, then substantive interim, then case sheets, then procedural bodies, so
        research is useful early.
    - The scheduler service gains `extra_hosts: ["host.docker.internal:host-gateway"]` to reach the host's Ollama, as
      `api` has.

31. **Settings** (environment, documented in `.env.example`; no secret):
    - `RESEARCH_INDEX_ENABLED` (default `false`): the master switch for the job, the CLI's embedding and the meaning
      list. With it false, chunks can still be cut by `aslms research-index run --chunks-only`, and nothing calls
      Ollama. Preflight warns when it is true and `ASSISTANT_MODE` is not `ollama`.
    - `RESEARCH_EMBED_MODEL` (`embeddinggemma:300m`, the model test's winner, decision 5).
    - `RESEARCH_EMBED_KEEP_ALIVE` (`-1`), `RESEARCH_EMBED_ON_CPU` (`false`), `RESEARCH_EMBED_BATCH` (16).
    - `RESEARCH_JOB_SECONDS` (60), `RESEARCH_QUERY_EMBED_SECONDS` (5), `RESEARCH_CANDIDATES` (100),
      `RESEARCH_EXACT_MAX` (20,000), `RESEARCH_EF_SEARCH` (100).
    - Constants in code, each with a test: `CHUNK_MIN_CHARS`, the RRF k, the weights, 2 passages per order.

32. **Status everywhere.**
    - **The data-health block `research_index`** (in `GET /admin/data-health`):
      - `enabled`, `live_model_key`, `readiness`;
      - chunks current by kind;
      - vectors of the live key, `waiting`, `coverage`;
      - other keys with counts;
      - open failures, the last run (`job_runs`) and the table sizes.

      It is read in isolated parts with a timeout, as row 264 does for `order_sections`, so a slow part reports
      `timed_out`.
    - **System Health:** a new check `research_model` ("Research Index Model"), only when enabled. It reads
      `/api/version`, `/api/tags` and `/api/ps` (never embeds, never loads) and reports ok, warn or down with the
      facts Model, Loaded, On GPU and Coverage, as `assistant_model` does.
    - **`GET /assistant/status`** gains `research: {state: "off" | "building" | "ready" | "unavailable", coverage}`:
      - building: under 99% of current chunks embedded under the live key;
      - unavailable: the model is not ready.
    - **`aslms research-index status`** prints the same.

33. **Audit and logging.**
    - Indexing is system work on derived data: no event, alert or audit, as row 250.
    - `assistant.asked` adds `filters`. `assistant.answered` adds `retrieval` and `checks` (counts as in decision 29).
      Never text.
    - `aslms research-index rebuild` writes `research_index.rebuilt` (entity `research_index`, no id; `after`: what was
      retired and the counts), with the CLI's actor rules. A model's vectors retired by the rebuild are part of that
      row.
    - **Log lines:** one INFO line per batch (count, characters, milliseconds, model key) and per question (list sizes,
      fused, kind). Never chunk text and never the question.

34. **Failures are recorded, not lost.**
    - A chunk whose embedding is refused even after the split, or whose vector has the wrong dimension, goes into
      `source_failures` (kind `research_embed`, with the chunk id and the error class). It is retried in the daily
      reconcile, and closed when it succeeds or its chunk is retired.
    - An unreachable model is not a failure: the job stops and counts `model_unready`.
    - The status shows the open count.

35. **Documentation** (owner; the scribe writes it from the developer's and the integrator's output).
    - **Software Documentation (`docs/software-documentation/build.js`):**
      - section 6.5 gains "The meaning search": chunks by structure, the case sheet, how the embedding model turns a
        chunk into a vector, the two lists and their merge, small-to-big reading, which case details and orders the
        model gets and in what order, and the sentence checks;
      - Annexure E gains:
        - the masked fixture order (`final_directions.txt`) and the masked judgment (`judgment_parts.txt`) cut into
          chunks, each with its context line, paragraphs, page and offsets;
        - the case sheet of a masked case;
        - one worked question with its two lists, the fused order, the sources given and the checked, cited answer,
          including one removed sentence. The worked question comes from Verification 7 on the masked fixtures, never
          from an unmasked order.
      - section 13.2 gains the variation (decision 1);
      - Annexure A gains the job;
      - the version history gets a line.
    - **`docs/ASLMS_Process_Workflows.md`:** the owner's plain-words explanation.
    - **Runbook `docs/operations.md`, section 28:**
      - the image, pulling the embedding model;
      - the backfill command, stop and resume;
      - a model change (pull, the new key, the job, `rebuild --embeddings`, and a migration when the dimension
        differs);
      - `RESEARCH_EMBED_ON_CPU`;
      - a restore elsewhere needing the image.
    - **The decisions log** gets an entry. The scribe amends `docs/design/assistant-ollama.md` "Not covered".

## Data

**Migration 0042 `research_index`.** A new migration; 0001 to 0041 are applied and untouched. It does the following:

1. Creates the extension: `CREATE EXTENSION IF NOT EXISTS vector`. Applied by `migrate` as the cluster superuser;
   `vector` is not trusted (decision 14).
2. Creates the enum types `research_chunk_kind` (`order_body`, `case_sheet`) and `research_retire_reason`
   (`reading_gone`, `sheet_changed`, `chunker_version`, `case_merged`, `model_changed`, `chunk_retired`, `rebuilt`).
3. Creates the tables `research_chunks` and `research_embeddings` (below), with their indexes, CHECKs, triggers, grants
   and comments.
4. Adds two GIN indexes on `order_sections`:
   - `ix_order_sections_facts_judgments`: `USING gin ((facts -> 'judgments') jsonb_path_ops) WHERE replaced_at IS
     NULL`;
   - `ix_order_sections_facts_acts`: `USING gin ((facts -> 'acts') jsonb_path_ops) WHERE replaced_at IS NULL`.

   Indexes do not touch the row trigger.
5. Downgrade: drops the two GIN indexes, both tables and their functions, the two types and the extension. The
   tables are derived and re-buildable, so nothing is kept. The runbook warns that a re-upgrade means a new backfill.

`job_runs.job` gains `research_index` and `research_index_reconcile`. `source_failures.kind` gains `research_embed`
(free text).

**`docs/DB_STANDARD.md` amendments (v1.4, written before the migration):**
- §0, the derived row: add `research_chunks`, `research_embeddings`.
- New **§13 Vector data (pgvector)**:
  - Vectors are derived data only. They are made from court information only (court orders as read by
    `order_sections`, and court-public case fields), never from notes, file remarks, internal documents or drafts.
  - They are made by the local Ollama model through `integration/ollama/` and stored by PostgreSQL's `vector`
    extension (pgvector, pinned in `infra/postgres/Dockerfile` and in CI, the same build).
  - The column is `halfvec` without typmod, with a `dims` column and CHECK `vector_dims(embedding) = dims`. One HNSW
    partial expression index exists per dimension in use (`halfvec_cosine_ops`, `m = 16`, `ef_construction = 64`).
  - Every vector records the model's name, digest and key, and the SHA-256 of the exact input. A changed model is a new
    key, never an overwrite. Vectors are never deleted; they are retired.
  - Vectors are bound as text literals. The backend holds no vector or model library.
  - Search settings are `SET LOCAL` only (PgBouncer).
  - A table keyed by a content hash may join another by that hash without a foreign key, when it also carries a
    RESTRICT foreign key to the row it was first made for (`research_embeddings.first_chunk_id`).
- The version history line for v1.4.

**`docs/schema/schema.md` changes:**
- **Conventions:**
  - "Extensions": add `vector` (pgvector 0.8.7, not trusted, created by migration 0042 through `migrate` as the cluster
    superuser; the server image is `infra/postgres/Dockerfile`).
  - "Derived tables": add the two tables.
- **"Not carried over":** the sentence about pgvector and the prototype's `document_chunks` and `chunk_embeddings` gains:
  "pgvector and two chunk tables return by the owner's case research plan of 12 Nov 2026 (design `research-index`,
  migration 0042), for court information only. They are new tables, not the prototype's."
- **Group 6, two new rows:**

| `research_chunks` (derived) | id (uuid v7 PK), kind (`research_chunk_kind` NOT NULL), body_sha256 (varchar 64 NULL; `order_body`: the readings' `body_sha256`), form (`order_kind` NULL; `order_body`), parser_version (smallint NULL; `order_body`), chunker_version (smallint NOT NULL), seq (smallint NOT NULL; 0-based within the set; 0 for a sheet), first_reading_id (→ order_sections RESTRICT, NULL; `order_body`: the reading the set was cut from), case_id (→ cases RESTRICT, NULL; `case_sheet`), part (varchar 30 NULL; row 250's part name), para_first (smallint NULL), para_last (smallint NULL), txt_start (integer NULL), txt_end (integer NULL; offsets in `body_text`, 0-based, end exclusive), split (boolean NOT NULL default false), context_line (varchar 200 NOT NULL; the embedded context line, decision 10), text (text NOT NULL; `order_body`: exactly `body_text[txt_start:txt_end]` of every reading with the key; `case_sheet`: the sheet), sheet_sha256 (varchar 64 NULL; `case_sheet`: of `text`), embed_sha256 (varchar 64 NOT NULL; SHA-256 of the exact embedding input: profile document prefix, context line, newline, text; the profile is fixed per model key, see `research_embeddings`), chars (integer NOT NULL), search_vector (tsvector, `GENERATED ALWAYS AS (to_tsvector('english', text)) STORED`), retired_at (timestamptz NULL), retire_reason (`research_retire_reason` NULL), created_at, updated_at | CHECK `ck_research_chunks_shape`: `order_body` ⇔ body_sha256, form, parser_version, first_reading_id, part, para_first, para_last, txt_start, txt_end NOT NULL and case_id, sheet_sha256 NULL; `case_sheet` ⇔ case_id and sheet_sha256 NOT NULL and the order columns NULL. CHECK `ck_research_chunks_retired` (`(retired_at IS NULL) = (retire_reason IS NULL)`); CHECK `ck_research_chunks_span` (`txt_start IS NULL OR (0 <= txt_start AND txt_start < txt_end)`). Partial unique `ix_research_chunks_set_current` (body_sha256, form, parser_version, chunker_version, seq) WHERE kind = 'order_body' AND retired_at IS NULL; partial unique `ix_research_chunks_sheet_current` (case_id) WHERE kind = 'case_sheet' AND retired_at IS NULL. Indexes: partial `ix_research_chunks_key` (body_sha256, form, parser_version) WHERE retired_at IS NULL; partial `ix_research_chunks_embed_sha256` (embed_sha256) WHERE retired_at IS NULL; partial GIN `ix_research_chunks_search_vector_gin` (search_vector) WHERE retired_at IS NULL; `ix_research_chunks_first_reading_id`; partial `ix_research_chunks_case_id` (case_id) WHERE case_id IS NOT NULL. Trigger `research_chunks_retire_once` (function `aslms_research_retire_once`, the 0035 pattern): every column except `retired_at`, `retire_reason` and `updated_at` is fixed, and those two change once, from NULL; plus `set_updated_at`. Grants: ALL to `aslms_owner`, SELECT to `aslms_readonly`, SELECT / INSERT / UPDATE to `aslms_app` (no DELETE; not on the §6 cascade list). Comment `class=derived`. Written only by `services/research_index.py` from current `order_sections` readings and court-public case fields (design `research-index`, decisions 2, 9 and 11); re-buildable; never deleted. The chunk set of a key is cut once; every current reading with the same (body_sha256, form, parser_version) shares it; pages and `src` offsets are read from each reading's own `paragraphs` when cited (decision 13). Estimated size about 0.9 GB for about 421,000 current rows. |
| `research_embeddings` (derived) | id (uuid v7 PK), input_sha256 (varchar 64 NOT NULL; equals `research_chunks.embed_sha256` of every chunk it serves), first_chunk_id (→ research_chunks RESTRICT, NOT NULL), model (varchar 160 NOT NULL; Ollama's full name with tag, `embeddinggemma:300m` today), model_digest (varchar 80 NOT NULL; as `/api/tags` gives it), model_key (varchar 180 NOT NULL; `<model>@<first 12 hex digits of the digest>`), profile (varchar 40 NOT NULL; the `EMBED_PROFILES` entry, which fixes the prefixes), dims (smallint NOT NULL), embedding (halfvec NOT NULL), retired_at (timestamptz NULL), retire_reason (`research_retire_reason` NULL), created_at, updated_at | CHECK `ck_research_embeddings_dims` (`dims BETWEEN 64 AND 4000 AND vector_dims(embedding) = dims`); CHECK `ck_research_embeddings_retired` (`(retired_at IS NULL) = (retire_reason IS NULL)`). Partial unique `ix_research_embeddings_current` (input_sha256, model_key) WHERE retired_at IS NULL. Indexes: `ix_research_embeddings_first_chunk_id`; partial `ix_research_embeddings_model_key` (model_key) WHERE retired_at IS NULL; HNSW `ix_research_embeddings_hnsw_768` USING hnsw ((embedding::halfvec(768)) halfvec_cosine_ops) WITH (m = 16, ef_construction = 64) WHERE dims = 768 AND retired_at IS NULL (768 is the dimension of `embeddinggemma:300m`, the model chosen by the test; decision 5). Trigger `research_embeddings_retire_once` (the same function) plus `set_updated_at`. Grants as `research_chunks`. Comment `class=derived`. Written only by `services/research_embed.py` with vectors from the local Ollama model (`integration/ollama/`, `POST /api/embed`, `truncate: false`); never from notes, remarks, internal documents or drafts. Joined to chunks by `input_sha256` = `embed_sha256` with no foreign key (DB_STANDARD §13); `first_chunk_id` keeps the chain. Retired (`chunk_retired`) when no current chunk has its hash, and (`model_changed`) by `aslms research-index rebuild --embeddings`; never deleted. Estimated size about 0.7 GB of heap plus about 0.8 to 0.9 GB of index for about 420,000 vectors at 768 dimensions. |

## Services

- **`integration/ollama/client.py`**:
  - `embed` and `embed_sync`, and `parse_embed`, which returns `EmbedReply(embeddings, model, prompt_eval_count,
    total_duration)`. A reply that is not an object, has no `embeddings` list, gives a count other than the inputs or
    holds a non-number is `SourceTraceProtocolError`.
  - `__init__.py` exports them.
- **`services/research_chunks.py`** (pure; no database):
  - `CHUNKER_VERSION`, `CHUNK_MIN_CHARS`, `EMBED_PROFILES`;
  - `cap_chars(profile)`;
  - `chunk_reading(form, body_text, paragraphs, parts, *, cap) -> list[ChunkSpec]` (decision 9);
  - `context_line(form, part, labels)`;
  - `embed_input(profile, context_line, text)` and its hash;
  - `case_sheet_text(case, parties, acts, short_orders)` (decision 11);
  - `split_long(text, cap)`.
- **`services/research_index.py`** (database):
  - `sync_sets(session, *, since, limit)` cuts the sets of current readings without one, through the partial unique
    index; a lost race counts `skipped`;
  - `retire_orphans(session, *, since)`;
  - `sync_sheets(session, *, since, limit)`;
  - `reconcile(session)` (the daily full pass);
  - `status(session, cfg, *, timeout_s)`;
  - `rebuild(session, *, chunks, embeddings, actor)`, audited;
  - `holders(session, chunk_ids, scope)`, which returns the current readings and orders that hold each chunk.
- **`services/research_embed.py`**:
  - `live_key(client, model)`;
  - `pending(session, key, *, limit, backfill)`;
  - `embed_batch(session, client, key, chunks)`, which inserts with `ON CONFLICT DO NOTHING` on the current unique
    index;
  - `retire_unused(session)`;
  - `wait_for_people(redis)`;
  - `run_job(session_factory, client, cfg)`, which writes `job_runs` `research_index` with its counters;
  - `backfill(...)` for the CLI.
- **`services/research_search.py`**:
  - `embed_question(client, cfg, question)` returns a vector or a reason;
  - `ranked_words`, `ranked_meaning` and `fuse`;
  - `expand(session, items, scope)`, with weights, shared bodies and grouping;
  - `apply_filters`;
  - `passages(session, request, budget, *, vector, filters, limit)` returns the `Passage` list `assistant_ollama`
    already takes, with the new citation fields and the full context line;
  - `passage_view(session, citation)` serves the passage endpoint.
- **`services/answer_checks.py`** and **`services/answer_check_rules.py`** (pure):
  - `split_sentences`;
  - `check(answer, sources) -> Checked(text, removed: list[(index, reason)], withheld: str | None, quotes:
    dict[label, list[(start, end)]], counts)`.
- **`services/assistant_ollama.py`**:
  - `PROMPT_VERSION = 3` with rules 9 and 10;
  - retrieval through `research_search.passages` when `RESEARCH_INDEX_ENABLED`, the scope is `my_cases` or
    `research`, or for the related orders of `case`; otherwise as today;
  - `answer_checks.check` after `check_citations`;
  - `model_info.retrieval` and `checks`;
  - the asking flag set and cleared around the slot.
- **`services/assistant.py`**:
  - `filters` validated and stored in `scope_info`;
  - the citation fields mapped and re-checked on read (`text_changed`);
  - `passage_for(session, user, message_id, label)`, own answers only.
- **`services/service_checks.py`**: `check_research_model`.
- **`services/data_health.py`**: the `research_index` block.
- **`services/preflight.py`**:
  - `no_cloud_model` covers `RESEARCH_EMBED_MODEL`;
  - a warning `research_index_mode` (enabled while `ASSISTANT_MODE` is not `ollama`);
  - `no_local_model` is unchanged.
- **`domain/research.py`**: the models `ResearchChunk` and `ResearchEmbedding`.
- **`db/base.py`**: `HalfVec`.
- **`cli/research.py`**: `aslms research-index`:
  - `status`;
  - `run [--backfill] [--chunks-only] [--limit N] [--pause-ms N]`;
  - `rebuild (--chunks | --embeddings) --yes` (audited);
  - `search "question" [--scope research|my_cases] [--explain]`, read-only, printing the two lists and the fused order
    with order ids, case numbers, pages and scores for Verification. It sends no text to the chat model. This fourth
    sub-command is a small addition to the owner's three.
- **`jobs/celery_app.py`**: the tasks `aslms.research_index` and `aslms.research_index_reconcile`.
- **`infra/postgres/Dockerfile`**, `compose.yml` (`postgres` build; `scheduler` `extra_hosts`) and
  `.github/workflows/ci.yml` (the pinned install step).

## API

Every route keeps its existing guard. No new function.

| Method and path | Function | Change |
|---|---|---|
| `POST /assistant/ask` | `assistant.use` (unchanged) | Optional `filters` `{forms?, substantive_only?, outcomes?, against_state?, cites?, act?, from?, to?}` for `research` and `my_cases` (400 `filters_not_allowed` otherwise; 400 `bad_filter` for an unknown outcome or act key or `from` after `to`). The answer's `model_info` gains `retrieval` and `checks`; court-order citations gain `chunk_id`, `reading_id`, `paragraphs`, `src`, `pdf_sha256`, `text_sha256`, `parser_version`, `chunker_version`, `model_key`, `match`, `same_words_in`, `quotes`. Visibility as today: court orders open to every assistant user; filings by the document rule. |
| `GET /assistant/conversations/{id}` | `assistant.use` (unchanged; own conversations only) | Citations as above, plus `text_changed` computed on read. |
| `GET /assistant/messages/{message_id}/sources/{label}/passage` | `assistant.use` | **New.** Only for a court-order citation with `src` in an answer of the reader's own conversation (404 otherwise, as the court-order view). Returns `{order_id, document_id, page, page_count, page_text, highlights: [{start, end, kind: "passage" or "quote", exact}], text_changed}`: the stored text of that page (`document_text.full_text` split at form feeds), offsets relative to the page. Court-public text; not audited, like "What the Order Says". |
| `GET /assistant/status` | `assistant.use` (unchanged) | Gains `research: {state, coverage}` (decision 32). |
| `GET /admin/data-health` | `reports.state`, `admin.napix_refetch` or `admin.masters_sync` (unchanged) | Gains the `research_index` block (counts only). |
| `GET /admin/system-health` | `admin.service_health` (unchanged) | Gains the check `research_model` when enabled. |

## Jobs

| Kind | Where | Schedule | What | Writes |
|---|---|---|---|---|
| `research-index` | scheduler (Celery beat) | every 5 minutes at minutes 4, 9, … | sets for new readings, orphans retired, changed sheets, then embedding newest first, within `RESEARCH_JOB_SECONDS`; returns at once without calling Ollama when disabled or the model is not ready (`model_unready`) | `job_runs` `research_index` `{cut, retired, sheets, embedded, reused, failed, skipped, waited_ms, model_unready, watermark}` |
| `research-index-reconcile` | scheduler | 01:45 IST | full comparison of keys and sheets; retries of `research_embed` failures | `job_runs` `research_index_reconcile` |
| backfill | `docker compose run -d --rm api aslms research-index run --backfill` | once after deploy, and after a model change | every waiting chunk in decision 30's order, resumable | `job_runs` rows `research_index` per batch |

No `fetch_queue` row and no NAPIX call from any of them.

## Tests

**Unit (no database):**
- `test_chunk_interim_whole`: an interim body up to the cap is one chunk.
- `test_chunk_runs_never_cross_parts`: on the masked `judgment_parts.txt` reading, no chunk spans two parts.
- `test_chunk_min_and_cap`: runs grow to `CHUNK_MIN_CHARS` and stop before the cap.
- `test_chunk_split_only_over_cap_at_sentence_end`.
- `test_chunk_text_equals_body_slice`.
- `test_chunk_no_empty_body`.
- `test_context_line_has_no_case_values`: the embedded line never holds a case number, date or judge (decision 10).
- `test_case_sheet_fields_and_caps`: no CNR, `ref_no`, next hearing or advocate; parties capped with "and N more".
- `test_embed_input_hash_includes_prefix`.
- `test_parse_embed_errors`.
- `test_embed_sends_truncate_false_and_num_ctx` (`httpx.MockTransport`): `num_ctx` and `num_batch` both equal the
  profile's input limit; a 400 and a 413 "input length exceeds the context length" both read as too long.
- `test_no_cloud_embed_model`.
- `test_only_listed_modules_import_the_ollama_client`, `test_api_embed_only_in_client`: the existing guards extended.
- `test_no_vector_or_model_library_in_lock`: no `numpy`, `pgvector` or `sentence-transformers` in `uv.lock`.
- `test_rrf_fuse`: k = 60; an item on both lists beats an item first on one.
- `test_weights_and_grouping`: procedural × 0.5; at most 2 passages per order; adjacent chunks merged; shared bodies
  give one item with `same_words_in`.
- `test_small_to_big_stays_in_part`.
- `test_split_sentences_abbreviations`: `No.`, `W.P.(C)`, initials, `Hon'ble`.
- `test_quote_exact_with_whitespace_only`: a changed letter fails; a line break passes.
- `test_uncited_sentence_rules`.
- `test_dates_numbers_words`: "4 weeks" backed by "four weeks"; "12.03.2024" backed by "12th March, 2024".
- `test_case_numbers_and_citations_compacted`.
- `test_names_reordered_pass_invented_fail`.
- `test_outcome_word_or_rule_outcome`.
- `test_removal_note_and_withheld_rules`: the first sentence, the majority, none cited.
- `test_checks_pure_imports`.
- `test_prompt_version_3_rules`.
- `test_research_readers_touch_only_court_tables`: the SQL table scan of decision 2.
- `test_pgvector_pin_same_in_dockerfile_and_ci`.
- `test_scheduler_has_host_gateway`.

**Database (scripted Ollama through `httpx.MockTransport`, never a real model):**
- `test_migration_0042_up_down_up`: extension, types, tables, the HNSW index and the two `order_sections` GIN indexes.
- `test_halfvec_binding_and_dims_check`: a wrong dimension is refused.
- `test_retire_once_trigger`: any other change is refused; `aslms_app` has no DELETE.
- `test_sets_shared_by_identical_bodies`: two orders with one body produce one set.
- `test_new_reading_same_body_reuses_set`, `test_changed_body_retires_old_set_and_vectors`.
- `test_parser_version_bump_reuses_vectors_by_hash`.
- `test_sheet_new_on_change`.
- `test_job_budget_and_watermark`.
- `test_job_waits_for_asking_flag`.
- `test_embed_failure_recorded_and_retried`.
- `test_model_key_change_ignores_old_vectors`: words-only until new vectors exist.
- `test_rebuild_embeddings_audited`.
- `test_hybrid_research_finds_by_meaning_and_by_number`: a fake vector space where the meaning list finds a reworded
  passage and the words list finds `WP(C)/7013/2024`.
- `test_my_cases_exact_scan`.
- `test_filters_cites_act_outcome_dates`; `test_against_state_rule`; `test_filters_refused_for_case_and_my_work`.
- `test_unindexed_order_still_found_by_words`.
- `test_stale_text_never_cited`: a changed `document_text` drops the order and counts `stale_dropped`.
- `test_query_embed_failure_words_only`: the question is answered with `retrieval.kind = words_only`.
- `test_citation_fields_and_text_changed_on_read`.
- `test_passage_endpoint_own_answer_only`: page-relative highlights; 404 for another user's message.
- `test_answer_checks_applied_case_scope_internal`: a sentence citing a note with an invented date is removed.
- `test_my_work_and_facts_not_checked`.
- `test_audit_counts_no_text`: `assistant.answered` carries `retrieval` and `checks` and no text.
- `test_data_health_research_block_timeout_parts`; `test_system_health_research_model_check`;
  `test_assistant_status_research_state`.
- `test_preview_mode_unchanged`: no embed call in preview.
- `test_no_napix_no_fetch_queue`: job and CLI.

## Verification

1. **Image and migration.** Build the postgres image from a clean worktree of `main`. `pre-migrate` backup, stop the
   app services, recreate `postgres` on the same volume, then `migrate`. Check:
   - `SELECT extversion FROM pg_extension WHERE extname = 'vector'` gives 0.8.7;
   - `\d+ research_embeddings` shows the HNSW index;
   - `aslms_app` cannot DELETE from either table.
2. **Ollama's fields.** With the chosen model pulled, one `embed_sync` of two short texts records `embeddings`
   (2 × dims), `model` and `prompt_eval_count` on Ollama 0.40.11 (the names the model test saw). An over-long input
   with `truncate: false` answers 400 (past `num_ctx`) or 413 (past `num_batch`).
3. **Chunks only.** `aslms research-index run --chunks-only --backfill` with the switch off. Expected: about 336,000
   order chunks (±2% of the simulation) and 84,898 sheets. `status` shows 0 vectors. Time recorded.
4. **Words-only safety.** With the switch off, an All Court Orders question answers as before
   (`retrieval.kind = words`). The checks apply, and `model_info.checks` is present.
5. **Backfill.** Switch on and run the backfill detached. Record the rate on the owner's GPU, the total time, the
   court calls in the window (none from the backfill) and any Assistant question asked meanwhile (it waits under
   5 s). Then record:
   - `pg_total_relation_size` of both tables and the index;
   - the coverage in `status`, data-health and System Health.
6. **Search check (owner and integrator).** Run `aslms research-index search --explain` for the 20 hand questions of
   the model test. The meaning list finds reworded passages the words list misses. A case number and a citation
   query are found by words. Grouping holds: no answer has more than 2 passages of one order.
7. **Worked example for Annexure E.** One question asked against the masked fixtures in a test database, with the
   lists, the fused order, the sources and the checked answer, including one removed sentence, saved for the scribe.
8. **The owner's live check.** Five questions in All Court Orders and three in My Cases on the owner's machine. Each
   answer's sources open at their page. A deliberately leading question ("on which date did the court dismiss…" when
   it did not) is withheld or loses the sentence. `model_info.checks` and `retrieval` are recorded.
9. **Model change drill** (test database). Change `RESEARCH_EMBED_MODEL` to a second pulled tag. Old vectors are
   ignored and the words list carries the search. The job embeds under the new key; `rebuild --embeddings` retires
   the old ones and writes one audit row.

## The model test
Run by the architect on 23 Nov 2026, 12:33 to 15:00 IST (about 2 hours 30 minutes), on the owner's machine: Ollama
0.40.11, Intel Core i7-14650HX (16 cores), 32 GB, RTX 4070 Laptop 8 GB with `qwen3.5:4b` loaded on it throughout.
Read-only on the dev database, no court call, scripts and extracts in the session scratchpad only (court text never left
the machine). The only network use was the model downloads.

**The candidates** (from `/api/tags` after the pull; every tag existed as named):

| Tag | Digest (SHA-256) | Size | Dims | Input limit | Cap (decision 9) |
|---|---|---:|---:|---:|---:|
| `bge-m3:567m` | `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab` | 1.16 GB (F16) | 1,024 | 8,192 | 20,000 |
| `nomic-embed-text:latest` | `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f` | 0.27 GB (F16) | 768 | 2,048 | 5,120 |
| `embeddinggemma:latest` (= `:300m`) | `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1` | 0.62 GB (BF16) | 768 | 2,048 | 5,120 |
| `qwen3-embedding:0.6b` | `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d` | 0.64 GB (Q8_0) | 1,024 | 8,192 used (32,768 allowed) | 20,000 |

Prefixes used: bge-m3 none; nomic-embed-text `search_document: ` and `search_query: `; embeddinggemma `title: none |
text: ` and `task: search result | query: `; qwen3-embedding none on documents and `Instruct: Given a question about
Gauhati High Court orders, retrieve the order passages that answer it`, a newline and `Query: ` on questions. Every call:
`truncate: false`, `options: {num_gpu: 0, num_ctx: <limit>, num_batch: <limit>}`, 8 inputs per call. No input was
refused. The `/api/embed` fields seen are recorded in decision 6.

**The orders, the seed and the mix.**
- Targets: current readings (`replaced_at IS NULL`), not procedural, body not empty, one reading per distinct
  (`body_sha256`, `form`), ordered within each form by `md5(id || 'aslms-251-target')`: the first 80 interim, 60 final
  and 60 judgments.
- Distractors: the same filter with the targets' bodies left out, ordered by `md5(id || 'aslms-251-distract')`; 1,500
  interim, 1,150 final and 1,150 judgments drawn (22,651 chunks at the 20,000 cap, the planned "20,000 other chunks of
  the same mix"). **Used: the first 150, 115 and 115 (2,276 chunks at the 20,000 cap, 2,314 at 5,120).** Reason: the
  200-chunk speed check gave 1.36 (bge-m3), 4.52 (nomic-embed-text), 3.93 (embeddinggemma) and 0.86 (qwen3-embedding)
  chunks per second on CPU, so the full set would have taken about 16 hours for the four models; one tenth of each
  form's distractor orders kept the whole run near the 3 hours allowed. Every chunk of the 200 test orders was kept
  (1,313 at the 20,000 cap), so the other passages of the same judgment stayed in as the hardest distractors.
- Chunking: decision 9 as written, with each model's own cap. 3,589 chunks at the 20,000 cap (10 split pieces) and
  3,673 at 5,120 (114 split pieces). Embedded input: the profile's document prefix, the embedded context line
  (decision 10), a newline and the text.
- The target chunk: the body of an interim order, else a chunk chosen by `random.Random("251-<reading id>")` among the
  order's chunks outside `opening` with at least 400 characters. A retrieved chunk counts as the target when it is
  from the same reading and its span overlaps the target's span, so the two caps compare fairly.
- Questions: `qwen3.5:4b`, `think` off, temperature 0.7, seed 251 (plus one per retry), sent one at a time with the
  live model's own context size so it was never reloaded. 133 were accepted first time, 54 on the second try and 12
  on the third; 1 (a judgment) was dropped: **199 questions** (80 interim, 60 final, 59 judgments), 204 s of chat.
- Hand questions: 20 (decision 5). The fused top 5 of every model were pooled (247 passages) and each was judged by
  reading: it counts when it deals with the question's issue.

**The two lists and the fusion.**
- Words: the exact query of decision 17(a), run in the dev PostgreSQL 16 inside a read-only transaction:
  `to_tsvector('english', text) @@ websearch_to_tsquery('english', question)`, ranked by `ts_rank_cd`, top 100. The
  chunk texts were rebuilt in SQL as `substr(body_text, s + 1, e - s)` from the reading ids and offsets passed in a
  `VALUES` list; nothing was written and no temporary table was made. This is the same text search configuration,
  operator and ranking function the index will use, which is why it was preferred to a local BM25.
- Meaning: cosine similarity of the question's vector to every chunk's vector in the script, top 100
  (`RESEARCH_CANDIDATES`).
- Fusion: reciprocal rank fusion with k = 60 (decision 17). Decision 18's weights were not applied: every test order is
  substantive, and the weights act the same on every model.

**Results** (199 generated questions; hand precision@5 over the 20 hand questions; CPU speed over the whole test set,
with the 200-chunk check in brackets):

| Model | Fused recall@10 | Fused MRR@10 | Vector recall@10 | Vector MRR@10 | Hand precision@5 | CPU chunks/s | Dims | Bytes per vector (halfvec) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `embeddinggemma` | **86.4** | **0.661** | 86.9 | 0.659 | 46 | 4.07 (3.93) | 768 | 1,536 |
| `qwen3-embedding:0.6b` | 83.4 | 0.639 | 83.4 | 0.641 | 46 | 1.01 (0.86) | 1,024 | 2,048 |
| `bge-m3:567m` | 77.4 | 0.595 | 77.4 | 0.598 | 49 | 1.68 (1.36) | 1,024 | 2,048 |
| `nomic-embed-text` | 64.3 | 0.446 | 64.3 | 0.446 | 35 | 4.12 (4.52) | 768 | 1,536 |

Fused recall@10 by form (interim 80, final 60, judgments 59 questions):

| Model | Interim | Final | Judgment |
|---|---:|---:|---:|
| `embeddinggemma` | 80.0 | 90.0 | 91.5 |
| `qwen3-embedding:0.6b` | 82.5 | 80.0 | 88.1 |
| `bge-m3:567m` | 68.8 | 81.7 | 84.7 |
| `nomic-embed-text` | 51.2 | 75.0 | 71.2 |

- The words list alone found the target in the top 10 for 1 of the 199 questions; 11 of all 219 questions matched any
  chunk (decision 17, "What the model test showed about the words list").
- With an OR words list (tried, not adopted) fused recall@10 fell to 63.3 (embeddinggemma), 70.4 (qwen3-embedding),
  59.3 (bge-m3) and 56.3 (nomic-embed-text).
- Tokens: 4.1 to 4.5 characters per token on these orders (embeddinggemma 4.29), against the 2.5 the cap assumes.
- Full-run times on CPU: embeddinggemma 902 s, nomic-embed-text 892 s, bge-m3 2,130 s, qwen3-embedding 3,545 s.

**The judgment context (decision 8).** 1,013 sentences by `qwen3.5:4b` (762 s on the GPU); the 60 test judgments'
1,037 chunks embedded again by embeddinggemma with the sentence (306 s on CPU). Judgment recall@10: 91.5 without, 91.5
with (vector-only and fused); fused MRR@10 0.676 without, 0.685 with. The rule needs +5 points: **not adopted.**

**The model chosen by the rule: `embeddinggemma:300m`** (digest `85462619ee72…`, the same as `embeddinggemma:latest`).
Best fused recall@10, 3.0 points ahead of qwen3-embedding, so the 2-point speed tie-break does not apply; its 2,048-token
limit is not under 2,048. It is also about four times faster on CPU than the two 1,024-dimension models, and its vectors
are a quarter smaller.

**Limits of the test, stated so nobody reads more into it.**
- The distractor set was one tenth of the plan, so every recall figure is higher than it would be against the full
  index of about 336,000 chunks. The rule compares the models with each other, and their order was the same in
  vector-only and fused results.
- qwen3-embedding was better on interim orders (82.5 against 80.0) and bge-m3 on the hand questions (49 against 46,
  that is 3 passages out of 100); the rule decides on fused recall over all 199 questions.
- The hand judgments are one reader's. Questions written from a passage tend to carry its specifics; the hand
  questions test general subjects. Four hand questions (pension withheld for a pending case, recovery as arrears of land
  revenue, a last opportunity to comply, and compensation without acquisition) found little or nothing relevant in so
  small a sample for any model.
- CPU speeds were measured with the chat model loaded on the GPU and, for part of the time, writing questions and
  sentences. The GPU speed and memory of the embedding model are measured in Verification 5.

After the test the three other candidates and the `embeddinggemma:latest` tag were removed with `ollama rm`; Ollama
holds `embeddinggemma:300m` and `qwen3.5:4b`.

## Open questions

1. **May the four candidate embedding models be pulled and the test run now?** This note cannot name the model
   without it (decision 5). The test:
   - downloads about 2.7 GB to the Ollama server on this machine: `bge-m3:567m`, `nomic-embed-text`, `embeddinggemma`
     and `qwen3-embedding:0.6b`;
   - runs on CPU (`num_gpu = 0`), so the live Case Assistant model stays loaded on the GPU, for about one to two hours;
   - reads the dev database read-only and makes no court call;
   - uses `qwen3.5:4b` to write the 200 test questions, so the live Assistant is slower for anyone asking during that
     time.

   **(a) Recommended:** yes. The architect runs it, records the results under "The model test", fills in the model,
   its dimension and the decision 8 result, and returns the note for approval. The unused models can be removed
   afterwards (`ollama rm`).

   **(b)** The developer runs the same test as the first build step, under the rule of decision 5, and the owner
   approves the rule now instead of the named model.

   **Answered (owner, 23 Nov 2026): (a).** The architect runs the test now and returns the note with the model named.
   **Done (23 Nov 2026):** the test was run (under "The model test"); the rule chose `embeddinggemma:300m` (768
   dimensions, 2,048-token input, cap 5,120 characters); decision 8's context sentence was not adopted. The other
   candidates were removed. No question remains open.

## Owner's answers (23 Nov 2026)
- **Open question 1:** option (a), the architect runs the model test now (decision 5) and returns the note for approval
  with the model named; unused models are removed afterwards.
- **Decision 1 confirmed:** the research index is built locally first, a recorded deviation from the plan's
  "research index held in SourceTrace", then sent to SourceTrace when row 36 arrives.
- **`against_state` by rule confirmed:** `allowed` or `partly_allowed` with the State as a current respondent, or
  `dismissed` with the State as a current petitioner; disposed of, withdrawn and closed count neither way.
