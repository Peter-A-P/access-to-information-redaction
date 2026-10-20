"""Short excerpts of published release packages, for the demonstration.

The six invented records show the tool where the answers are known. These show it on pages a
public body has already released, which is the question a visitor from a public body asks
first. `data/demo/manifest.json` names ten records of one to three pages, each taken from
one package in `data/releases`, and says what each one shows (PLAN.md 12.46).

**The excerpts are rebuilt, not committed**, for the reason the packages are not
(docs/data.md): `build` takes the listed pages from each package after checking the
package's sha256 against the manifest, and refuses a package whose bytes differ. The page
images and their OCR text layers come across unchanged; nothing is re-rendered.

**Nothing on them is a label.** Everything visible was released by a person, so a
withholding proposal on one of these pages is an over-redaction against that person's
decision, and there is no requester: the same reading as `sever eval-releases`, whose
configuration `items` uses.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sever.ingest.document import Document

DEFAULT_MANIFEST = Path("data/demo/manifest.json")
DEFAULT_DIR = Path("data/demo")
RELEASES_DIR = Path("data/releases")
# A record a visitor can read through in a few minutes. The manifest is checked against it,
# so a longer record cannot be added by accident.
MAX_PAGES = 3


class ExcerptError(RuntimeError):
    """The manifest, a package or an excerpt is not what it should be."""


@dataclass(frozen=True, slots=True)
class Released:
    """Where a demonstration record came from: shown beside it, and how its PDF is built."""

    file_name: str
    title: str
    source: str
    source_sha256: str
    pages: tuple[int, ...]
    request_number: str
    institution: str
    retrieved_on: str
    details_url: str
    lac_disposition: str
    shows: str
    # The excerpt on disk, once `load` has found it. Not in the manifest.
    pdf: Path | None = None

    @property
    def doc_id(self) -> str:
        return Path(self.file_name).stem

    @property
    def archival(self) -> bool:
        return self.institution.startswith("Library and Archives Canada")

    @property
    def page_label(self) -> str:
        """The package's own page numbers, as a visitor would look them up."""
        numbers = ", ".join(str(n) for n in self.pages)
        return f"{'page' if len(self.pages) == 1 else 'pages'} {numbers} of {self.source}"


def read_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[Released, ...]:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    records = tuple(
        Released(**{**r, "pages": tuple(r["pages"])}) for r in raw["records"]
    )
    seen: set[str] = set()
    for r in records:
        if r.doc_id in seen:
            raise ExcerptError(f"{path}: {r.doc_id} is listed twice")
        seen.add(r.doc_id)
        if not 1 <= len(r.pages) <= MAX_PAGES:
            raise ExcerptError(
                f"{path}: {r.file_name} has {len(r.pages)} pages; a demonstration record "
                f"has one to {MAX_PAGES}"
            )
    return records


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(
    manifest: Path = DEFAULT_MANIFEST,
    releases: Path = RELEASES_DIR,
    out: Path = DEFAULT_DIR,
) -> tuple[Path, ...]:
    """Write every excerpt the manifest lists, from the packages it names."""
    import pymupdf

    written: list[Path] = []
    out.mkdir(parents=True, exist_ok=True)
    for r in read_manifest(manifest):
        source = releases / r.source
        if not source.is_file():
            raise ExcerptError(f"{source} is missing; see docs/data.md for its source URL")
        found = _sha256(source)
        if found != r.source_sha256:
            raise ExcerptError(
                f"{source} has sha256 {found}, the manifest says {r.source_sha256}; "
                "LAC may have re-OCRed it, and the excerpt is not built from different bytes"
            )
        src = pymupdf.open(str(source))
        dst = pymupdf.open()
        try:
            for n in r.pages:
                if not 1 <= n <= src.page_count:
                    raise ExcerptError(f"{r.source} has no page {n}")
                dst.insert_pdf(src, from_page=n - 1, to_page=n - 1)
            dst.set_metadata(
                {
                    "title": r.title,
                    "subject": f"{r.page_label}, released by {r.institution}",
                }
            )
            target = out / r.file_name
            dst.save(str(target), garbage=4, deflate=True)
            written.append(target)
        finally:
            dst.close()
            src.close()
    return tuple(written)


def load(record: Released, directory: Path = DEFAULT_DIR) -> Document:
    """One excerpt as a `Document`, its blocks recovered from the text as for any release."""
    from sever.ingest.releases import to_document

    path = directory / record.file_name
    if not path.is_file():
        raise ExcerptError(f"{path} is missing; run `sever demo-records`")
    document = to_document(path, record.doc_id)
    if len(document) != len(record.pages):
        raise ExcerptError(
            f"{path} has {len(document)} pages, the manifest lists {len(record.pages)}"
        )
    return document
