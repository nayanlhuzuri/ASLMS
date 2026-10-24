"""No local model (CLAUDE.md: all AI goes through SourceTrace; design `followups-oct`, decisions 24 and 25): no
installed distribution brings an onnxruntime, the installed PyMuPDF carries no runtime linked into its native code,
opening and reading a PDF initialises none, and preflight stops the start at every APP_ENV when one arrives."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from aslms.core.config import Settings
from aslms.services import preflight

SAMPLE_PDF = Path(__file__).resolve().parents[3] / "docs" / "specs" / "samples" / "order_2026-09-03.pdf"


def test_no_model_distribution_is_installed():
    assert preflight.model_distributions() == []
    # the name rules themselves
    assert preflight.model_distributions(["onnxruntime-gpu", "PyMuPDF_Layout", "pymupdf4llm", "PyMuPDF"]) == [
        "onnxruntime-gpu",
        "pymupdf-layout",
        "pymupdf4llm",
    ]


def test_no_runtime_bytes_in_the_installed_pymupdf():
    root = preflight._pymupdf_dir()
    assert root is not None and root.is_dir()
    assert any(p.suffix in (".pyd", ".so", ".dll") or ".so." in p.name for p in root.rglob("*")), (
        "the scan covers the native libraries"
    )
    assert preflight.file_with_marker(root) is None


def test_opening_a_pdf_initialises_no_onnxruntime():
    """Text and tables of a stored-style PDF in a fresh process, with C-level stderr (fd 2) captured."""
    code = textwrap.dedent(
        f"""
        import os, sys, tempfile
        err = tempfile.TemporaryFile()
        saved = os.dup(2)
        os.dup2(err.fileno(), 2)
        import pymupdf
        doc = pymupdf.open({str(SAMPLE_PDF)!r})
        chars = 0
        for page in doc:
            chars += len(page.get_text("text"))
            page.find_tables()
        os.dup2(saved, 2)
        err.seek(0)
        captured = err.read().decode("utf-8", "replace")
        maps = ""
        if sys.platform.startswith("linux"):
            with open("/proc/self/maps") as fh:
                maps = fh.read()
        print(chars > 0, "onnxruntime" in captured.lower(), "onnxruntime" in sys.modules, "onnxruntime" in maps)
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=180, check=True
    )
    read, in_stderr, in_modules, in_maps = out.stdout.split()[-4:]
    assert read == "True", "the PDF was read"
    assert (in_stderr, in_modules, in_maps) == ("False", "False", "False"), out.stderr[-500:]
    assert "onnxruntime" not in out.stderr.lower()


def test_preflight_is_fatal_when_a_fake_onnxruntime_is_installed(tmp_path, monkeypatch):
    dist = tmp_path / "onnxruntime-1.20.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: onnxruntime\nVersion: 1.20.0\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    finding = preflight.no_local_model()
    assert finding is not None and finding.level == preflight.FATAL
    assert (
        finding.line() == "fatal: no_local_model: onnxruntime found in the installed distribution onnxruntime"
    )
    for env in ("dev", "test", "prod"):
        findings = preflight.check(Settings(_env_file=None, app_env=env))
        assert any(f.variable == "no_local_model" and f.level == preflight.FATAL for f in findings), env
        assert preflight.errors(findings), env


def test_preflight_names_the_file_with_the_marker(tmp_path):
    lib = tmp_path / "pymupdf"
    lib.mkdir()
    (lib / "clean.so").write_bytes(b"\x7fELF" + b"\x00" * (2 << 20))
    (lib / "linked.so").write_bytes(b"\x00" * ((1 << 20) - 3) + b"OrtGetApiBase")  # across a chunk boundary
    finding = preflight.no_local_model(names=[], pymupdf_root=lib)
    assert finding is not None and finding.message == f"onnxruntime found in {lib / 'linked.so'}"
    assert preflight.no_local_model(names=[], pymupdf_root=tmp_path / "absent") is None
