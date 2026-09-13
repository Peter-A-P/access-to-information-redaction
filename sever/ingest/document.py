"""The document model everything else reads.

One shape for every input format. A PDF, a Word file, an email export and a scan all
become the same thing: pages of text, each page carrying blocks with a kind and a
bounding box.

Offsets are per page and index into `Page.text`. That choice is deliberate. A
document-global offset is convenient right up to the moment a reviewer approves page 4 and
a later page shifts, and the export has to draw a box on one page from one offset. Every
span in this system says which page it is on and where on that page it starts.

Bounding boxes are in PDF points with the origin at the top left, which is what PyMuPDF
gives and what the redaction export needs back. A block from a source with no geometry
(an email body, a Word paragraph) has bbox None, and the export rasterises or re-lays such
documents rather than pretending to know where the text sat.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Self


class BlockKind(StrEnum):
    """What a block is, structurally. The decision layer leans on this hard: a name in a
    SIGNATURE block is an official signing a letter, and the same name in BODY is just a
    name. Getting this wrong is the single biggest source of role errors, which is why
    the sentence-only baseline exists to measure it."""

    LETTERHEAD = "letterhead"
    HEADING = "heading"
    ADDRESS = "address"
    SALUTATION = "salutation"
    BODY = "body"
    SIGNATURE = "signature"
    TABLE = "table"
    LIST = "list"
    HEADER = "header"
    FOOTER = "footer"
    EMAIL_HEADER = "email_header"
    ATTACHMENT_NOTE = "attachment_note"
    UNKNOWN = "unknown"

    @property
    def is_role_bearing(self) -> bool:
        """Blocks where a name normally comes with the capacity it is named in."""
        return self in (
            BlockKind.LETTERHEAD,
            BlockKind.SIGNATURE,
            BlockKind.EMAIL_HEADER,
            BlockKind.HEADER,
            BlockKind.FOOTER,
        )


class DocumentType(StrEnum):
    """The six document types in the corpus, plus a catch-all. Document type is part of
    the context record because it changes the prior: a signature on a complaint letter is
    usually the complainant, a signature on a briefing note is usually an official."""

    CORRESPONDENCE = "correspondence"
    CASE_NOTE = "case_note"
    EMAIL_CHAIN = "email_chain"
    MEETING_MINUTES = "meeting_minutes"
    HR_MEMORANDUM = "hr_memorandum"
    INCIDENT_REPORT = "incident_report"
    OTHER = "other"


class SourceKind(StrEnum):
    """Which track a page came from. Every published number is reported per track, because
    an OCR error and a decision error are different failures with different fixes."""

    NATIVE = "native"
    OCR = "ocr"


@dataclass(frozen=True, slots=True, order=True)
class Offsets:
    """A half-open character range [start, end) into a page's text."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"start must not be negative, got {self.start}")
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be greater than start ({self.start})")

    def __len__(self) -> int:
        return self.end - self.start

    def overlaps(self, other: Offsets) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Offsets) -> bool:
        return self.start <= other.start and other.end <= self.end

    def intersection(self, other: Offsets) -> Offsets | None:
        start, end = max(self.start, other.start), min(self.end, other.end)
        return Offsets(start, end) if end > start else None


@dataclass(frozen=True, slots=True)
class BBox:
    """A rectangle in PDF points, origin top left. Passed back to PyMuPDF unchanged when
    the export draws a redaction over it."""

    x0: float
    y0: float
    x1: float
    y1: float

    def union(self, other: BBox) -> BBox:
        return BBox(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass(frozen=True, slots=True)
class Block:
    """A run of text with a structural kind. Offsets index the page text."""

    kind: BlockKind
    offsets: Offsets
    text: str
    bbox: BBox | None = None
    # Set on blocks inside an email chain: which message of the chain this belongs to,
    # counting 0 for the outermost. A quoted reply is a different message with a different
    # author, and treating a chain as one document is how a quoted signature gets
    # attributed to the wrong person.
    message_index: int | None = None

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True, slots=True)
class Page:
    """One page. `text` is the authority: every offset in the system indexes it."""

    number: int
    text: str
    blocks: tuple[Block, ...] = ()
    width: float | None = None
    height: float | None = None
    source: SourceKind = SourceKind.NATIVE
    # Mean OCR confidence 0..1 for an OCR page, None for a native one. Reported with the
    # measured character error rate rather than used as a threshold.
    ocr_confidence: float | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError(f"page numbers start at 1, got {self.number}")
        for b in self.blocks:
            if b.offsets.end > len(self.text):
                raise ValueError(
                    f"page {self.number}: block ends at {b.offsets.end} but the page text "
                    f"is {len(self.text)} characters"
                )

    def slice(self, offsets: Offsets) -> str:
        return self.text[offsets.start : offsets.end]

    def block_at(self, offsets: Offsets) -> Block | None:
        """The block containing a span, or the one it overlaps most. A detected span that
        straddles a block boundary is usually a layout artefact rather than two entities,
        so it is attributed rather than split."""
        best: Block | None = None
        best_overlap = 0
        for b in self.blocks:
            hit = b.offsets.intersection(offsets)
            if hit is not None and len(hit) > best_overlap:
                best, best_overlap = b, len(hit)
        return best

    def blocks_of(self, *kinds: BlockKind) -> tuple[Block, ...]:
        wanted = set(kinds)
        return tuple(b for b in self.blocks if b.kind in wanted)

    def _is_sentence_end(self, i: int, hi: int) -> bool:
        """True when the character at `i` ends a sentence.

        A newline always does. A full stop, question mark or exclamation mark does only
        when what follows is whitespace or the end of the block. That qualification is not
        pedantry: without it "aaronpenashue@gov.nl.ca" ends a sentence three times, the
        context handed to the model is a truncated fragment, and, worse, the truncated
        email no longer matches the detected entity, so the placeholder policy does not
        substitute it and a name leaves the boundary inside a broken address. The
        corpus-wide guard caught exactly that, which is why this method exists.
        """
        ch = self.text[i]
        if ch == "\n":
            return True
        if ch not in ".!?":
            return False
        nxt = i + 1
        return nxt >= hi or self.text[nxt].isspace()

    def sentence_at(self, offsets: Offsets) -> Offsets:
        """The sentence containing a span, bounded by the block. Used by the sentence-only
        baseline, and as the smallest unit of context in the full record."""
        block = self.block_at(offsets)
        lo = block.offsets.start if block else 0
        hi = block.offsets.end if block else len(self.text)
        start = lo
        for i in range(offsets.start - 1, lo - 1, -1):
            if self._is_sentence_end(i, hi) and i + 1 <= offsets.start:
                start = i + 1
                break
        end = hi
        for i in range(offsets.end, hi):
            if self._is_sentence_end(i, hi):
                end = i + 1
                break
        while start < offsets.start and self.text[start].isspace():
            start += 1
        return Offsets(start, max(end, offsets.end))


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    """What the document says about itself. Populated by the format readers from headers
    and letterhead, not inferred. Inference belongs in sever.context."""

    title: str | None = None
    author: str | None = None
    recipients: tuple[str, ...] = ()
    date: str | None = None
    subject: str | None = None
    # Where the file came from and under what licence, carried through to the corpus
    # manifest so a published number can always be traced back to a source.
    source_note: str | None = None


@dataclass(frozen=True, slots=True)
class Document:
    """A record responsive to a request."""

    doc_id: str
    doc_type: DocumentType
    pages: tuple[Page, ...]
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    source_path: Path | None = None
    # sha256 of the source bytes. The corpus manifest commits these; nothing raw is
    # committed, so this is how a result is tied to an input that is not in the repository.
    sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.pages:
            raise ValueError(f"document {self.doc_id} has no pages")
        expected = list(range(1, len(self.pages) + 1))
        actual = [p.number for p in self.pages]
        if actual != expected:
            raise ValueError(f"document {self.doc_id} pages are {actual}, expected {expected}")

    def __iter__(self) -> Iterator[Page]:
        return iter(self.pages)

    def __len__(self) -> int:
        return len(self.pages)

    def page(self, number: int) -> Page:
        return self.pages[number - 1]

    @property
    def text(self) -> str:
        """The whole document, pages joined by a form feed. For coreference and for the
        model's document-level context only; never for offsets."""
        return "\f".join(p.text for p in self.pages)

    @property
    def tracks(self) -> frozenset[SourceKind]:
        return frozenset(p.source for p in self.pages)

    @property
    def is_scanned(self) -> bool:
        return SourceKind.OCR in self.tracks

    def with_pages(self, pages: Sequence[Page]) -> Self:
        return type(self)(
            doc_id=self.doc_id,
            doc_type=self.doc_type,
            pages=tuple(pages),
            metadata=self.metadata,
            source_path=self.source_path,
            sha256=self.sha256,
        )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
