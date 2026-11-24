"""Guards and pure helpers of the research index (design `research-index`, "Tests", unit): the modules that may call
Ollama and where `/api/embed` appears, no vector or model library in the lock, the research readers touch only court
tables, the pgvector pin is the same in the image and CI, the scheduler reaches the host's Ollama, the fusion, the
weights and the grouping, small-to-big reading, the filters, the prompt version 3 and the settings. No database."""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from aslms.core.config import Settings
from aslms.services import assistant_ollama as ol
from aslms.services import research_search as rsearch

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
ASLMS = BACKEND / "aslms"

ALLOWED_CLIENT = {
    ("services", "assistant_ollama.py"),
    ("services", "service_checks.py"),
    ("cli", "assistant.py"),
    ("services", "research_embed.py"),
    ("services", "research_search.py"),
    ("cli", "research.py"),
}


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_only_listed_modules_import_the_ollama_client():
    offenders = []
    for path in ASLMS.rglob("*.py"):
        rel = path.relative_to(ASLMS)
        if rel.parts[:2] == ("integration", "ollama"):
            continue
        if any(m.startswith("aslms.integration.ollama") for m in _imports(path)):
            if tuple(rel.parts[-2:]) not in ALLOWED_CLIENT:
                offenders.append(str(rel))
    assert offenders == []


def test_api_embed_only_in_client():
    offenders = [
        str(p.relative_to(ASLMS))
        for p in ASLMS.rglob("*.py")
        if "/api/embed" in p.read_text("utf-8")
        and p.relative_to(ASLMS).parts[:2] != ("integration", "ollama")
    ]
    assert offenders == []


def test_no_vector_or_model_library_in_lock():
    lock = (BACKEND / "uv.lock").read_text("utf-8").lower()
    names = set(re.findall(r'^name = "([a-z0-9_.\-]+)"', lock, re.M))
    for banned in ("numpy", "pgvector", "sentence-transformers", "torch", "transformers", "ollama"):
        assert banned not in names, banned
    deps = (BACKEND / "pyproject.toml").read_text("utf-8").lower()
    assert "pgvector" not in deps and "numpy" not in deps


# ------------------------------------------------------------------------------------------------ court tables only

COURT_TABLES = {
    "order_sections",
    "orders",
    "documents",
    "document_text",
    "cases",
    "case_parties",
    "case_acts",
    "case_hearings",
    "courts",
    "research_chunks",
    "research_embeddings",
    "source_failures",
    "job_runs",
    "audit_log",
}
RESEARCH_MODULES = ("research_chunks.py", "research_index.py", "research_embed.py", "research_search.py")
TABLE_RE = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([a-z_][a-z0-9_]*)", re.I)
BANNED_IMPORTS = (
    "aslms.services.assistant_internal",
    "aslms.domain.workflow",
    "aslms.services.custody",
    "aslms.services.notes",
)


def test_research_readers_touch_only_court_tables():
    """Decision 2: the research modules' SQL names only court tables (and their own derived tables, the failure and
    job logs and the audit row of the rebuild); they never import the notes, custody or internal-records modules."""
    for name in RESEARCH_MODULES:
        path = ASLMS / "services" / name
        src = path.read_text("utf-8")
        sql = "\n".join(
            n.value
            for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        )
        tables = {t.lower() for t in TABLE_RE.findall(sql)}
        tables -= {"unnest", "string_to_table", "the", "a", "an", "it", "every", "this", "one", "each"}
        tables = {t for t in tables if "_" in t or t in COURT_TABLES}
        assert tables <= COURT_TABLES, (name, tables - COURT_TABLES)
        for banned in (
            "case_notes",
            "custody",
            "case_note_drafts",
            "case_note_attachments",
            "assistant_messages",
        ):
            assert banned not in tables, (name, banned)
        mods = _imports(path)
        assert not any(m.startswith(BANNED_IMPORTS) for m in mods), (name, mods)


def test_pgvector_pin_same_in_dockerfile_and_ci():
    docker = (ROOT / "infra" / "postgres" / "Dockerfile").read_text("utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    pin = re.search(r"PGVECTOR_VERSION=(\S+)", docker).group(1)
    ci_pin = re.search(r"PGVECTOR_VERSION:\s*(\S+)", ci).group(1)
    assert pin == ci_pin == "0.8.7-1.pgdg13+1"  # +2 needs postgresql-16 >> 16.16 (Deviations 14)
    assert "dpkg-query -W -f=" in docker and 'postgresql-16)" = "${PG_VERSION}"' in docker
    assert docker.splitlines()[
        [i for i, line in enumerate(docker.splitlines()) if line.startswith("FROM")][0]
    ] == ("FROM postgres:16.15")
    assert "postgres:16.15" in ci


def test_scheduler_has_host_gateway():
    compose = (ROOT / "compose.yml").read_text("utf-8")
    block = compose.split("\n  scheduler:\n", 1)[1].split("\n  web:\n", 1)[0]
    assert "host.docker.internal:host-gateway" in block
    postgres = compose.split("\n  postgres:\n", 1)[1].split("\n  redis:\n", 1)[0]
    assert "./infra/postgres" in postgres and "aslms/postgres:16.15-pgvector0.8.7" in postgres


# ------------------------------------------------------------------------------------------------ fusion and passages


def test_rrf_fuse():
    fused = rsearch.fuse({"words": ["a", "b", "c"], "meaning": ["d", "b"]})
    items = [i for i, _s, _l in fused]
    assert items[0] == "b"  # on both lists beats first on one
    score = {i: s for i, s, _l in fused}
    assert score["b"] == pytest.approx(1 / 62 + 1 / 62)
    assert score["a"] == pytest.approx(1 / 61) and score["d"] == pytest.approx(1 / 61)
    assert rsearch.RRF_K == 60
    assert {i: ls for i, _s, ls in fused}["b"] == {"words", "meaning"}
    assert rsearch.match_of({"words", "meaning"}) == "both" and rsearch.match_of({"meaning"}) == "meaning"


def test_weights_and_grouping():
    assert rsearch.weight("interim", True) == 0.5
    assert rsearch.weight("judgment", False) == rsearch.weight("final", False) == 1.2
    assert rsearch.weight("interim", False) == 1.0
    assert rsearch.PASSAGES_PER_ORDER == 2


def _chunk(seq, part, a, b):
    return SimpleNamespace(
        seq=seq, part=part, para_first=a, para_last=b, chunker_version=1, text=f"chunk {seq}"
    )


def test_grouping_joins_adjacent_and_caps_two_per_order(monkeypatch):
    order = uuid.uuid4()
    reading = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(5)]
    chunks = {
        ids[0]: _chunk(0, "reasoning", 0, 1),
        ids[1]: _chunk(1, "reasoning", 2, 3),  # adjacent to the first: joined
        ids[2]: _chunk(4, "conclusion", 7, 7),
        ids[3]: _chunk(6, "facts", 10, 10),
        ids[4]: _chunk(8, "issues", 12, 12),  # a third passage of the order: left out
    }
    holder = rsearch.Holder(ids[0], reading, order, uuid.uuid4(), uuid.uuid4(), "judgment", False, None, 0)
    holders = {c: rsearch.Holder(c, reading, order, holder.document_id, holder.case_id, "judgment", False, None, 0)
               for c in ids}  # fmt: skip
    paras = [{"i": i, "label": f"{i + 1}.", "page": 1 + i // 5, "page_to": 1 + i // 5, "src": [i * 10, i * 10 + 9],
              "txt": [i * 10, i * 10 + 9], "part": "reasoning" if i < 4 else "conclusion"} for i in range(14)]  # fmt: skip
    row = SimpleNamespace(
        id=reading,
        body_text="x" * 200,
        paragraphs=paras,
        pdf_sha256="p",
        text_sha256="t",
        parser_version=2,
        form="judgment",
        order_date=None,
        order_no="1",
        order_judge_name=None,
        case_no_text="WP(C)/1/2025",
        cnr=None,
        coram=None,
        case_type_text=None,
        category=None,
        sub_category=None,
    )
    monkeypatch.setattr(rsearch, "_reading_rows", lambda s, b, ids_: {reading: row})
    ranked = [(c, 1.0 / (60 + n), {"words"}) for n, c in enumerate(ids, start=1)]
    out = rsearch._order_passages(None, None, ranked, holders, chunks, None, 4000, False)
    passages = list(out.values())
    assert len(passages) == 2
    first = passages[0]
    assert first.chunk_ids == [ids[0], ids[1]] and (first.para_first, first.para_last) == (0, 3)
    assert first.src == (0, 39) and first.page == 1
    assert first.context_line.startswith("WP(C)/1/2025 · Judgment · Reasoning · paragraphs 1. to 4.") or (
        "Judgment · Reasoning" in first.context_line
    )


def test_small_to_big_stays_in_part():
    body = "".join(f"P{i:02d}......\n\n" for i in range(8))  # 12 characters a paragraph
    paras = [
        {"i": i, "txt": [i * 12, i * 12 + 10], "part": "facts" if i < 3 else "reasoning", "page": 1}
        for i in range(8)
    ]
    text, lo, hi = rsearch.small_to_big(paras, body, 4, 4, "reasoning", 40)
    assert (lo, hi) == (3, 5) or (lo, hi) == (4, 6)
    assert "P04" in text and "P02" not in text  # never the facts part
    text, lo, hi = rsearch.small_to_big(paras, body, 3, 3, "reasoning", 1000)
    assert (lo, hi) == (3, 7) and "P02" not in text


def test_filters_parse_and_store():
    f = rsearch.parse_filters(
        {"forms": ["judgment"], "outcomes": ["dismissed"], "cites": " (2006)  4 SCC 1 "}
    )
    assert f.cites == "(2006) 4 SCC 1" and f.any
    assert f.stored() == {"forms": ["judgment"], "outcomes": ["dismissed"], "cites": "(2006) 4 SCC 1"}
    for bad in ({"outcomes": ["won"]}, {"forms": ["order"]}, {"cites": "x" * 81}):
        with pytest.raises(rsearch.BadFilter):
            rsearch.parse_filters(bad)
    from datetime import date

    with pytest.raises(rsearch.BadFilter):
        rsearch.parse_filters({"from": date(2025, 2, 1), "to": date(2025, 1, 1)})
    assert not rsearch.parse_filters(None).any


# ------------------------------------------------------------------------------------------------ prompt and settings


def test_prompt_version_3_rules():
    assert ol.PROMPT_VERSION == 3
    lines = ol.SYSTEM_PROMPT.split("\n")
    assert lines[-2:] == [
        "9. Put the direct answer in the first sentence.",
        "10. When you quote, copy the words exactly and put them in double quotes.",
    ]
    assert any(line.startswith("1. End every sentence that states a fact") for line in lines)


def test_research_settings_defaults():
    s = Settings(_env_file=None)
    assert s.research_index_enabled is False
    assert s.research_embed_model == "embeddinggemma:300m"
    assert (s.research_embed_batch, s.research_job_seconds, s.research_query_embed_seconds) == (16, 60, 5.0)
    assert (s.research_candidates, s.research_exact_max, s.research_ef_search) == (100, 20_000, 100)
    assert s.research_embed_keep_alive == "-1" and s.research_embed_on_cpu is False
    env = (ROOT / ".env.example").read_text("utf-8")
    for var in (
        "RESEARCH_INDEX_ENABLED",
        "RESEARCH_EMBED_MODEL",
        "RESEARCH_EMBED_KEEP_ALIVE",
        "RESEARCH_EMBED_ON_CPU",
        "RESEARCH_EMBED_BATCH",
        "RESEARCH_JOB_SECONDS",
        "RESEARCH_QUERY_EMBED_SECONDS",
        "RESEARCH_CANDIDATES",
        "RESEARCH_EXACT_MAX",
        "RESEARCH_EF_SEARCH",
    ):
        assert f"\n{var}=" in env, var


def test_no_cloud_embed_model():
    from aslms.services import preflight

    bad = Settings(_env_file=None, research_embed_model="embeddinggemma:300m-cloud")
    found = preflight.ollama_rules(bad)
    assert any(f.variable == "no_cloud_model" and "RESEARCH_EMBED_MODEL" in f.message for f in found)
    assert all(
        "cloud" not in f.message.split("RESEARCH_EMBED_MODEL")[0]
        for f in found
        if f.variable == "no_cloud_model"
    )
    warn = preflight.ollama_rules(Settings(_env_file=None, research_index_enabled=True, assistant_mode="off"))
    assert any(f.variable == "research_index_mode" for f in warn)
