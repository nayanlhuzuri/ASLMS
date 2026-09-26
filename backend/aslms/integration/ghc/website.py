"""Cause-list PDFs from disk (CAUSE_LIST_DIR/DD-MM-YYYY/*.pdf) and from the GHC website (supplementary source).

The website URL template is not verified yet (decisions log, open items), so the website source is disabled
unless GHC_CAUSELIST_URL_TEMPLATE is set, e.g. `https://ghconline.gov.in/.../{list_type}_{dd}-{mm}-{yyyy}.pdf`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from aslms.core.config import get_settings
from aslms.core.errors import SourceNotFound, SourceUnavailable
from aslms.core.logging import get_logger

log = get_logger(__name__)
SKIP = re.compile(r"notice|roster|sitting|swearing|circular", re.I)


@dataclass(frozen=True)
class PdfRef:
    list_date: date
    name: str
    location: str  # path or URL


class LocalDirSource:
    name = "local_dir"

    def __init__(self, root: Path | None = None):
        self.root = Path(root or get_settings().cause_list_dir)

    def available_dates(self) -> list[date]:
        out = []
        if not self.root.exists():
            return out
        for d in self.root.iterdir():
            m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", d.name)
            if d.is_dir() and m:
                try:
                    out.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
                except ValueError:
                    continue
        return sorted(out)

    def list(self, list_date: date) -> list[PdfRef]:
        folder = self.root / list_date.strftime("%d-%m-%Y")
        if not folder.is_dir():
            return []
        return [
            PdfRef(list_date, p.name, str(p)) for p in sorted(folder.glob("*.pdf")) if not SKIP.search(p.name)
        ]

    def fetch(self, ref: PdfRef) -> bytes:
        return Path(ref.location).read_bytes()


class WebsiteSource:
    name = "ghc_website"
    LIST_TYPES = ("Daily", "Supplementary", "Lawazima")

    def __init__(self, template: str | None = None, timeout: float = 30.0):
        self.template = template or getattr(get_settings(), "ghc_causelist_url_template", None)
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.template)

    def list(self, list_date: date) -> list[PdfRef]:
        if not self.template:
            return []
        return [
            PdfRef(
                list_date,
                f"{lt}_{list_date:%d-%m-%Y}.pdf",
                self.template.format(
                    list_type=lt, dd=f"{list_date:%d}", mm=f"{list_date:%m}", yyyy=f"{list_date:%Y}"
                ),
            )
            for lt in self.LIST_TYPES
        ]

    def fetch(self, ref: PdfRef) -> bytes:
        try:
            r = httpx.get(ref.location, timeout=self.timeout, follow_redirects=True)
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"GHC website: {e}") from e
        if r.status_code == 404:
            raise SourceNotFound(f"GHC website: {ref.name} not published")
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            raise SourceUnavailable(f"GHC website: HTTP {r.status_code} for {ref.name}")
        return r.content
