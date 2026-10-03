"""Print the text of a .docx (the plan) so agents can read it: `python tools/docx_text.py <file> [--grep WORD]
[--section "5.7"]`. Paragraphs and table cells, in document order; no dependency beyond the standard library."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def paragraphs(path: Path) -> list[str]:
    xml = zipfile.ZipFile(path).read("word/document.xml")
    root = ET.fromstring(xml)
    out: list[str] = []
    for p in root.iter(f"{W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if text:
            out.append(text)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--grep", help="only paragraphs containing this (case-insensitive)")
    ap.add_argument(
        "--section",
        help="from the paragraph starting with this heading number to the next heading of the same depth",
    )
    args = ap.parse_args()
    paras = paragraphs(args.file)
    if args.section:
        depth = args.section.count(".")
        start = next(
            (i for i, p in enumerate(paras) if p.startswith(args.section + " ") or p == args.section), None
        )
        if start is None:
            print(f"no section {args.section}", file=sys.stderr)
            return 1
        head = re.compile(r"^\d+(\.\d+){" + str(depth) + "} ")
        end = next((i for i in range(start + 1, len(paras)) if head.match(paras[i])), len(paras))
        paras = paras[start:end]
    if args.grep:
        paras = [p for p in paras if args.grep.lower() in p.lower()]
    sys.stdout.reconfigure(errors="backslashreplace")
    print("\n".join(paras))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
