"""The scanned track: render, degrade, scan, read back, and measure what was lost.

Section 5 of PLAN.md names the scan track and section 10 asks for a character error rate on
it. A public body's records are not all born digital. Some of the oldest and most sensitive
are paper, and a redaction tool that only works on text it was handed cleanly is a tool for
the easy half of the job.

## What this does

A corpus document is already rendered to PDF for the export path, in a monospaced font with
computable geometry. This module takes that render, rasterises it, degrades it the way a
document scanner does, and reads it back with Tesseract. The result is a `Document` whose
pages are `SourceKind.OCR` and whose text is what the OCR engine actually produced,
mistakes and all.

## The hard part is not the OCR, it is the labels

The corpus knows where every persona value sits, as offsets into the page text. After OCR
those offsets mean nothing: a dropped character shifts everything after it. So the labels
are re-projected through a character alignment between the true text and the OCR output,
and a label whose value did not survive at all is **not** quietly dropped. It is counted.

That count is a number worth having on its own. A value the OCR destroyed is a value no
detector can find, so it puts a ceiling on recall for this track that has nothing to do with
the detector, and reporting recall on a scanned page without it would blame the wrong
component. This is the same mistake as the mislabelled-span one, arriving from a new
direction.

## Why the pages are degraded on purpose

Tesseract reading a clean 200 dpi render of Courier is close to perfect, and a scan track
built on that would report a character error rate near zero and prove nothing. Real scans
are skewed by a fraction of a degree, blurred by the optics, speckled by the sensor and
then JPEG compressed by the scanner's firmware. `Degradation` applies those, the defaults
are stated in the generated table, and the clean figure is reported beside the degraded one
so a reader can separate "OCR is hard" from "this project made it hard".
"""

from __future__ import annotations

import difflib
import io
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from sever.corpus.labels import LabelledSpan, LabelSet
from sever.ingest.document import Block, BlockKind, Document, Offsets, Page, SourceKind

# 200 dpi is what an office multifunction device defaults to for document capture, and it
# is the floor at which Tesseract is usually reliable on 9.5 point text. Higher would
# flatter the result.
DEFAULT_DPI = 200

PARAGRAPH_BREAK = "\n\n"


class TesseractMissing(RuntimeError):
    """The scan track needs a system binary that is not a Python package."""


def tesseract_path() -> Path | None:
    """The binary, from SEVER_TESSERACT, then PATH, then the usual installer locations."""
    override = os.environ.get("SEVER_TESSERACT", "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    known = (
        Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe",
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
    )
    return next((p for p in known if p.is_file()), None)


def available() -> bool:
    return tesseract_path() is not None


@dataclass(frozen=True, slots=True)
class Degradation:
    """What a document scanner does to a page, in the order it does it.

    The defaults are an office multifunction device on its normal setting, not a worst
    case. A worst case would produce a dramatic character error rate and would not tell
    anyone what to expect.
    """

    dpi: int = DEFAULT_DPI
    # Paper never goes through a feeder perfectly straight. A fraction of a degree is
    # enough to change which pixels a glyph lands on.
    rotation_degrees: float = 0.4
    # The optics. Below about 0.4 this changes nothing; above about 1.2 it destroys the
    # page and the measurement becomes one about blur.
    blur_radius: float = 0.6
    # Sensor noise, as a standard deviation in grey levels.
    noise_sigma: float = 6.0
    # The scanner's own compression. None leaves the render uncompressed.
    jpeg_quality: int | None = 70
    seed: int = 20270802

    @property
    def is_clean(self) -> bool:
        return (
            self.rotation_degrees == 0.0
            and self.blur_radius == 0.0
            and self.noise_sigma == 0.0
            and self.jpeg_quality is None
        )

    def describe(self) -> str:
        if self.is_clean:
            return f"{self.dpi} dpi, no degradation"
        parts = [f"{self.dpi} dpi"]
        if self.rotation_degrees:
            parts.append(f"{self.rotation_degrees} degree skew")
        if self.blur_radius:
            parts.append(f"{self.blur_radius} px blur")
        if self.noise_sigma:
            parts.append(f"sigma {self.noise_sigma} sensor noise")
        if self.jpeg_quality is not None:
            parts.append(f"JPEG quality {self.jpeg_quality}")
        return ", ".join(parts)


# Four points on one axis, because a single character error rate would be a number about
# this corpus rather than about OCR. The corpus renders in Courier at 9.5 point, which is
# close to the easiest thing a modern OCR engine can be given: monospaced, high contrast,
# no proportional kerning, no photocopy generation loss. So `CLEAN` is reported as the
# floor and is explicitly labelled a best case, and the harsher profiles say what happens
# as the input gets worse. The pipeline's behaviour across the four is the finding; any one
# of them alone is a number about a setting.
CLEAN = Degradation(rotation_degrees=0.0, blur_radius=0.0, noise_sigma=0.0, jpeg_quality=None)
SCANNER = Degradation()
PHOTOCOPY = Degradation(
    dpi=150, rotation_degrees=1.1, blur_radius=1.0, noise_sigma=14.0, jpeg_quality=45
)
FAX = Degradation(
    dpi=100, rotation_degrees=1.8, blur_radius=1.3, noise_sigma=22.0, jpeg_quality=25
)

PROFILES: dict[str, Degradation] = {
    "clean": CLEAN,
    "scanner": SCANNER,
    "photocopy": PHOTOCOPY,
    "fax": FAX,
}


def _degrade(image: Any, how: Degradation, page_number: int) -> Any:
    from PIL import Image, ImageFilter

    if how.rotation_degrees:
        # Pillow moved the resampling constants into an enum; the module-level aliases
        # still work at runtime but are not in the stubs, so this reads it from the enum.
        image = image.rotate(
            how.rotation_degrees,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=255,
        )
    if how.blur_radius:
        image = image.filter(ImageFilter.GaussianBlur(radius=how.blur_radius))
    if how.noise_sigma:
        # Seeded per page, so a rerun of the track is the same scan rather than a new one.
        rng = np.random.default_rng(how.seed + page_number)
        arr = np.asarray(image, dtype=np.float32)
        arr = arr + rng.normal(0.0, how.noise_sigma, arr.shape)
        image = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if how.jpeg_quality is not None:
        buffer = io.BytesIO()
        image.convert("L").save(buffer, format="JPEG", quality=how.jpeg_quality)
        buffer.seek(0)
        image = Image.open(buffer)
        image.load()
    return image


def read_pdf(path: Path, how: Degradation = SCANNER) -> tuple[list[str], list[float]]:
    """Rasterise, degrade, OCR. Returns each page's text and its mean word confidence."""
    binary = tesseract_path()
    if binary is None:
        raise TesseractMissing(
            "the scan track needs Tesseract, which is a system binary and not a Python "
            "package. Install it and put it on PATH, or point SEVER_TESSERACT at it."
        )
    import pymupdf
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = str(binary)

    texts: list[str] = []
    confidences: list[float] = []
    doc = pymupdf.open(str(path))
    try:
        for number, pdf_page in enumerate(doc, start=1):
            pix = pdf_page.get_pixmap(dpi=how.dpi, colorspace=pymupdf.csGRAY)
            image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            image = _degrade(image, how, number)
            texts.append(pytesseract.image_to_string(image))
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            scores = [float(c) for c in data.get("conf", []) if float(c) >= 0]
            confidences.append(sum(scores) / len(scores) / 100.0 if scores else 0.0)
    finally:
        doc.close()
    return texts, confidences


# --- what the OCR cost -----------------------------------------------------------


def edit_distance(a: str, b: str) -> int:
    """Levenshtein, row by row in numpy.

    A real edit distance rather than difflib's indel count. difflib treats a substitution
    as a delete plus an insert, which inflates the error rate on exactly the failure OCR
    makes most: reading one character as another.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = np.arange(len(b) + 1, dtype=np.int32)
    b_arr = np.frombuffer(b.encode("utf-32-le"), dtype=np.uint32)
    for i, ch in enumerate(a, start=1):
        current = np.empty_like(previous)
        current[0] = i
        cost = (b_arr != ord(ch)).astype(np.int32)
        for j in range(1, len(b) + 1):
            current[j] = min(
                current[j - 1] + 1,
                previous[j] + 1,
                previous[j - 1] + cost[j - 1],
            )
        previous = current
    return int(previous[-1])


def character_error_rate(truth: str, recovered: str) -> float:
    """Edit distance over the length of the truth. The standard CER."""
    if not truth:
        return 0.0
    return edit_distance(truth, recovered) / len(truth)


def _offset_map(truth: str, recovered: str) -> list[int | None]:
    """For each index in `truth`, the index in `recovered` that holds the same character.

    None where OCR changed or dropped it. Built from difflib's equal blocks, which is the
    right tool here: the question is not how far apart the strings are but which
    characters survived, and an equal block is exactly a run that did.
    """
    mapping: list[int | None] = [None] * len(truth)
    matcher = difflib.SequenceMatcher(None, truth, recovered, autojunk=False)
    for tag, i1, i2, j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                mapping[i1 + k] = j1 + k
    return mapping


@dataclass(frozen=True, slots=True)
class Reprojection:
    """Labels moved onto the OCR text, and the ones that did not make it."""

    labels: tuple[LabelledSpan, ...]
    destroyed: tuple[LabelledSpan, ...]

    @property
    def survival(self) -> float:
        total = len(self.labels) + len(self.destroyed)
        return len(self.labels) / total if total else 1.0


def reproject(labels: tuple[LabelledSpan, ...], truth: str, recovered: str) -> Reprojection:
    """Move each label's offsets from the true page text onto the OCR output.

    A label survives when at least one of its characters does. Anything less than that and
    there is nothing on the page to point at, so the label is returned as destroyed rather
    than as a zero-length span nobody can detect: a phantom label would count against
    detector recall for a value that is not there to be found.
    """
    mapping = _offset_map(truth, recovered)
    kept: list[LabelledSpan] = []
    lost: list[LabelledSpan] = []
    for label in labels:
        window = [
            j
            for i in range(label.offsets.start, min(label.offsets.end, len(mapping)))
            if (j := mapping[i]) is not None
        ]
        if not window:
            lost.append(label)
            continue
        start, end = min(window), max(window) + 1
        kept.append(replace(label, offsets=Offsets(start, end), text=recovered[start:end]))
    return Reprojection(labels=tuple(kept), destroyed=tuple(lost))


def paragraph_blocks(text: str) -> tuple[Block, ...]:
    """Blank-line-separated paragraphs, all BODY.

    A scan carries no semantic structure, and this is deliberately the weakest honest
    reconstruction of it: every block is BODY, because nothing in the pixels says which
    paragraph was a signature block and which was a letterhead. That matters more than the
    character error rate does. `BlockKind.is_role_bearing` is what tells the rules that a
    name in a signature block is an official signing in their official capacity, and on
    this track nothing is role-bearing, so the rules lose the evidence they lean on hardest.

    Kept as the baseline. `sever.ingest.layout.recover_blocks` reads the structure back
    from the text, and the scanned track reports both, so what the recovery is worth is a
    row in a table rather than a claim.
    """
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
    return tuple(blocks)


@dataclass(frozen=True, slots=True)
class ScannedPage:
    number: int
    truth: str
    recovered: str
    confidence: float
    cer: float
    destroyed_labels: int


@dataclass(frozen=True, slots=True)
class Scanned:
    """One document, put through a scanner and read back."""

    document: Document
    labels: LabelSet
    pages: tuple[ScannedPage, ...]
    degradation: Degradation

    @property
    def cer(self) -> float:
        """Over the whole document, weighted by page length rather than by page."""
        total = sum(len(p.truth) for p in self.pages)
        if not total:
            return 0.0
        return sum(p.cer * len(p.truth) for p in self.pages) / total

    @property
    def destroyed(self) -> int:
        return sum(p.destroyed_labels for p in self.pages)


def scan(
    document: Document,
    labels: LabelSet,
    pdf_path: Path,
    *,
    how: Degradation = SCANNER,
    recover_layout: bool = True,
) -> Scanned:
    """Render, scan, read back, and return a document whose text is what OCR produced.

    Its blocks are read back from that text by `recover_blocks`, or with
    `recover_layout=False` are paragraphs of BODY, which is what every scan was until
    2026-10-17.
    """
    from sever.ingest.layout import recover_blocks
    from sever.review.export import render_pdf

    render_pdf(document, pdf_path)
    texts, confidences = read_pdf(pdf_path, how)

    pages: list[Page] = []
    reports: list[ScannedPage] = []
    moved: list[LabelledSpan] = []
    for original, recovered, confidence in zip(document.pages, texts, confidences, strict=True):
        on_page = tuple(s for s in labels.spans if s.page == original.number)
        projection = reproject(on_page, original.text, recovered)
        moved.extend(projection.labels)
        pages.append(
            Page(
                number=original.number,
                text=recovered,
                blocks=(
                    recover_blocks(recovered) if recover_layout else paragraph_blocks(recovered)
                ),
                source=SourceKind.OCR,
                ocr_confidence=confidence,
            )
        )
        reports.append(
            ScannedPage(
                number=original.number,
                truth=original.text,
                recovered=recovered,
                confidence=confidence,
                cer=character_error_rate(original.text, recovered),
                destroyed_labels=len(projection.destroyed),
            )
        )
    return Scanned(
        document=replace(document, pages=tuple(pages)),
        labels=replace(labels, spans=tuple(moved)),
        pages=tuple(reports),
        degradation=how,
    )
