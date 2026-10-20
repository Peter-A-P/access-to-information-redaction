"""True redaction: the text under the box is removed, and a test proves it.

A black rectangle drawn over selectable text is the most common real-world redaction
failure. It has put names into the public domain repeatedly, and it happens because
drawing a box is easy and removing text is a different operation that looks identical on
screen. This project refuses to ship it: `apply_redactions` uses PyMuPDF's redaction
annotations, which delete the glyphs in the covered area, and `sever.eval.pdf_leak`
extracts the text layer of every export and asserts that nothing redacted survives.

Geometry. The corpus documents are text, so this module lays them out itself, in Courier
at a fixed size. That is not a cosmetic choice. A monospaced font makes the position of
character *n* on a line exactly computable, so a span at offsets [s, e) maps to a rectangle
without searching the rendered page for the string. Searching is how redaction tools
acquire their worst bug: a name that occurs twice gets a box over the first occurrence and
the second one ships. For an ingested PDF the geometry comes from the source instead, and
`rects_from_source` is the path that uses it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from sever.decide.pipeline import Proposal
from sever.ingest.document import BBox, Document, Offsets, Page

FONT = "cour"
FONT_SIZE = 9.5
# Courier's advance width is exactly 0.6 em at every size, which is what makes the offset
# arithmetic below exact rather than approximate.
CHAR_WIDTH_RATIO = 0.6
LINE_HEIGHT = FONT_SIZE * 1.35
MARGIN_X = 54.0
MARGIN_Y = 60.0
PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0

CHAR_WIDTH = FONT_SIZE * CHAR_WIDTH_RATIO
COLUMNS = int((PAGE_WIDTH - 2 * MARGIN_X) / CHAR_WIDTH)


@dataclass(frozen=True, slots=True)
class LineSegment:
    """One rendered line, and which slice of the page text it holds."""

    index: int
    offsets: Offsets
    text: str

    @property
    def y_top(self) -> float:
        return MARGIN_Y + self.index * LINE_HEIGHT

    def rect_for(self, start: int, end: int) -> BBox:
        col_start = max(start, self.offsets.start) - self.offsets.start
        col_end = min(end, self.offsets.end) - self.offsets.start
        return BBox(
            x0=MARGIN_X + col_start * CHAR_WIDTH,
            y0=self.y_top,
            x1=MARGIN_X + col_end * CHAR_WIDTH,
            y1=self.y_top + LINE_HEIGHT,
        )


def lay_out(text: str, columns: int = COLUMNS) -> list[LineSegment]:
    """Hard-wrap page text into lines, keeping the offset of every line.

    Wrapping is on whitespace where it can be and mid-word where it cannot, because a line
    that overflows the page silently loses characters and a redaction cannot be drawn over
    a character that was never rendered.
    """
    segments: list[LineSegment] = []
    index = 0
    pos = 0
    n = len(text)
    while pos <= n:
        newline = text.find("\n", pos)
        hard_end = n if newline == -1 else newline
        if hard_end - pos <= columns:
            segments.append(LineSegment(index, Offsets(pos, max(hard_end, pos + 1)), text[pos:hard_end]))
            index += 1
            if newline == -1:
                break
            pos = newline + 1
            continue
        cut = text.rfind(" ", pos, pos + columns + 1)
        if cut <= pos:
            cut = pos + columns
        segments.append(LineSegment(index, Offsets(pos, cut), text[pos:cut]))
        index += 1
        pos = cut + 1 if cut < n and text[cut] == " " else cut
    return [s for s in segments if len(s.offsets) > 0]


def rects_for(page: Page, offsets: Offsets, columns: int = COLUMNS) -> list[BBox]:
    """Every rectangle covering a span, one per line it crosses."""
    out: list[BBox] = []
    for seg in lay_out(page.text, columns):
        if seg.offsets.overlaps(offsets):
            out.append(seg.rect_for(offsets.start, offsets.end))
    return out


def rects_from_source(page: Page, offsets: Offsets) -> list[BBox]:
    """Rectangles from an ingested document's own geometry.

    Used when the page came from a real PDF and the block bounding boxes are real. Falls
    back to the block's box when a finer one is not available, which over-covers rather
    than under-covers: a box larger than the span redacts a little extra text, a box
    smaller than the span ships a name.
    """
    block = page.block_at(offsets)
    if block is not None and block.bbox is not None:
        return [block.bbox]
    return []


def render_pdf(document: Document, path: Path, *, columns: int = COLUMNS) -> Path:
    """Lay the document out into a PDF with computable geometry."""
    doc = pymupdf.open()
    for page in document:
        pdf_page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        for seg in lay_out(page.text, columns):
            if not seg.text:
                continue
            pdf_page.insert_text(
                (MARGIN_X, seg.y_top + FONT_SIZE),
                seg.text,
                fontname=FONT,
                fontsize=FONT_SIZE,
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


@dataclass(frozen=True, slots=True)
class RedactedRegion:
    """One box that was applied, and what used to be under it.

    Carried out of the export so the leak test can ask the only question that actually
    matters: is there still text inside this rectangle? Asking instead whether the string
    appears anywhere in the output is the wrong test, and it fails on a document where the
    same word is legitimately released elsewhere. The first version of this code made that
    mistake and reported ten leaks that were the word "Minister" appearing, correctly, in
    an unredacted heading.
    """

    page: int
    bbox: BBox
    text: str
    code: str


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: Path
    redacted_strings: tuple[str, ...]
    regions: tuple[RedactedRegion, ...]
    boxes: int
    pages: int


def apply_redactions(
    source: Path,
    destination: Path,
    document: Document,
    proposals: Iterable[Proposal],
    *,
    columns: int = COLUMNS,
    rasterise: bool = False,
) -> ExportResult:
    """Remove the text under every withholding proposal and write the released record.

    `rasterise` re-renders each page as an image afterwards. It is the belt-and-braces
    option for scans, where an OCR text layer may not align with the visible glyphs, and it
    is offered rather than defaulted because it destroys selectable text for the whole
    document including the parts that were released.
    """
    withheld = [p for p in proposals if p.withholds]
    doc = pymupdf.open(str(source))
    boxes = 0
    strings: list[str] = []
    regions: list[RedactedRegion] = []
    try:
        for proposal in withheld:
            page = document.page(proposal.page)
            pdf_page = doc[proposal.page - 1]
            rects = rects_for(page, proposal.detection.offsets, columns)
            for box in rects:
                pdf_page.add_redact_annot(pymupdf.Rect(*box.as_tuple()), fill=(0, 0, 0))
                boxes += 1
                regions.append(
                    RedactedRegion(
                        page=proposal.page,
                        bbox=box,
                        text=proposal.detection.text,
                        code=proposal.code,
                    )
                )
            strings.append(proposal.detection.text)
        for pdf_page in doc:
            # The default removes text and images under the annotation. This is the line
            # that makes the redaction real; without it the boxes are decoration.
            pdf_page.apply_redactions()
        if rasterise:
            raster = pymupdf.open()
            for pdf_page in doc:
                pix = pdf_page.get_pixmap(dpi=200)
                new = raster.new_page(width=pdf_page.rect.width, height=pdf_page.rect.height)
                new.insert_image(new.rect, pixmap=pix)
            doc.close()
            doc = raster
        destination.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(destination), garbage=4, deflate=True)
        pages = doc.page_count
    finally:
        doc.close()
    return ExportResult(
        path=destination,
        redacted_strings=tuple(strings),
        regions=tuple(regions),
        boxes=boxes,
        pages=pages,
    )


# Points added round every box on a scan. The OCR layer's word boxes are a reading of the
# image, not the image, and an ascender or a descender a hair outside its word's box would
# otherwise stay visible beside the box.
SCAN_PADDING = 1.5


class UnplacedSpan(RuntimeError):
    """A span to withhold whose characters the scan's word boxes do not all cover. The
    export stops rather than ship a page with part of a name left in the image."""


@dataclass(frozen=True, slots=True)
class _Word:
    start: int
    end: int
    rect: pymupdf.Rect
    line: tuple[int, int]


def _words_on(pdf_page: pymupdf.Page, text: str) -> list[_Word]:
    """Each word of the page's text layer, with its offsets in `text` and its box.

    `text` is the page's `get_text("text")`, which is what `Page.text` holds, and the words
    come in the same reading order, so each is found by walking forward from the end of the
    last with nothing but whitespace between. That ties a box to an occurrence, never to a
    string: a name that appears twice gets the box of the occurrence the span is at. A word
    that cannot be placed so is left out, and a span that needs it is refused by
    `rects_on_scan`.
    """
    words: list[_Word] = []
    cursor = 0
    for x0, y0, x1, y1, word, block, line, _ in pdf_page.get_text("words"):
        at = text.find(word, cursor)
        if at < 0 or text[cursor:at].strip():
            continue
        words.append(_Word(at, at + len(word), pymupdf.Rect(x0, y0, x1, y1), (block, line)))
        cursor = at + len(word)
    return words


def rects_on_scan(words: Sequence[_Word], text: str, offsets: Offsets) -> list[BBox]:
    """The boxes that cover a span on a scanned page: one per line it crosses.

    Whole words, so a span that ends inside a word takes the word, which over-covers rather
    than under-covers. Every non-space character of the span must fall inside a placed word
    or the span is refused.
    """
    hit = [w for w in words if w.start < offsets.end and w.end > offsets.start]
    for i in range(offsets.start, offsets.end):
        if not text[i].isspace() and not any(w.start <= i < w.end for w in hit):
            raise UnplacedSpan(
                f"no word box covers character {i} of {text[offsets.start:offsets.end]!r}"
            )
    lines: dict[tuple[int, int], pymupdf.Rect] = {}
    for w in hit:
        lines[w.line] = lines[w.line] | w.rect if w.line in lines else pymupdf.Rect(w.rect)
    p = SCAN_PADDING
    return [BBox(r.x0 - p, r.y0 - p, r.x1 + p, r.y1 + p) for r in lines.values()]


def redact_scan(
    source: Path,
    destination: Path,
    document: Document,
    proposals: Iterable[Proposal],
) -> ExportResult:
    """Redact a scanned record in place: the boxes go on the original page images.

    A scan is a picture with an invisible OCR text layer over it, and both have to lose
    what a box covers. `apply_redactions` with `PDF_REDACT_IMAGE_PIXELS` overwrites the
    pixels under each box in the image itself, deletes the text layer's characters under
    it, and draws the box into the page's content, so there is no shape to remove and no
    covered picture under it. The file is then written whole, without the unused objects
    and earlier revisions a PDF can carry, and with its document information emptied.
    `sever.eval.pdf_leak` checks the text layer, the pixels and the structure before it is
    served.
    """
    withheld = [p for p in proposals if p.withholds]
    doc = pymupdf.open(str(source))
    regions: list[RedactedRegion] = []
    strings: list[str] = []
    try:
        placed: dict[int, list[_Word]] = {}
        for proposal in withheld:
            page = document.page(proposal.page)
            pdf_page = doc[proposal.page - 1]
            if proposal.page not in placed:
                placed[proposal.page] = _words_on(pdf_page, page.text)
            boxes = rects_on_scan(placed[proposal.page], page.text, proposal.detection.offsets)
            for box in boxes:
                pdf_page.add_redact_annot(pymupdf.Rect(*box.as_tuple()), fill=(0, 0, 0))
                regions.append(
                    RedactedRegion(
                        page=proposal.page,
                        bbox=box,
                        text=proposal.detection.text,
                        code=proposal.code,
                    )
                )
            strings.append(proposal.detection.text)
        for pdf_page in doc:
            pdf_page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )
        doc.set_metadata({})
        doc.del_xml_metadata()
        destination.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(destination), garbage=4, deflate=True, clean=True)
        pages = doc.page_count
    finally:
        doc.close()
    return ExportResult(
        path=destination,
        redacted_strings=tuple(strings),
        regions=tuple(regions),
        boxes=len(regions),
        pages=pages,
    )


def extract_text(path: Path) -> str:
    doc = pymupdf.open(str(path))
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


@dataclass(frozen=True, slots=True)
class Schedule:
    """The redaction schedule the requester receives, generated from approved rows."""

    request_id: str
    rows: tuple[tuple[int, str, str, str, str], ...]

    def to_markdown(self) -> str:
        lines = [
            f"# Schedule of severances - request {self.request_id}",
            "",
            "Each severance in the released record, the category applied and the provision",
            "relied upon. Generated from the approved reviewer actions; not hand-edited.",
            "",
            "| Page | Extent | Category | Provision | Reason |",
            "|---|---|---|---|---|",
        ]
        for page, extent, code, provision, reason in self.rows:
            lines.append(f"| {page} | {extent} | {code} | {provision} | {reason} |")
        if not self.rows:
            lines.append("| - | - | - | - | Nothing was severed. |")
        return "\n".join(lines) + "\n"


def build_schedule(
    request_id: str, document: Document, proposals: Sequence[Proposal]
) -> Schedule:
    rows: list[tuple[int, str, str, str, str]] = []
    for p in sorted(
        (p for p in proposals if p.withholds), key=lambda p: (p.page, p.detection.offsets.start)
    ):
        extent = f"{len(p.detection.offsets)} characters"
        rows.append((p.page, extent, p.code, p.citation or "not mapped", p.reason))
    return Schedule(request_id=request_id, rows=tuple(rows))
