"""The local-model Case Assistant's pure rules (design `assistant-ollama`, round 1, "Tests", unit): the state by mode
and environment, the cloud rule and preflight, the model-runtime guard, the import boundaries, the fixed prompt and
the drop order, the citation check, the client's error mapping, readiness and the slot, the health card and the
settings. Ollama is `FakeOllama`; nothing here reaches a network."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import re
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from aslms.core.config import Settings
from aslms.integration.ollama import ModelState, OllamaClient, cloud_host, model_name_ok, url_problem
from aslms.integration.ollama.client import model_state, parse_chat
from aslms.integration.sourcetrace import (
    AskRequest,
    AskScope,
    CaseContext,
    Citation,
    SourceTraceProtocolError,
    SourceTraceRejected,
    SourceTraceUnavailable,
    Turn,
)
from aslms.integration.sourcetrace.fake import FakeSourceTrace
from aslms.services import assistant as svc
from aslms.services import assistant_internal, preflight, service_checks
from aslms.services import assistant_ollama as ol
from aslms.services.assistant_preview import PreviewConnector
from tests.fakes.ollama import FakeOllama, chat_reply

ASLMS = Path(__file__).resolve().parents[2] / "aslms"
BACKEND = ASLMS.parent


def _settings(**over) -> Settings:
    return Settings(_env_file=None, **over)


# ------------------------------------------------------------------------------------------------ the state


def test_assistant_state_ollama_ready_in_every_env():
    for env in ("dev", "test", "prod"):
        s = _settings(assistant_mode="ollama", app_env=env)
        assert svc.assistant_state(s) == "ready" and svc.portal_mode(s) == "ollama"
        assert svc.banner(s) == svc.OLLAMA_BANNER
        conn = svc.assistant_connector(s, object())
        assert isinstance(conn, ol.OllamaConnector) and svc.mode_of(conn) == "ollama"
        assert not isinstance(conn, FakeSourceTrace)
    prod_preview = _settings(assistant_mode="preview", app_env="prod")
    assert svc.assistant_state(prod_preview) == "off"
    a = svc.assistant_connector(_settings(assistant_mode="ollama"), "factory")
    b = svc.assistant_connector(_settings(assistant_mode="ollama"), "factory")
    assert a is b  # one connector (its slots and readiness cache) per process
    assert isinstance(svc.assistant_connector(_settings(assistant_mode="preview"), None), PreviewConnector)


def test_cloud_model_and_cloud_host_refused(monkeypatch):
    monkeypatch.setitem(svc._warned, "cloud", False)
    for model in ("gpt-oss:20b-cloud", "qwen3:CLOUD", "deepseek-cloud/x:1", "bad name", ""):
        assert not model_name_ok(model), model
    for model in ("qwen3.5:4b", "llama3.2", "library/qwen3.5:4b-q4_K_M"):
        assert model_name_ok(model), model
    assert cloud_host("https://ollama.com") and cloud_host("https://api.ollama.com:443/x")
    assert not cloud_host("http://notollama.com") and not cloud_host("http://host.docker.internal:11434")
    assert url_problem("https://user:pw@10.0.0.5:11434") and url_problem("http://10.0.0.5:11434/?x=1")
    assert url_problem("ftp://10.0.0.5") and url_problem("http://ollama.com")
    assert url_problem("http://10.0.0.5:11434") is None
    for env in ("dev", "test", "prod"):
        for over in (
            {"assistant_ollama_model": "gpt-oss:20b-cloud"},
            {"assistant_ollama_url": "https://ollama.com"},
        ):
            s = _settings(assistant_mode="ollama", app_env=env, **over)
            assert svc.assistant_state(s) == "off" and svc.assistant_connector(s, None) is None
            findings = preflight.ollama_rules(s, resolve=lambda h: ["10.0.0.5"])
            assert [f.variable for f in findings] == ["no_cloud_model"]
            assert findings[0].level == preflight.FATAL
            with pytest.raises(preflight.PreflightFailed):
                preflight.raise_on_errors(findings, is_prod=False)


def test_preflight_ollama_url_rules():
    s = _settings(assistant_mode="ollama", app_env="prod")
    assert preflight.ollama_rules(s, resolve=lambda h: ["172.17.0.1"]) == []
    assert preflight.ollama_rules(s, resolve=lambda h: ["127.0.0.1", "::1"]) == []
    assert preflight.ollama_rules(s, resolve=lambda h: ["fd00::5", "169.254.1.1"]) == []
    public = preflight.ollama_rules(s, resolve=lambda h: ["8.8.8.8"])
    assert [(f.level, f.variable) for f in public] == [(preflight.ERROR, "ASSISTANT_OLLAMA_URL")]
    dev = preflight.ollama_rules(_settings(assistant_mode="ollama"), resolve=lambda h: ["8.8.8.8"])
    assert [f.level for f in dev] == [preflight.WARNING]
    unresolved = preflight.ollama_rules(s, resolve=lambda h: None)
    assert [(f.level, f.variable) for f in unresolved] == [(preflight.WARNING, "ASSISTANT_OLLAMA_URL")]
    slow = _settings(
        assistant_mode="ollama", assistant_timeout_seconds=20, assistant_ollama_timeout_seconds=30
    )
    assert [f.variable for f in preflight.ollama_rules(slow, resolve=lambda h: ["10.1.1.1"])] == [
        "ASSISTANT_OLLAMA_TIMEOUT_SECONDS"
    ]
    # the defaults give no Ollama finding, whatever the mode
    assert preflight.ollama_rules(_settings()) == []
    assert preflight.ollama_rules(_settings(assistant_mode="ollama"), resolve=lambda h: ["172.17.0.1"]) == []


def test_preflight_ollama_findings_carry_no_value():
    secretish = "gpt-oss:20b-cloud"
    s = _settings(
        assistant_mode="ollama",
        assistant_ollama_model=secretish,
        assistant_ollama_url="https://u:p@ollama.com/?k=v",
    )
    lines = " ".join(f.line() for f in preflight.ollama_rules(s, resolve=lambda h: ["8.8.8.8"]))
    for value in (secretish, "u:p", "ollama.com/?k", "k=v"):
        assert value not in lines
    s2 = _settings(assistant_mode="ollama", assistant_ollama_url="http://203.0.113.9:11434")
    lines2 = " ".join(f.line() for f in preflight.ollama_rules(s2, resolve=lambda h: ["203.0.113.9"]))
    assert "203.0.113.9" not in lines2


# ------------------------------------------------------------------------------------------------ no local model


def test_no_local_model_refuses_llm_runtimes():
    for name in (
        "llama-cpp-python",
        "llama_cpp_python",
        "torch",
        "transformers",
        "vllm",
        "gpt4all",
        "ctransformers",
    ):
        finding = preflight.no_local_model(names=[name], pymupdf_root=None)
        assert finding is not None and finding.level == preflight.FATAL
        assert finding.line().startswith(
            "fatal: no_local_model: a model runtime found in the installed distribution"
        )
    # the onnxruntime lines are unchanged
    onnx = preflight.no_local_model(names=["onnxruntime"], pymupdf_root=None)
    assert onnx.line() == "fatal: no_local_model: onnxruntime found in the installed distribution onnxruntime"
    assert preflight.runtime_distributions() == []
    assert preflight.no_local_model(names=["httpx", "sqlalchemy"], pymupdf_root=None) is None


def test_pyproject_has_no_model_library():
    text = (BACKEND / "pyproject.toml").read_text("utf-8").lower()
    deps = re.findall(r'^\s*"([a-z0-9_.\-]+)', text, re.M)
    for banned in ("ollama", "openai", "anthropic", "llama-cpp-python", "torch", "transformers"):
        assert banned not in deps, banned


# ------------------------------------------------------------------------------------------------ boundaries


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
    return out


def _full_imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def test_ollama_package_imports_only_stdlib_httpx_aslms():
    allowed = set(sys.stdlib_module_names) | {"httpx", "aslms", "__future__"}
    for path in (ASLMS / "integration" / "ollama").glob("*.py"):
        assert _imports(path) - allowed == set(), path.name


ALLOWED_CLIENT = {
    ("services", "assistant_ollama.py"),
    ("services", "service_checks.py"),
    ("cli", "assistant.py"),
}


def test_only_listed_modules_import_the_ollama_client():
    offenders = []
    for path in ASLMS.rglob("*.py"):
        rel = path.relative_to(ASLMS)
        if rel.parts[:2] == ("integration", "ollama"):
            continue
        if any(m.startswith("aslms.integration.ollama") for m in _full_imports(path)):
            if tuple(rel.parts[-2:]) not in ALLOWED_CLIENT:
                offenders.append(str(rel))
    assert offenders == []


def test_no_module_names_ollama_paths():
    offenders = []
    for path in ASLMS.rglob("*.py"):
        rel = path.relative_to(ASLMS)
        if rel.parts[:2] == ("integration", "ollama"):
            continue
        text = path.read_text("utf-8")
        if "/api/chat" in text or "/api/generate" in text:
            offenders.append(str(rel))
        if "11434" in text and rel.parts[-2:] != ("core", "config.py"):
            offenders.append(str(rel))
    assert offenders == []
    assert (
        "api_key"
        not in (ASLMS / "core" / "config.py").read_text("utf-8").split("assistant_ollama_url")[1][:2000]
    )


def test_assistant_internal_imports_no_connector_and_never_names_drafts():
    path = ASLMS / "services" / "assistant_internal.py"
    mods = _full_imports(path)
    assert not any(m.startswith(("aslms.integration.ollama", "aslms.integration.sourcetrace")) for m in mods)
    text = path.read_text("utf-8")
    assert "CaseNoteDraft" not in text and "case_note_draft" not in text


WRITE_SERVICES = (
    "aslms.services.stages",
    "aslms.services.ownership",
    "aslms.services.notes.add_note",
    "aslms.services.custody.send",
    "aslms.services.custody.recall",
    "aslms.services.custody.move_custody",
)


def test_assistant_modules_import_no_write_service():
    for name in (
        "assistant.py",
        "assistant_ollama.py",
        "assistant_internal.py",
        "assistant_sources.py",
        "assistant_preview.py",
    ):
        path = ASLMS / "services" / name
        mods = _full_imports(path)
        assert not any(m.startswith(WRITE_SERVICES) for m in mods), name
        text = path.read_text("utf-8")
        for call in (
            "custody.send(",
            "custody.recall(",
            "custody.move_custody(",
            "notes.add_note(",
            "stages.",
            "ownership.",
        ):
            assert call not in text, (name, call)


def test_contract_has_no_internal_field():
    assert [f.name for f in dataclasses.fields(AskRequest)] == ["request_id", "question", "scope", "history"]
    assert [f.name for f in dataclasses.fields(AskScope)] == [
        "kind",
        "focus",
        "orders",
        "filings",
        "truncated",
    ]


# ------------------------------------------------------------------------------------------------ the prompt


def _request(question="what was directed?", history=()) -> AskRequest:
    focus = CaseContext(
        case_id=uuid.uuid4(),
        cnr="ASHC010000012026",
        case_no_text="WP(C)/1/2026",
        filing_no_text=None,
        court="Gauhati High Court",
        bench=None,
        case_type="WP(C)",
        year=2026,
        status="pending",
    )
    return AskRequest(
        request_id=uuid.uuid4(),
        question=question,
        scope=AskScope(kind="case", focus=(focus,), orders="focus_and_related"),
        history=tuple(history),
    )


def _src(kind, header, body="text", drop=None, related=False, case_id=None, internal=False):
    return ol.Source(
        kind=kind,
        header=header,
        body=body,
        citation=Citation(reference=header, source_kind=kind, related=related),
        drop=drop,
        case_id=case_id,
        internal=internal,
    )


def _gathered(body_chars=10):
    focus_case = uuid.uuid4()
    other = uuid.uuid4()
    g = ol.Gathered()
    g.focus_details = _src(
        "case_details", "Case Details (Court Record), WP(C)/1/2026", "x" * body_chars, case_id=focus_case
    )
    g.court = [
        _src(
            "court_order",
            "Court Order (Court Record) focus high",
            "f" * body_chars,
            drop=(1, 0),
            case_id=focus_case,
        ),
        _src(
            "court_order",
            "Court Order (Court Record) focus low",
            "l" * body_chars,
            drop=(1, -1),
            case_id=focus_case,
        ),
        _src(
            "court_order",
            "Court Order (Court Record) related",
            "r" * body_chars,
            drop=(0, -2),
            related=True,
            case_id=other,
        ),
    ]
    g.details = {other: _src("case_details", "Case Details (Court Record), other", "d", case_id=other)}
    g.movement = _src(
        "file_movement", "File Movement (Internal), newest first", "m" * body_chars, internal=True
    )
    g.notes = [
        _src("note", "Note (Internal): Note 3", "n3" * body_chars, drop=(3, 3), internal=True),
        _src("note", "Note (Internal): Note 1 corrected", "n1" * body_chars, drop=(2, 0), internal=True),
        _src("note", "Note (Internal): Note 2", "n2" * body_chars, drop=(3, 2), internal=True),
    ]
    g.documents = [
        _src(
            "department_document",
            "Department Document (Internal), page 1",
            "p" * body_chars,
            drop=(4, 0),
            internal=True,
        )
    ]
    return g


def test_build_messages_fixed_prompt_and_labelled_kinds():
    msgs, sources, dropped = ol.build_messages(_request(), _gathered(), _settings(), history_turns=2)
    assert msgs[0] == {"role": "system", "content": ol.SYSTEM_PROMPT}
    assert ol.SYSTEM_PROMPT.startswith("You answer questions from officers of the Government of Assam")
    assert "reply exactly: The records found do not answer this question." in ol.SYSTEM_PROMPT
    assert "8. Reply in plain text without headings or tables, in at most 200 words." in ol.SYSTEM_PROMPT
    last = msgs[-1]["content"]
    assert last.startswith("Sources:\n[S1] Case Details (Court Record)") and last.endswith(
        "Question: what was directed?"
    )
    order = [s.kind for s in sources]
    assert order == [
        "case_details",
        "court_order",
        "court_order",
        "court_order",
        "case_details",
        "file_movement",
        "note",
        "note",
        "note",
        "department_document",
    ]
    assert [s.citation.related for s in sources[1:4]] == [False, False, True]  # focus, then related
    for i, s in enumerate(sources, start=1):
        assert f"[S{i}] {s.header}" in last
        assert ("(Internal)" in s.header) == s.internal and ("(Court Record)" in s.header) != s.internal
    assert dropped == {}
    details = ol.details_text(
        {
            "case_id": uuid.uuid4(),
            "cnr": "C",
            "case_no_text": "WP(C)/1/2026",
            "filing_no_text": None,
            "court": "GHC",
            "bench": None,
            "case_type": "WP(C)",
            "year": 2026,
            "status": "pending",
            "parties": ("A", "B"),
            "advocates": ("X",),
            "acts": (),
            "last_hearing_date": None,
            "next_hearing_date": None,
            "hearings": [],
            "listings": [],
        },
        compact=False,
    ).lower()
    for banned in ("owner", "stage", "custody", "recommend", "ref_no", "aslms/"):
        assert banned not in details


def test_build_messages_drop_order():
    g = _gathered(body_chars=6000)
    s = _settings(assistant_ollama_num_ctx=2048, assistant_ollama_num_predict=64)
    msgs, sources, dropped = ol.build_messages(_request(), g, s, history_turns=0)
    kinds = [x.kind for x in sources]
    assert "case_details" in kinds and "file_movement" in kinds  # never dropped
    assert dropped["court_order"] == 3 and dropped["note"] == 3 and dropped["department_document"] == 1
    # the order: related, then the low court passages, corrected notes, old notes, then document pages
    g2 = _gathered(body_chars=6000)
    seen = []
    while ol._droppable(g2):
        victim = ol._droppable(g2)[0]
        seen.append(victim.header)
        ol._drop(g2, victim)
    assert seen == [
        "Court Order (Court Record) related",
        "Court Order (Court Record) focus low",
        "Court Order (Court Record) focus high",
        "Note (Internal): Note 1 corrected",
        "Note (Internal): Note 2",
        "Note (Internal): Note 3",
        "Department Document (Internal), page 1",
    ]


def test_check_citations():
    text, cited, invalid = ol.check_citations("A [S2]. B [S1, S3]. C [S1; S9]. D [S1][S3]. E [s2 , 4].", 3)
    assert cited == {1, 2, 3} and invalid == 2
    assert "[S1][S3]" in text and "[S9]" not in text and "[S4]" not in text
    assert "C [S1]." in text
    text, cited, invalid = ol.check_citations("<think>secret plan [S1]</think>No marker here.", 2)
    assert text == "No marker here." and cited == set() and invalid == 0
    _t, cited, invalid = ol.check_citations("Only [S5].", 2)
    assert cited == set() and invalid == 1


def test_history_markers_removed_and_capped():
    history = [Turn(question=f"q{i}", answer=f"answer {i} [S1][S2].") for i in range(5)]
    msgs, _s, _d = ol.build_messages(_request(history=history), _gathered(), _settings(), history_turns=2)
    assert [m["content"] for m in msgs[1:-1]] == ["q3", "answer 3.", "q4", "answer 4."]
    assert [m["role"] for m in msgs[1:-1]] == ["user", "assistant", "user", "assistant"]
    msgs0, _s, _d = ol.build_messages(_request(history=history), _gathered(), _settings(), history_turns=0)
    assert len(msgs0) == 2


def test_chat_request_body():
    fake = FakeOllama()
    reply = asyncio.run(fake.client().chat({"model": "m", "messages": []}, timeout=2))
    assert reply.content.endswith("[S1].") and reply.done_reason == "stop" and reply.prompt_eval_count == 900
    assert fake.chats == [{"model": "m", "messages": []}]


def test_client_error_mapping():
    def run(step):
        fake = FakeOllama()
        fake.replies.append(step)
        return asyncio.run(fake.client().chat({"model": "m"}, timeout=2))

    for code in (500, 503, 404):
        with pytest.raises(SourceTraceUnavailable):
            run(httpx.Response(code, json={"error": "x"}))
    with pytest.raises(SourceTraceRejected):
        run(httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(SourceTraceProtocolError):
        run(httpx.Response(200, content=b"not json"))
    with pytest.raises(SourceTraceProtocolError):
        run({"message": {"role": "assistant"}, "done": True})
    with pytest.raises(SourceTraceProtocolError):
        run({**chat_reply("x"), "done": False})
    down = FakeOllama(reachable=False)
    with pytest.raises(SourceTraceUnavailable):
        asyncio.run(down.client().chat({"model": "m"}, timeout=2))
    assert down.client().state_sync("qwen3.5:4b").reason == "unreachable"
    with pytest.raises(SourceTraceProtocolError):
        parse_chat([1, 2])


def test_keep_alive_setting_values():
    for good in ("-1", "0", "300", "5m", "24h", "30s"):
        conn = ol.OllamaConnector(None, _settings(assistant_ollama_keep_alive=good))
        assert conn.keep_alive() == (int(good) if good.lstrip("-").isdigit() else good)
    for bad in ("forever", "5 m", "1d", ""):
        with pytest.raises(ValidationError):
            _settings(assistant_ollama_keep_alive=bad)


# ------------------------------------------------------------------------------------------------ readiness


def test_readiness_states_and_one_load_in_flight():
    fake = FakeOllama(loaded=False)
    conn = ol.OllamaConnector(None, _settings(assistant_mode="ollama"), client=fake.client())
    gate = threading.Event()
    real_load = fake.handle

    def slow(request):
        if request.url.path == "/api/generate":
            gate.wait(5)
        return real_load(request)

    conn.client = OllamaClient("http://ollama.test", transport=httpx.MockTransport(slow))
    r = conn.readiness()
    assert r.state == "loading" and r.reason == "not_loaded"
    assert conn.start_load() is False  # one at a time, and at most every 150 s
    conn._cache = None
    assert conn.readiness().state == "loading"
    gate.set()
    conn.load_thread.join(5)
    assert fake.loads == 1
    conn._cache = None
    assert conn.readiness().state == "ready"
    for kw, reason in (
        ({"held": False}, "missing"),
        ({"reachable": False}, "unreachable"),
        ({"size": 5000}, "not_local"),
    ):
        f = FakeOllama(loaded=False, **kw)
        c = ol.OllamaConnector(None, _settings(), client=f.client())
        r = c.readiness()
        assert (r.state, r.reason) == ("unavailable", reason)
        assert f.loads == 0


def test_admission_busy_after_wait():
    fake = FakeOllama()
    conn = ol.OllamaConnector(None, _settings(assistant_ollama_slot_wait_seconds=0.2), client=fake.client())
    slot = asyncio.run(conn.admission())
    started = time.monotonic()
    with pytest.raises(ol.ModelBusy):
        asyncio.run(conn.admission())
    assert 0.15 < time.monotonic() - started < 3
    slot.release()
    slot.release()  # idempotent
    asyncio.run(conn.admission()).release()
    fake.loaded = False
    conn._cache = None
    with pytest.raises(ol.ModelLoading):
        asyncio.run(conn.admission())
    fake.held = False
    conn._cache = None
    with pytest.raises(ol.ModelUnavailable):
        asyncio.run(conn.admission())


def test_model_state_from_answers():
    tags = {"models": [{"name": "qwen3.5:4b", "size": 3_000_000_000, "digest": "d"}]}
    ps = {"models": [{"name": "qwen3.5:4b", "size": 3_000_000_000, "size_vram": 1_000_000_000}]}
    st = model_state("qwen3.5:4b", {"version": "0.40.2"}, tags, ps)
    assert st.ready and st.version_ok and st.on_gpu == "partial"
    cloud = {"models": [{"name": "qwen3.5:4b", "size": 384, "remote_host": "https://ollama.com:443"}]}
    assert model_state("qwen3.5:4b", None, cloud, None).reason == "not_local"
    assert model_state("llama3", None, {"models": [{"name": "llama3:latest", "size": 10**9}]}, None).held


# ------------------------------------------------------------------------------------------------ the health card


def test_service_check_assistant_model_states():
    s = _settings(assistant_mode="ollama")
    ok = ModelState(
        True, "0.40.1", True, 3 * 10**9, True, True, 3 * 10**9, 3 * 10**9, "2318-01-01T00:00:00Z", "d"
    )
    check = service_checks.check_assistant_model(s, ok, None, 5)
    assert check.status == "ok" and check.to_dict()["label"] == "Case Assistant Model"
    facts = {f["label"]: f["value"] for f in check.facts}
    assert (
        facts["Loaded"] == "Yes"
        and facts["On GPU"] == "Fully"
        and facts["Kept Loaded Until"] == "while the server runs"
    )
    assert "host.docker.internal" not in str(check.to_dict())
    cases = [
        (dataclasses.replace(ok, loaded=False, size=None, size_vram=None), "warn"),
        (dataclasses.replace(ok, version="0.39.0"), "warn"),
        (dataclasses.replace(ok, size_vram=10**9), "warn"),
        (ModelState(False, reason="unreachable"), "down"),
        (ModelState(True, "0.40.1", reason="missing"), "down"),
        (dataclasses.replace(ok, local=False, reason="not_local"), "down"),
    ]
    for state, want in cases:
        assert service_checks.check_assistant_model(s, state, None, 1).status == want, state
    assert service_checks.check_assistant_model(s, None, "ConnectError", 1).status == "down"
    cloud = _settings(assistant_mode="ollama", assistant_ollama_model="x:cloud")
    assert service_checks.check_assistant_model(cloud, ok, None, 1).status == "down"


def test_settings_defaults_and_bounds():
    s = _settings()
    assert s.assistant_mode == "off"
    assert (s.assistant_ollama_url, s.assistant_ollama_model) == (
        "http://host.docker.internal:11434",
        "qwen3.5:4b",
    )
    assert (s.assistant_ollama_num_ctx, s.assistant_ollama_num_predict, s.assistant_ollama_keep_alive) == (
        16384,
        800,
        "-1",
    )
    assert (
        s.assistant_ollama_timeout_seconds,
        s.assistant_ollama_slots,
        s.assistant_ollama_slot_wait_seconds,
    ) == (30, 1, 20)
    assert (
        s.assistant_ollama_sources,
        s.assistant_ollama_source_chars,
        s.assistant_ollama_history_turns,
    ) == (6, 4000, 2)
    assert (s.assistant_ollama_internal_chars, s.assistant_ollama_hearings) == (12000, 10)
    for name, bad in (
        ("assistant_ollama_num_ctx", 1024),
        ("assistant_ollama_num_ctx", 200_000),
        ("assistant_ollama_num_predict", 10),
        ("assistant_ollama_timeout_seconds", 0),
        ("assistant_ollama_slots", 9),
        ("assistant_ollama_slot_wait_seconds", 61),
        ("assistant_ollama_sources", 13),
        ("assistant_ollama_source_chars", 100),
        ("assistant_ollama_history_turns", 7),
        ("assistant_ollama_internal_chars", 30_001),
        ("assistant_ollama_hearings", 51),
        ("assistant_mode", "cloud"),
    ):
        with pytest.raises(ValidationError):
            _settings(**{name: bad})
    conn = ol.OllamaConnector(None, _settings(assistant_timeout_seconds=45))
    assert conn.model_seconds == 30 and conn.search_seconds == 13


def test_suggest_words():
    assert assistant_internal.suggests("Who has the file?")
    assert assistant_internal.suggests("what did we decided") or assistant_internal.suggests(
        "what we decided"
    )
    assert assistant_internal.suggests("Any pending action?") and assistant_internal.suggests("our notes")
    assert not assistant_internal.suggests("what did the court direct on 12 March")
