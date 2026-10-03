"""PostToolUse: lint and format a Python file under backend/ right after it is written or edited."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return
    inp = payload.get("tool_input") or {}
    path = str(inp.get("file_path") or "")
    norm = path.replace("\\", "/")
    if not norm.endswith(".py") or "/backend/" not in norm or not os.path.exists(path):
        return
    root = norm.split("/backend/", 1)[0] + "/backend"
    ruff = os.path.join(root, ".venv", "Scripts", "ruff.exe")
    if not os.path.exists(ruff):
        ruff = os.path.join(root, ".venv", "bin", "ruff")
    if not os.path.exists(ruff):
        return
    for args in (["check", "--fix", "--quiet", path], ["format", "--quiet", path]):
        subprocess.run([ruff, *args], cwd=root, capture_output=True, timeout=60, check=False)


if __name__ == "__main__":
    main()
