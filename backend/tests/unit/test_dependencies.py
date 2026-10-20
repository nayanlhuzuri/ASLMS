"""Dependencies that must stay as approved (design `document-ocr`, decision 2): PyMuPDF is pinned below 2, because
2.x opens bundled onnxruntime layout models at import, an unapproved local neural network the portal does not use
(text extraction needs only `page.get_text("text")`)."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_pymupdf_loads_no_neural_runtime():
    code = "import sys, pymupdf; print(pymupdf.VersionBind); print('onnxruntime' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True
    )
    version, loaded = out.stdout.split()[-2:]
    assert version.startswith("1."), version
    assert loaded == "False"


def test_pyproject_pins_pymupdf_below_2():
    deps = tomllib.loads(PYPROJECT.read_text("utf-8"))["project"]["dependencies"]
    pymupdf = [d for d in deps if d.lower().startswith("pymupdf")]
    assert pymupdf == ["pymupdf>=1.24,<2"]
