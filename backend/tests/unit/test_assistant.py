"""The Case Assistant's pure rules (design `assistant`, "Tests", unit): the state by mode and environment, the
preflight rule, the preview's imports and fixed text, the fake's query side, the court-public `CaseContext`, and the
split of the ingestion nature rule."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.dialects import postgresql

from aslms.core.config import Settings
from aslms.domain.documents import DocGroup, DocKind, Document, Order, ScanStatus, Visibility
from aslms.integration.sourcetrace import (
    Answer,
    AskRequest,
    AskScope,
    CaseContext,
    Citation,
    FilingRef,
    SourceTraceRejected,
    SourceTraceUnavailable,
)
from aslms.integration.sourcetrace.fake import OUT_OF_SCOPE_REF, FakeSourceTrace
from aslms.services import assistant as svc
from aslms.services import preflight
from aslms.services import sourcetrace_ingest as st
from aslms.services.assistant_preview import NO_MATCH_LINE, PREVIEW_LINE, PreviewConnector, answer_text

ASLMS = Path(__file__).resolve().parents[2] / "aslms"


def _settings(**over) -> Settings:
    return Settings(_env_file=None, **over)


# ------------------------------------------------------------------------------------------------ the switch


def test_assistant_state_by_mode_and_env():
    off = _settings(assistant_mode="off")
    assert svc.assistant_state(off) == "off" and svc.assistant_connector(off, None) is None
    for env in ("dev", "test"):
        s = _settings(assistant_mode="preview", app_env=env)
        assert svc.assistant_state(s) == "preview"
        assert isinstance(svc.assistant_connector(s, None), PreviewConnector)
        assert svc.portal_mode(s) == "preview"
        assert svc.banner(s) == svc.PREVIEW_BANNER
    prod = _settings(assistant_mode="preview", app_env="prod")
    assert svc.assistant_state(prod) == "off" and svc.assistant_connector(prod, None) is None
    assert svc.portal_mode(prod) == "off"
    for enabled in (False, True):
        s = _settings(assistant_mode="sourcetrace", sourcetrace_enabled=enabled)
        assert svc.assistant_state(s) == "not_implemented"
        assert svc.assistant_connector(s, None) is None
        assert svc.portal_mode(s) == "off" and svc.banner(s) is None
    for s in (off, prod, _settings(assistant_mode="sourcetrace", sourcetrace_enabled=True)):
        assert not isinstance(svc.assistant_connector(s, None), FakeSourceTrace)


def test_preview_in_prod_warns_once(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(svc.log, "warning", lambda msg, *a: warnings.append(msg % a if a else msg))
    monkeypatch.setitem(svc._warned, "prod_preview", False)
    prod = _settings(assistant_mode="preview", app_env="prod")
    svc.assistant_state(prod)
    svc.assistant_state(prod)
    assert len(warnings) == 1 and "ASSISTANT_MODE=preview" in warnings[0]


def test_preflight_refuses_preview_in_prod():
    findings = preflight.assistant_rules(_settings(assistant_mode="preview", app_env="prod"))
    assert [(f.level, f.variable) for f in findings] == [(preflight.ERROR, "ASSISTANT_MODE")]
    with pytest.raises(preflight.PreflightFailed):
        preflight.raise_on_errors(findings, True)
    assert preflight.assistant_rules(_settings(assistant_mode="preview", app_env="dev")) == []
    assert preflight.assistant_rules(_settings(assistant_mode="off", app_env="prod")) == []
    # the full check carries it too
    full = preflight.check(_settings(assistant_mode="preview", app_env="prod"))
    assert any(f.variable == "ASSISTANT_MODE" and f.level == preflight.ERROR for f in full)


def test_preflight_warns_sourcetrace_not_ready():
    for env in ("dev", "prod"):
        findings = preflight.assistant_rules(
            _settings(assistant_mode="sourcetrace", sourcetrace_enabled=True, app_env=env)
        )
        assert [(f.level, f.variable) for f in findings] == [(preflight.WARNING, "ASSISTANT_MODE")]


def test_settings_bounds():
    s = _settings()
    assert s.assistant_mode == "off" and s.assistant_questions_per_hour == 30
    assert s.assistant_question_max_chars == 2000 and s.assistant_preview_sql_ms == 8000
    with pytest.raises(ValueError):
        _settings(assistant_mode="cloud")
    with pytest.raises(ValueError):
        _settings(assistant_questions_per_hour=0)
    with pytest.raises(ValueError):
        _settings(assistant_question_max_chars=5000)


# ------------------------------------------------------------------------------------------------ the preview


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_preview_imports_no_model_library():
    allowed = set(sys.stdlib_module_names) | {"sqlalchemy", "aslms", "__future__"}
    found = _imports(ASLMS / "services" / "assistant_preview.py")
    assert found - allowed == set(), found - allowed
    # and the modules it pulls in from aslms are the eligibility rule, the connector contract and the models
    text = (ASLMS / "services" / "assistant_preview.py").read_text(encoding="utf-8")
    for banned in (
        "openai",
        "anthropic",
        "transformers",
        "torch",
        "sentence_transformers",
        "llama",
        "ollama",
    ):
        assert banned not in text.lower()


def test_preview_answer_text_is_the_fixed_template():
    assert answer_text(0, 0, "all") == f"{PREVIEW_LINE}\n{NO_MATCH_LINE}"
    assert answer_text(3, 2, "all") == (
        f"{PREVIEW_LINE}\n3 passages from 2 documents matched all of the words of your question."
    )
    assert answer_text(1, 1, "any") == (
        f"{PREVIEW_LINE}\n1 passage from 1 document matched any of the words of your question."
    )
    assert PREVIEW_LINE == "Preview: passages found in the court records, not an AI answer."


# ------------------------------------------------------------------------------------------------ the contract


def _request(*, filings=(), question="what did the court direct") -> AskRequest:
    return AskRequest(
        request_id=uuid.uuid4(),
        question=question,
        scope=AskScope(kind="case", focus=(), orders="focus", filings=tuple(filings)),
    )


def test_fake_ask_records_and_follows_its_script():
    scripted = Answer(text="scripted", citations=(Citation(reference="ref-1"),))
    fake = FakeSourceTrace(timeout_sleep=0.2, cite="ref-order").script_ask(
        "unavailable", "rejected", "bad_answer", "out_of_scope", scripted, "timeout"
    )
    filing = FilingRef(document_id=uuid.uuid4(), reference="ref-filing")

    async def go():
        out = []
        for _ in range(2):
            try:
                await fake.ask(_request())
            except (SourceTraceUnavailable, SourceTraceRejected) as exc:
                out.append(type(exc).__name__)
        out.append(await fake.ask(_request()))
        out.append(await fake.ask(_request()))
        out.append(await fake.ask(_request()))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(fake.ask(_request()), timeout=0.01)
        out.append(await fake.ask(_request(filings=[filing])))
        out.append(await fake.ask(_request()))
        return out

    out = asyncio.run(go())
    assert out[:2] == ["SourceTraceUnavailable", "SourceTraceRejected"]
    assert out[2] == {"text": None}
    assert [c.reference for c in out[3].citations] == [OUT_OF_SCOPE_REF]
    assert out[4] is scripted
    assert [c.reference for c in out[5].citations] == ["ref-filing"]  # the first filing by default
    assert [c.reference for c in out[6].citations] == ["ref-order"]  # else the given reference
    assert len(fake.asked) == 8
    with pytest.raises(ValueError):
        fake.script_ask("nonsense")


def test_case_context_has_only_court_public_fields():
    names = {f.name for f in dataclasses.fields(CaseContext)}
    assert names == {
        "case_id",
        "cnr",
        "case_no_text",
        "filing_no_text",
        "court",
        "bench",
        "case_type",
        "year",
        "status",
        "parties",
        "advocates",
        "acts",
        "last_hearing_date",
        "next_hearing_date",
    }
    for banned in ("owner", "office", "custody", "stage", "note", "ref_no", "recommend", "remark", "user"):
        assert not any(banned in n for n in names), banned
    scope_names = {f.name for f in dataclasses.fields(AskScope)}
    assert scope_names == {"kind", "focus", "orders", "filings", "truncated"}
    request_names = {f.name for f in dataclasses.fields(AskRequest)}
    assert request_names == {"request_id", "question", "scope", "history"}


def _old_nature_condition():
    """The rule as written before the split (design sourcetrace-connector, decision 3)."""
    return and_(
        or_(
            and_(
                Document.kind == DocKind.ORDER,
                Document.doc_group == DocGroup.COURT_RECORD,
                Document.virus_scan_status == ScanStatus.SKIPPED,
                exists(select(Order.id).where(Order.document_id == Document.id)),
            ),
            and_(
                Document.kind == DocKind.UPLOAD,
                Document.doc_group == DocGroup.COURT_FILING,
                Document.virus_scan_status == ScanStatus.CLEAN,
            ),
        ),
        Document.visibility != Visibility.PRIVATE_TO_OFFICE,
    )


def _sql(expr) -> str:
    stmt = select(Document.id).where(expr)
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_nature_condition_split_is_unchanged():
    assert _sql(st.nature_condition()) == _sql(_old_nature_condition())


def test_failure_messages_cover_every_family():
    assert set(svc.FAILURE_MESSAGES) == {"unavailable", "rejected", "protocol", "scope", "error"}
    assert svc.WITHHELD == "The answer drew on material outside your reach and was withheld."
