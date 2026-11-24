"""The research index's chunker and case sheet (design `research-index`, decisions 6, 9, 10, 11 and 12): pure, no
database, no network, no model and no model library.

- `chunk_reading(form, body_text, paragraphs, parts, cap=)` cuts one reading of `order_sections` by its structure: an
  interim order's body is one chunk; a final order's or judgment's chunks are runs of whole paragraphs inside one part,
  closed at a part boundary, at `CHUNK_MIN_CHARS` or before the cap; only a paragraph (or an interim body) longer than
  the cap is split, at the last sentence end before it, else at the last space (`split`). No overlap. Every chunk's
  text is exactly `body_text[txt_start:txt_end]`.
- `context_line(form, part, labels)` is the short line embedded with a chunk: only what every order sharing the body
  shares (the form, the part, the paragraph labels), never a case number, date or judge (decision 10).
- `case_sheet_text(...)` writes one case's sheet from court-public fields (decision 11).
- `embed_input(profile, context_line, text)` is the exact text sent to the model (the profile's document prefix, the
  context line, a newline, the text) and `input_sha256` its hash (decision 12).

`EMBED_PROFILES` holds, per model family, the prefixes, the input limit in tokens and the dimensions (decision 6); a
model with no profile is not used."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

CHUNKER_VERSION = 1
CHUNK_MIN_CHARS = 1_000
CHARS_PER_TOKEN = 2.5  # conservative for digits and Indian names (the model test measured 4.1 to 4.5)
CAP_MAX = 20_000
SHEET_MAX = 4_000
SHEET_PARTIES = 40
SHEET_HEARINGS = 5
CONTEXT_MAX = 200
SHEET_CONTEXT = "Case Details"
SENTENCE_END_CHARS = ".?!:;\"'”’)]"


@dataclass(frozen=True)
class EmbedProfile:
    """Decision 6: one model family's prompts (Ollama does not add them), input limit and dimensions. The document
    prefix is part of the embedded input and of its hash."""

    name: str
    doc_prefix: str
    query_prefix: str
    input_tokens: int
    dims: int


EMBED_PROFILES: dict[str, EmbedProfile] = {
    # the model test's winner (decision 5): the model's published prompts
    "embeddinggemma": EmbedProfile(
        name="embeddinggemma",
        doc_prefix="title: none | text: ",
        query_prefix="task: search result | query: ",
        input_tokens=2048,
        dims=768,
    ),
}

FORM_LABELS = {"judgment": "Judgment", "final": "Final Order", "interim": "Order"}
PART_LABELS = {
    "opening": "Opening",
    "facts": "Facts",
    "petitioner_submissions": "Petitioner's Submissions",
    "respondent_submissions": "Respondent's Submissions",
    "issues": "Issues",
    "reasoning": "Reasoning",
    "conclusion": "Conclusion",
}


def profile_for(model: str | None) -> EmbedProfile | None:
    """The profile of a model name (`embeddinggemma:300m` → `embeddinggemma`), or None."""
    family = (model or "").strip().rsplit("/", 1)[-1].split(":", 1)[0].lower()
    return EMBED_PROFILES.get(family)


def cap_chars(profile: EmbedProfile) -> int:
    """Decision 9: the input limit in tokens × 2.5 characters, at most 20,000 (5,120 for `embeddinggemma:300m`)."""
    return min(CAP_MAX, int(profile.input_tokens * CHARS_PER_TOKEN))


@dataclass(frozen=True)
class ChunkSpec:
    seq: int
    part: str
    para_first: int
    para_last: int
    txt_start: int
    txt_end: int
    split: bool
    context_line: str
    text: str


# ------------------------------------------------------------------------------------------------ splitting


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def _cut_at(text: str, start: int, limit: int) -> int:
    """The end of a piece starting at `start` of at most `limit` characters: after the last sentence end followed by
    whitespace, else at the last whitespace, else at the limit."""
    hard = start + limit
    floor = start + max(1, limit // 4)  # a piece is never tiny because a sentence ended early
    for p in range(hard, floor, -1):
        if text[p - 1] in SENTENCE_END_CHARS and p < len(text) and text[p].isspace():
            return p
    for p in range(hard, floor, -1):
        if text[p].isspace():
            return p
    return hard


def split_long(text: str, cap: int, *, start: int = 0, end: int | None = None) -> list[tuple[int, int]]:
    """Decision 9: `text[start:end]` cut into pieces of at most `cap` characters, each ending at the last sentence end
    (`order_parse_rules.SENTENCE_END`'s characters followed by whitespace) before the cap, else at the last space;
    pieces trimmed of surrounding whitespace, never empty. A span within the cap is returned whole."""
    end = len(text) if end is None else end
    s, e = _trim(text, start, end)
    out: list[tuple[int, int]] = []
    while e - s > cap:
        cut = _cut_at(text, s, cap)
        a, b = _trim(text, s, cut)
        if b > a:
            out.append((a, b))
        s, e = _trim(text, cut, e)
    if e > s:
        out.append((s, e))
    return out


# ------------------------------------------------------------------------------------------------ context lines


def _para_label(label: Any) -> str | None:
    if not isinstance(label, str):
        return None
    cleaned = label.strip().strip(".:-").strip()
    return cleaned or None


def context_line(form: str, part: str | None, labels: list[str | None] | tuple[str | None, ...] = ()) -> str:
    """Decision 10: `Judgment · Reasoning · paragraphs 14 to 16`. An interim order's line is its form only. Only what
    every order with the same body shares: never a case number, a date or a judge."""
    bits = [FORM_LABELS.get(str(form), "Order")]
    if str(form) != "interim":
        part_label = PART_LABELS.get(str(part or ""))
        if part_label:
            bits.append(part_label)
        shown = [x for x in (_para_label(lb) for lb in labels) if x]
        if shown:
            first, last = shown[0], shown[-1]
            bits.append(f"paragraph {first}" if first == last else f"paragraphs {first} to {last}")
    line = " · ".join(bits)
    return line[:CONTEXT_MAX]


# ------------------------------------------------------------------------------------------------ chunking


def _txt(p: dict[str, Any]) -> tuple[int, int]:
    t = p.get("txt") or [0, 0]
    return int(t[0]), int(t[1])


def _spec(seq, form, part, paras, s, e, split, body_text) -> ChunkSpec:
    labels = [p.get("label") for p in paras]
    return ChunkSpec(
        seq=seq,
        part=str(part),
        para_first=int(paras[0]["i"]) if paras else 0,
        para_last=int(paras[-1]["i"]) if paras else 0,
        txt_start=s,
        txt_end=e,
        split=split,
        context_line=context_line(form, part, labels),
        text=body_text[s:e],
    )


def _overlapping(paras: list[dict[str, Any]], s: int, e: int) -> list[dict[str, Any]]:
    hit = [p for p in paras if _txt(p)[0] < e and s < _txt(p)[1]]
    return hit or paras[:1]


def chunk_reading(
    form: str,
    body_text: str,
    paragraphs: list[dict[str, Any]],
    parts: list[dict[str, Any]] | None = None,
    *,
    cap: int,
) -> list[ChunkSpec]:
    """Decision 9. `paragraphs` and `parts` are the reading's JSON (row 250); `parts` is accepted for the record, the
    paragraphs carry their own part. An empty body gives no chunk."""
    if not body_text or not body_text.strip():
        return []
    paras = sorted((p for p in paragraphs or [] if _txt(p)[1] > _txt(p)[0]), key=lambda p: _txt(p)[0])
    out: list[ChunkSpec] = []
    if str(form) == "interim" or not paras:
        part = str(paras[0].get("part") or "body") if paras else "body"
        s = _txt(paras[0])[0] if paras else 0
        e = _txt(paras[-1])[1] if paras else len(body_text)
        pieces = split_long(body_text, cap, start=s, end=e)
        split = len(pieces) > 1
        for a, b in pieces:
            out.append(_spec(len(out), form, part, _overlapping(paras, a, b), a, b, split, body_text))
        return out

    run: list[dict[str, Any]] = []

    def close() -> None:
        if not run:
            return
        a, b = _trim(body_text, _txt(run[0])[0], _txt(run[-1])[1])
        if b > a:
            out.append(_spec(len(out), form, run[0].get("part") or "body", list(run), a, b, False, body_text))
        run.clear()

    for p in paras:
        s, e = _txt(p)
        part = p.get("part") or "body"
        if e - s > cap:  # a paragraph longer than the cap: alone, split at sentence ends
            close()
            for a, b in split_long(body_text, cap, start=s, end=e):
                out.append(_spec(len(out), form, part, [p], a, b, True, body_text))
            continue
        if run:
            run_start = _txt(run[0])[0]
            run_chars = _txt(run[-1])[1] - run_start
            if (run[0].get("part") or "body") != part or run_chars >= CHUNK_MIN_CHARS or e - run_start > cap:
                close()
        run.append(p)
    close()
    return out


# ------------------------------------------------------------------------------------------------ case sheets


def _cap_side(names: list[str]) -> str:
    names = [n.strip() for n in names if n and n.strip()]
    if len(names) <= SHEET_PARTIES:
        return "; ".join(names)
    rest = len(names) - SHEET_PARTIES
    return "; ".join(names[:SHEET_PARTIES]) + f" and {rest} more"


def case_sheet_text(
    case: dict[str, Any],
    parties: dict[str, list[str]],
    acts: list[str],
    short_orders: list[str],
) -> str:
    """Decision 11, from court-public fields only, in this order: the heading line, category and sub-category, acts and
    sections, the petitioners and respondents (current parties in party order, else the summaries; at most 40 a side,
    then "and N more"), status and disposal nature, the case's short order, the distinct short orders of its last 5
    hearings. No advocate, CNR, `ref_no`, next hearing, owner or internal value. At most 4,000 characters.

    `case` holds `case_type`, `year`, `court`, `category`, `sub_category`, `status`, `disposal_nature`,
    `short_order`, `petitioner_summary`, `respondent_summary`; `parties` `{"petitioner": [...], "respondent": [...]}`."""
    head = ["Case details"]
    for key in ("case_type", "year"):
        if case.get(key) not in (None, ""):
            head.append(str(case[key]))
    head.append(str(case.get("court") or "Gauhati High Court"))
    lines = [" · ".join(head)]
    category = " / ".join(str(case[k]).strip() for k in ("category", "sub_category") if case.get(k))
    if category:
        lines.append(f"Category: {category}")
    acts = [a.strip() for a in acts if a and a.strip()]
    if acts:
        lines.append("Acts: " + "; ".join(dict.fromkeys(acts)))
    pets = parties.get("petitioner") or (
        [case["petitioner_summary"]] if case.get("petitioner_summary") else []
    )
    ress = parties.get("respondent") or (
        [case["respondent_summary"]] if case.get("respondent_summary") else []
    )
    if pets:
        lines.append("Petitioners: " + _cap_side(pets))
    if ress:
        lines.append("Respondents: " + _cap_side(ress))
    status = str(case.get("status") or "").replace("_", " ").strip()
    if status:
        disposal = (case.get("disposal_nature") or "").strip()
        lines.append(f"Status: {status.title()}" + (f" ({disposal})" if disposal else ""))
    if case.get("short_order") and str(case["short_order"]).strip():
        lines.append("Order: " + re.sub(r"\s+", " ", str(case["short_order"])).strip())
    seen: list[str] = []
    for so in short_orders:
        clean = re.sub(r"\s+", " ", so or "").strip()
        if clean and clean not in seen:
            seen.append(clean)
        if len(seen) >= SHEET_HEARINGS:
            break
    if seen:
        lines.append("Hearings: " + " | ".join(seen))
    text = "\n".join(lines)
    if len(text) > SHEET_MAX:
        cut = text.rfind(" ", 0, SHEET_MAX)
        text = text[: cut if cut > SHEET_MAX // 2 else SHEET_MAX].rstrip()
    return text


# ------------------------------------------------------------------------------------------------ the embedded input


def embed_input(profile: EmbedProfile, line: str, text: str) -> str:
    """Decision 12: the exact text sent to the model."""
    return f"{profile.doc_prefix}{line}\n{text}"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_sha256(profile: EmbedProfile, line: str, text: str) -> str:
    return sha256(embed_input(profile, line, text))


def query_input(profile: EmbedProfile, question: str) -> str:
    return f"{profile.query_prefix}{question}"


__all__ = [
    "CAP_MAX",
    "CHUNKER_VERSION",
    "CHUNK_MIN_CHARS",
    "EMBED_PROFILES",
    "ChunkSpec",
    "EmbedProfile",
    "cap_chars",
    "case_sheet_text",
    "chunk_reading",
    "context_line",
    "embed_input",
    "input_sha256",
    "profile_for",
    "query_input",
    "sha256",
    "split_long",
]
