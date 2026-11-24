"""The research index's chunker, context lines, case sheets and embedding inputs (design `research-index`, decisions
9 to 12; "Tests", unit), and the embedding call of the Ollama client (decision 6). No database, no network, no model."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from aslms.integration.ollama import OllamaClient, parse_embed, too_long
from aslms.integration.sourcetrace.connector import SourceTraceProtocolError, SourceTraceRejected
from aslms.services import order_parse as P
from aslms.services import research_chunks as rc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "orders"
GEMMA = rc.EMBED_PROFILES["embeddinggemma"]
CAP = rc.cap_chars(GEMMA)


def load(name: str) -> str:
    text = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
    return text.replace("<FF>", "\f").replace("GAHC01XXXXXX", "GAHC01000001").strip()


def reading(name: str, kind: str):
    r = P.parse(load(name), napix_kind=kind)
    return r.form, r.body_text, r.paragraphs, r.parts


def para(i, s, e, part="body", label=None):
    return {"i": i, "label": label, "page": 1, "page_to": 1, "src": [s, e], "txt": [s, e], "part": part}


# ------------------------------------------------------------------------------------------------ profiles and cap


def test_profile_and_cap_for_the_chosen_model():
    assert rc.profile_for("embeddinggemma:300m") is GEMMA
    assert rc.profile_for("nomic-embed-text:latest") is None
    assert (GEMMA.dims, GEMMA.input_tokens) == (768, 2048)
    assert CAP == 5120
    assert rc.cap_chars(rc.EmbedProfile("x", "", "", 32768, 1024)) == rc.CAP_MAX


# ------------------------------------------------------------------------------------------------ chunking


def test_chunk_interim_whole():
    form, body, paras, parts = reading("interim_template", "interim")
    chunks = rc.chunk_reading(form, body, paras, parts, cap=CAP)
    assert len(chunks) == 1
    c = chunks[0]
    assert not c.split and c.context_line == "Order"
    assert c.text == body[c.txt_start : c.txt_end] == body.strip()
    assert (c.para_first, c.para_last) == (paras[0]["i"], paras[-1]["i"])


def test_chunk_runs_never_cross_parts():
    form, body, paras, parts = reading("judgment_parts", "judgment")
    chunks = rc.chunk_reading(form, body, paras, parts, cap=CAP)
    assert len(chunks) >= 3
    by_i = {p["i"]: p for p in paras}
    for c in chunks:
        covered = [by_i[i]["part"] for i in range(c.para_first, c.para_last + 1) if i in by_i]
        assert set(covered) == {c.part}, c
        assert c.context_line.startswith("Judgment · ")
    assert [c.seq for c in chunks] == list(range(len(chunks)))
    # every paragraph is in exactly one chunk, in order
    seen = [i for c in chunks for i in range(c.para_first, c.para_last + 1)]
    assert seen == sorted(seen) and len(seen) == len(set(seen))


def test_chunk_min_and_cap():
    body_parts = []
    paras = []
    pos = 0
    for i in range(12):
        t = f"{i + 1}. " + ("word " * 60).strip() + "."
        paras.append(para(i, pos, pos + len(t), part="reasoning", label=f"{i + 1}."))
        body_parts.append(t)
        pos += len(t) + 2
    body = "\n\n".join(body_parts)
    chunks = rc.chunk_reading("judgment", body, paras, cap=CAP)
    for c in chunks[:-1]:
        assert len(c.text) >= rc.CHUNK_MIN_CHARS  # a run grows to the minimum
    small = rc.chunk_reading("judgment", body, paras, cap=700)
    assert all(len(c.text) <= 700 for c in small)
    assert all(not c.split for c in small)  # no paragraph is over the cap, so nothing is split


def test_chunk_split_only_over_cap_at_sentence_end():
    sentence = "The respondents shall consider the claim afresh. "
    long_para = (sentence * 40).strip()
    short = "2. Heard."
    body = long_para + "\n\n" + short
    paras = [
        para(0, 0, len(long_para), part="reasoning"),
        para(1, len(long_para) + 2, len(body), "reasoning"),
    ]
    chunks = rc.chunk_reading("final", body, paras, cap=600)
    pieces = [c for c in chunks if c.split]
    assert len(pieces) >= 3 and all(len(c.text) <= 600 for c in pieces)
    assert all(c.text.endswith(".") for c in pieces)  # cut at a sentence end
    assert not chunks[-1].split and chunks[-1].text == short
    # a paragraph within the cap is never split
    assert not any(c.split for c in rc.chunk_reading("final", body, paras, cap=CAP))


def test_split_long_falls_back_to_space_and_never_empty():
    text = "x" * 50 + " " + "y" * 50
    pieces = rc.split_long(text, 60)
    assert [text[a:b] for a, b in pieces] == ["x" * 50, "y" * 50]
    assert rc.split_long("   ", 10) == []


def test_chunk_text_equals_body_slice():
    for name, kind in (
        ("judgment_parts", "judgment"),
        ("final_directions", "final"),
        ("interim_variants", "interim"),
    ):
        form, body, paras, parts = reading(name, kind)
        for c in rc.chunk_reading(form, body, paras, parts, cap=CAP):
            assert c.text == body[c.txt_start : c.txt_end]
            assert c.text == c.text.strip() and c.text


def test_chunk_no_empty_body():
    assert rc.chunk_reading("interim", "", [], cap=CAP) == []
    assert rc.chunk_reading("judgment", "  \n ", [], cap=CAP) == []


def test_context_line_has_no_case_values():
    for name, kind in (
        ("judgment_parts", "judgment"),
        ("final_directions", "final"),
        ("interim_template", "interim"),
    ):
        form, body, paras, parts = reading(name, kind)
        for c in rc.chunk_reading(form, body, paras, parts, cap=CAP):
            line = c.context_line
            assert not re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", line)  # no date
            assert not re.search(r"\(C\)|/\d{4}|GAHC", line)  # no case number or CNR
            assert "Justice" not in line and "JUSTICE" not in line
            assert len(line) <= rc.CONTEXT_MAX
    assert rc.context_line("judgment", "reasoning", ["14.", "15.", "16."]) == (
        "Judgment · Reasoning · paragraphs 14 to 16"
    )
    assert rc.context_line("final", "conclusion", ["7."]) == "Final Order · Conclusion · paragraph 7"
    assert rc.context_line("interim", "body", ["1."]) == "Order"


# ------------------------------------------------------------------------------------------------ case sheets


def test_case_sheet_fields_and_caps():
    case = {
        "case_type": "WP(C)",
        "year": 2024,
        "court": "Gauhati High Court",
        "category": "Service",
        "sub_category": "Regularisation",
        "status": "pending",
        "disposal_nature": None,
        "short_order": "Issue notice.",
        "petitioner_summary": "SUMMARY P",
        "respondent_summary": "SUMMARY R",
        "cnr": "GAHC010000012024",
        "ref_no": "ASLMS/GHC/CASE/2024/000001",
        "next_hearing": "2026-12-01",
        "advocates": ["MR ADVOCATE X"],
    }
    parties = {"petitioner": [f"PETITIONER {i}" for i in range(45)], "respondent": ["THE STATE OF ASSAM"]}
    sheet = rc.case_sheet_text(
        case, parties, ["Assam Services Act s. 3"], ["List after 4 weeks.", "List after 4 weeks.", "Heard."]
    )
    assert sheet.startswith("Case details · WP(C) · 2024 · Gauhati High Court\n")
    assert "Category: Service / Regularisation" in sheet
    assert "PETITIONER 39" in sheet and "PETITIONER 40" not in sheet and "and 5 more" in sheet
    assert "Respondents: THE STATE OF ASSAM" in sheet
    assert "Hearings: List after 4 weeks. | Heard." in sheet
    for banned in ("GAHC010000012024", "ASLMS/", "2026-12-01", "ADVOCATE X", "SUMMARY P"):
        assert banned not in sheet
    # summaries when no party is held
    assert "Petitioners: SUMMARY P" in rc.case_sheet_text(case, {}, [], [])
    # the whole sheet is capped
    long = rc.case_sheet_text(case, {"petitioner": ["N" * 300] * 40, "respondent": []}, [], [])
    assert len(long) <= rc.SHEET_MAX


def test_embed_input_hash_includes_prefix():
    text = "List after four weeks."
    a = rc.input_sha256(GEMMA, "Order", text)
    other = rc.EmbedProfile("other", "search_document: ", "search_query: ", 2048, 768)
    assert a != rc.input_sha256(other, "Order", text)
    assert rc.embed_input(GEMMA, "Order", text) == "title: none | text: Order\nList after four weeks."
    assert a == rc.sha256("title: none | text: Order\nList after four weeks.")
    assert rc.query_input(GEMMA, "pension") == "task: search result | query: pension"


# ------------------------------------------------------------------------------------------------ the client


def test_parse_embed_errors():
    good = {"model": "embeddinggemma:300m", "embeddings": [[0.1, 0.2], [0.3, 0.4]], "prompt_eval_count": 7}
    r = parse_embed(good, 2)
    assert (
        r.embeddings == [[0.1, 0.2], [0.3, 0.4]]
        and r.prompt_eval_count == 7
        and r.model == "embeddinggemma:300m"
    )
    for bad in (
        [],
        {"embeddings": None},
        {"embeddings": [[0.1]]},
        {"embeddings": [[0.1], ["x"]]},
        {"embeddings": [[0.1], [True]]},
        {"embeddings": [[0.1], []]},
    ):
        with pytest.raises(SourceTraceProtocolError):
            parse_embed(bad, 2)


def _client(handler) -> OllamaClient:
    return OllamaClient("http://ollama.test:11434", transport=httpx.MockTransport(handler))


def test_embed_sends_truncate_false_and_num_ctx():
    seen = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        return httpx.Response(
            200, json={"model": body["model"], "embeddings": [[0.5] * 4 for _ in body["input"]]}
        )

    opts = {"num_ctx": GEMMA.input_tokens, "num_batch": GEMMA.input_tokens}
    reply = _client(handler).embed_sync(
        "embeddinggemma:300m", ["a", "b"], options=opts, keep_alive=-1, timeout=5
    )
    assert len(reply.embeddings) == 2
    path, body = seen[0]
    assert path == "/api/embed"
    assert body == {
        "model": "embeddinggemma:300m",
        "input": ["a", "b"],
        "truncate": False,
        "options": {"num_ctx": 2048, "num_batch": 2048},
        "keep_alive": -1,
    }

    for status in (400, 413):

        def refuse(request, status=status):
            return httpx.Response(status, json={"error": "the input length exceeds the context length"})

        with pytest.raises(SourceTraceRejected) as exc:
            _client(refuse).embed_sync("embeddinggemma:300m", ["x"], options=opts, timeout=5)
        assert too_long(exc.value)
