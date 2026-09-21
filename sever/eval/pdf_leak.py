"""The PDF leak test: is anything that was redacted still recoverable from the output?

The question has to be asked precisely or the answer is worthless in both directions.

The wrong question is "does the redacted string appear anywhere in the output". It
over-reports: a record that redacts one occurrence of a name and correctly releases the
minister's title in a heading trips the test on the word "Minister". The first version of
this module asked that question and reported ten leaks, none of which were leaks. It also
*under*-reports, because a name that survives inside a box but is broken across a line by
the extractor does not match a substring test.

The right question is "is there still text inside this rectangle". That is what a
redaction claims to have done, it is checkable exactly, and it is what is measured here.
Two channels, because there are two ways it fails:

  1. The text layer. Extract the text clipped to each applied rectangle. A box drawn over
     selectable text leaves the glyphs in the content stream and this finds them. Runs on
     every export, always. This is the failure that has put real names into the public
     domain.
  2. The rendering. If the glyphs are painted and merely covered by an opaque rectangle,
     OCR of the rendered page recovers them. Needs Tesseract, a system binary. Where it is
     missing the check reports as not run, never as passed: a check that silently degrades
     to a pass is worse than no check at all.

The published number is "N boxes across M documents, K with recoverable text", and K is
expected to be zero. It is published even so, because the claim "our redactions are real"
is worth exactly as much as the test behind it.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from sever.context.requester import normalise
from sever.review.export import RedactedRegion

# A box narrower than this holds no recoverable text and clipping noise from neighbouring
# glyphs dominates. Counted and reported rather than silently dropped.
MIN_TESTABLE_WIDTH = 3.0
# Clip the rectangle inward before extracting, so a glyph from the adjacent unredacted
# character that overlaps the boundary by a hair is not reported as a survivor.
CLIP_INSET = 0.75


@dataclass(frozen=True, slots=True)
class LeakFinding:
    document: str
    page: int
    expected: str
    recovered: str
    channel: str

    def __str__(self) -> str:
        return (
            f"{self.document} p{self.page}: {self.recovered!r} is still readable inside a "
            f"box that redacted {self.expected!r} ({self.channel})"
        )


@dataclass(frozen=True, slots=True)
class LeakReport:
    documents: int
    boxes_tested: int
    findings: tuple[LeakFinding, ...] = ()
    ocr_ran: bool = False
    ocr_note: str = ""
    skipped_too_small: int = 0

    @property
    def clean(self) -> bool:
        return not self.findings

    @property
    def recoverable(self) -> int:
        return len(self.findings)

    def summary(self) -> str:
        channels = (
            "text layer and OCR of the rendering"
            if self.ocr_ran
            else f"text layer only ({self.ocr_note})"
        )
        return (
            f"{self.recoverable} of {self.boxes_tested} redaction boxes across "
            f"{self.documents} documents still had recoverable text. "
            f"Channels checked: {channels}."
        )

    def as_row(self) -> str:
        """The README's PDF leak test cell."""
        return f"{self.recoverable} recoverable out of {self.boxes_tested}"


# Where the Windows installer puts it. Tesseract is a system binary rather than a wheel, so
# it is routinely installed without landing on PATH, and a leak test that quietly skips its
# second channel because of that is the worst possible failure mode: it reports "text layer
# only" and the reader has to notice.
_KNOWN_LOCATIONS = (
    Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe",
    Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
    Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
)


def tesseract_path() -> Path | None:
    """The binary, from SEVER_TESSERACT, then PATH, then the usual installer locations."""
    override = os.environ.get("SEVER_TESSERACT", "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    return next((p for p in _KNOWN_LOCATIONS if p.is_file()), None)


def tesseract_available() -> bool:
    return tesseract_path() is not None


def _clip(bbox: tuple[float, float, float, float]) -> pymupdf.Rect:
    x0, y0, x1, y1 = bbox
    return pymupdf.Rect(x0 + CLIP_INSET, y0 + CLIP_INSET, x1 - CLIP_INSET, y1 - CLIP_INSET)


def check_text_layer(
    path: Path, regions: Sequence[RedactedRegion], document: str
) -> tuple[list[LeakFinding], int]:
    """Extract the text clipped to each applied rectangle. Anything non-empty is a leak."""
    findings: list[LeakFinding] = []
    skipped = 0
    doc = pymupdf.open(str(path))
    try:
        for region in regions:
            if region.bbox.x1 - region.bbox.x0 < MIN_TESTABLE_WIDTH:
                skipped += 1
                continue
            page = doc[region.page - 1]
            recovered = page.get_text("text", clip=_clip(region.bbox.as_tuple())).strip()
            if recovered:
                findings.append(
                    LeakFinding(
                        document=document,
                        page=region.page,
                        expected=region.text,
                        recovered=recovered,
                        channel="text layer",
                    )
                )
    finally:
        doc.close()
    return findings, skipped


def check_rendering(
    path: Path, regions: Sequence[RedactedRegion], document: str, *, dpi: int = 300
) -> list[LeakFinding]:
    """OCR the pixels inside each box. Catches a box that covers rather than removes."""
    import pytesseract

    # pytesseract shells out to the binary and looks only at PATH. Point it at whatever
    # `tesseract_path` found, so an installation that is not on PATH still runs.
    binary = tesseract_path()
    if binary is not None:
        pytesseract.pytesseract.tesseract_cmd = str(binary)
    from PIL import Image

    findings: list[LeakFinding] = []
    doc = pymupdf.open(str(path))
    try:
        for region in regions:
            if region.bbox.x1 - region.bbox.x0 < MIN_TESTABLE_WIDTH:
                continue
            page = doc[region.page - 1]
            pix = page.get_pixmap(dpi=dpi, clip=_clip(region.bbox.as_tuple()))
            if pix.width == 0 or pix.height == 0:
                continue
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            recovered = pytesseract.image_to_string(image).strip()
            # OCR of a solid black rectangle returns noise, so require that what came back
            # looks like the string that was redacted rather than merely being non-empty.
            if recovered and normalise(recovered) and normalise(recovered) in normalise(
                region.text
            ):
                findings.append(
                    LeakFinding(
                        document=document,
                        page=region.page,
                        expected=region.text,
                        recovered=recovered,
                        channel="ocr of the rendering",
                    )
                )
    finally:
        doc.close()
    return findings


@dataclass
class LeakChecker:
    """Accumulates results across every export in a run."""

    use_ocr: bool = True
    findings: list[LeakFinding] = field(default_factory=list)
    documents: int = 0
    boxes_tested: int = 0
    skipped_too_small: int = 0
    _ocr_ran: bool = False
    _ocr_note: str = ""

    def check(self, path: Path, regions: Sequence[RedactedRegion], *, document: str) -> None:
        self.documents += 1
        text_findings, skipped = check_text_layer(path, regions, document)
        self.skipped_too_small += skipped
        self.boxes_tested += len(regions) - skipped
        self.findings.extend(text_findings)
        if not self.use_ocr:
            self._ocr_note = "OCR channel disabled for this run"
            return
        if not tesseract_available():
            self._ocr_note = (
                "Tesseract is not installed on this machine, so the rendering channel did "
                "not run"
            )
            return
        self._ocr_ran = True
        self.findings.extend(check_rendering(path, regions, document))

    def report(self) -> LeakReport:
        return LeakReport(
            documents=self.documents,
            boxes_tested=self.boxes_tested,
            findings=tuple(self.findings),
            ocr_ran=self._ocr_ran,
            ocr_note=self._ocr_note,
            skipped_too_small=self.skipped_too_small,
        )
