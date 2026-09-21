"""Real released records: the only track where a human made every label.

Section 2.4 of PLAN.md names this as the real-document test, and it is the only measurement
in the repository whose ground truth was not written by this project. Everything still
visible in a completed access-to-information release was looked at by a public body's
reviewer and judged releasable. So a visible span is a **must-keep label made by a person**,
and any span this tool would put a box over is an over-redaction against a real decision
rather than against a generated one.

## What this track can and cannot measure

It measures over-redaction and nothing else. What sits under the existing black boxes was
removed before publication and cannot be recovered, so there is no must-redact denominator
and **leak rate is not computable here**. `Scored.leak_rate` refuses outright on an observed
track rather than returning a number that would mean nothing, which is the behaviour this
module exists to feed.

## Why there is no fetcher

There is no documented API for downloading completed release packages. Library and Archives
Canada publishes a search interface at
https://telechargerdemandesaicompletees-downloadcompletedatirequests.bac-lac.gc.ca that
serves them free of charge, and its search backend is an undocumented endpoint behind a
JavaScript front end. Reverse-engineering it was tried and abandoned: it would be fragile,
it is not a use the site documents, and a track that depends on an undocumented endpoint
staying stable is not reproducible in the way the rest of this repository is.

So the track is manifest-driven. Somebody downloads packages by hand, `sever releases add`
records each one with its sha256, its source URL and the date it was retrieved, and the
manifest is committed while the PDFs are not. Anyone can then download the same packages
from the same URLs, run the same command, and get the same numbers or a checksum failure
saying which file differs. That is slower than a fetcher and more honest than one.

Terms: Government of Canada material may be reproduced for non-commercial purposes without
permission, with attribution, under the canada.ca terms of reproduction. Nothing raw is
committed here in any case; see `docs/data.md`.

## The guard that matters more than the measurement

A released PDF is supposed to have had the text under its boxes removed. Not all of them do.
A package that merely draws rectangles over live text still carries the withheld names in
its text layer, and this module would then read them as "visible" and count every one as a
must-keep label. The measurement would be wrong and, worse, the tool would be marked down
for proposing to redact exactly the spans a reviewer *had* decided to withhold.

`inspect_redaction` looks for that before anything is scored, and a package that fails is
excluded with a reason rather than quietly included. It is the same question
`sever/eval/pdf_leak.py` asks of this project's own exports, turned around and asked of
someone else's.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sever.ingest.document import Block, BlockKind, Document, DocumentType, Offsets, Page

DEFAULT_MANIFEST = Path("data/releases/manifest.json")
DEFAULT_DIR = Path("data/releases")

PARAGRAPH_BREAK = "\n\n"

# A page with fewer characters than this is a separator, a fax cover or a page that was
# withheld in full. Counted and reported rather than scored: it carries no visible span, so
# it contributes nothing to a must-keep denominator and would only dilute the page count.
MIN_PAGE_CHARACTERS = 40


class ManifestError(RuntimeError):
    """The manifest and the files on disk disagree."""


@dataclass(frozen=True, slots=True)
class ReleaseRecord:
    """One published release package, as the committed manifest records it."""

    file_name: str
    sha256: str
    source_url: str
    retrieved_on: str
    institution: str = ""
    request_number: str = ""
    note: str = ""

    def path(self, root: Path = DEFAULT_DIR) -> Path:
        return root / self.file_name


@dataclass(frozen=True, slots=True)
class RedactionCheck:
    """Whether a package's black boxes actually removed the text underneath."""

    boxes: int
    boxes_with_text: int
    checked: bool = True
    note: str = ""

    @property
    def sound(self) -> bool:
        """True when nothing was recovered from under a box.

        A package that fails this is excluded from the measurement. Its visible text
        includes values a reviewer decided to withhold, so counting them as must-keep
        labels would mark this tool down for agreeing with that reviewer.
        """
        return self.checked and self.boxes_with_text == 0


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[ReleaseRecord, ...]:
    if not path.is_file():
        return ()
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = set(ReleaseRecord.__dataclass_fields__)
    return tuple(
        ReleaseRecord(**{k: v for k, v in row.items() if k in fields})
        for row in data.get("packages", [])
    )


def write_manifest(
    records: tuple[ReleaseRecord, ...], path: Path = DEFAULT_MANIFEST
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "_comment": (
                    "Published federal access-to-information release packages, for the "
                    "real-record over-redaction test. The PDFs are not committed; these "
                    "checksums and URLs are, so the same packages can be downloaded and "
                    "the same numbers reproduced. See sever/ingest/releases.py."
                ),
                "packages": [asdict(r) for r in records],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def add(
    pdf: Path,
    *,
    source_url: str,
    institution: str = "",
    request_number: str = "",
    note: str = "",
    manifest: Path = DEFAULT_MANIFEST,
    today: dt.date | None = None,
) -> ReleaseRecord:
    """Record a downloaded package, replacing any earlier entry for the same file."""
    if not pdf.is_file():
        raise ManifestError(f"no file at {pdf}")
    record = ReleaseRecord(
        file_name=pdf.name,
        sha256=sha256_of(pdf),
        source_url=source_url,
        retrieved_on=(today or dt.date.today()).isoformat(),
        institution=institution,
        request_number=request_number,
        note=note,
    )
    existing = tuple(r for r in read_manifest(manifest) if r.file_name != pdf.name)
    write_manifest((*existing, record), manifest)
    return record


def verify(
    records: tuple[ReleaseRecord, ...], root: Path = DEFAULT_DIR
) -> tuple[tuple[ReleaseRecord, ...], tuple[str, ...]]:
    """Split the manifest into packages present and correct, and reasons for the rest.

    A checksum mismatch is not a warning. The whole point of committing the manifest
    instead of the PDFs is that a reader can obtain the same bytes; a file that differs is
    not the file the published number was measured on.
    """
    good: list[ReleaseRecord] = []
    problems: list[str] = []
    for record in records:
        path = record.path(root)
        if not path.is_file():
            problems.append(f"{record.file_name}: not downloaded (expected at {path})")
            continue
        actual = sha256_of(path)
        if actual != record.sha256:
            problems.append(
                f"{record.file_name}: sha256 is {actual[:12]} and the manifest says "
                f"{record.sha256[:12]}, so this is not the file that was measured"
            )
            continue
        good.append(record)
    return tuple(good), tuple(problems)


# --- reading a released PDF -------------------------------------------------------


def inspect_redaction(path: Path) -> RedactionCheck:
    """Ask someone else's release the question this project asks of its own exports.

    A black rectangle drawn over live text is the most common real redaction failure, and a
    package with one is unusable here for a reason that has nothing to do with the failure
    itself: its text layer carries values a reviewer withheld, and this module would read
    them as visible and score them as must-keep.

    Filled rectangles are found in the page's drawing commands and the text layer is read
    inside each one. A page image with no vector drawings gives no boxes to check, which is
    reported as unchecked rather than as sound.
    """
    import pymupdf

    boxes = 0
    with_text = 0
    doc = pymupdf.open(str(path))
    try:
        for page in doc:
            for drawing in page.get_drawings():
                if drawing.get("fill") is None:
                    continue
                rect = drawing.get("rect")
                if rect is None or rect.width < 8 or rect.height < 4:
                    continue
                boxes += 1
                inner = pymupdf.Rect(
                    rect.x0 + 1.0, rect.y0 + 1.0, rect.x1 - 1.0, rect.y1 - 1.0
                )
                if inner.is_empty:
                    continue
                if page.get_text("text", clip=inner).strip():
                    with_text += 1
    finally:
        doc.close()
    if not boxes:
        return RedactionCheck(
            boxes=0,
            boxes_with_text=0,
            checked=False,
            note=(
                "no filled rectangles found, so nothing could be checked. The package may "
                "be a scan, or may have been redacted by removing the text without drawing "
                "anything over it"
            ),
        )
    return RedactionCheck(boxes=boxes, boxes_with_text=with_text)


def to_document(path: Path, doc_id: str) -> Document:
    """The visible text of a released package, as a `Document`.

    Blocks are paragraphs and every one is BODY, for the same reason as the scanned track:
    nothing in a released PDF says which paragraph was a signature block. The consequence is
    the same too, and it is stated in the generated table rather than left for a reader to
    work out: the rules lose the evidence they lean on hardest, so this track's
    over-redaction figure carries that handicap as well as everything else.
    """
    import pymupdf

    pages: list[Page] = []
    doc = pymupdf.open(str(path))
    try:
        for number, pdf_page in enumerate(doc, start=1):
            text = pdf_page.get_text("text")
            blocks: list[Block] = []
            position = 0
            for part in text.split(PARAGRAPH_BREAK):
                stripped = part.strip()
                if stripped:
                    start = text.index(stripped, position)
                    blocks.append(
                        Block(
                            kind=BlockKind.BODY,
                            offsets=Offsets(start, start + len(stripped)),
                            text=stripped,
                        )
                    )
                position += len(part) + len(PARAGRAPH_BREAK)
            pages.append(Page(number=number, text=text, blocks=tuple(blocks)))
    finally:
        doc.close()
    if not pages:
        raise ManifestError(f"{path} has no pages")
    return Document(doc_id=doc_id, doc_type=DocumentType.CORRESPONDENCE, pages=tuple(pages))


@dataclass(frozen=True, slots=True)
class LoadedRelease:
    record: ReleaseRecord
    document: Document
    redaction: RedactionCheck

    @property
    def scorable_pages(self) -> int:
        return sum(1 for p in self.document if len(p.text.strip()) >= MIN_PAGE_CHARACTERS)


@dataclass
class Loaded:
    releases: list[LoadedRelease] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)

    @property
    def pages(self) -> int:
        return sum(r.scorable_pages for r in self.releases)


def load(
    manifest: Path = DEFAULT_MANIFEST, root: Path = DEFAULT_DIR
) -> Loaded:
    """Every package in the manifest that is present, unmodified and soundly redacted."""
    records, problems = verify(read_manifest(manifest), root)
    out = Loaded(excluded=list(problems))
    for record in records:
        path = record.path(root)
        check = inspect_redaction(path)
        if not check.sound:
            out.excluded.append(
                f"{record.file_name}: {check.boxes_with_text} of {check.boxes} boxes still "
                f"have text under them, so its visible text includes values a reviewer "
                f"withheld and it cannot be used as a must-keep label set"
                if check.checked
                else f"{record.file_name}: {check.note}"
            )
            continue
        out.releases.append(
            LoadedRelease(
                record=record,
                document=to_document(path, record.file_name),
                redaction=check,
            )
        )
    return out
