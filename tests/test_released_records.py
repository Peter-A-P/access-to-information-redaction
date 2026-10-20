"""The demonstration's released pages: excerpts built only from the right bytes, and a box on
a scan that leaves nothing in the file.

A redacted scan can fail in three ways a typeset export cannot: the box covers the picture
and leaves it whole underneath, the hidden OCR text layer keeps the word, or the file keeps
a second copy of the page somewhere. Each test below builds the failure and checks the leak
test sees it, and builds the real redaction and checks the leak test passes it. The scan is
made here, a rendered page under an invisible text layer as an OCR'd package is, so the tests
run in CI, where the LAC packages are not; the last test runs on those packages where they
are present.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from sever.decide.pipeline import Proposal, Source
from sever.detect.types import Detection, EntityType
from sever.eval.pdf_leak import LeakChecker, check_image_pixels, check_scan_structure
from sever.ingest import excerpts
from sever.ingest.document import Document, Offsets
from sever.review.demo import DemoServer, demo_items, released_items
from sever.review.export import UnplacedSpan, rects_on_scan, redact_scan
from sever.review.session import Item
from sever.taxonomy.loader import Decision

NAME = "Margaret Thibodeau"
LINES = (
    "Dear Mr. Plaxton,",
    f"{NAME} wrote to the office on 3 May about the inspection.",
    "The inspecting officer replied the same week.",
    f"On 9 May {NAME} called again and asked for the file.",
)


def make_scan(path: Path, *, jpeg: bool = False) -> Path:
    """One page as an OCR'd package has it: a picture of the page, and the same words in an
    invisible text layer at the same places. LAC's colour scans are JPEGs, `jpeg`."""
    typeset = pymupdf.open()
    page = typeset.new_page(width=612, height=792)
    at = [(72.0, 90.0 + 20 * i) for i in range(len(LINES))]
    for (x, y), line in zip(at, LINES, strict=True):
        page.insert_text((x, y), line, fontname="helv", fontsize=12)
    picture = page.get_pixmap(dpi=150)
    scan = pymupdf.open()
    out = scan.new_page(width=612, height=792)
    if jpeg:
        out.insert_image(out.rect, stream=picture.tobytes("jpeg", jpg_quality=75))
    else:
        out.insert_image(out.rect, pixmap=picture)
    for (x, y), line in zip(at, LINES, strict=True):
        out.insert_text((x, y), line, fontname="helv", fontsize=12, render_mode=3)
    scan.set_metadata({"title": "a scanned page"})
    scan.save(str(path))
    return path


def withhold(document: Document, occurrence: int) -> Proposal:
    """A withholding proposal on the `occurrence`th appearance of NAME, by offset."""
    text = document.page(1).text
    start = -1
    for _ in range(occurrence):
        start = text.index(NAME, start + 1)
    detection = Detection(
        page=1,
        offsets=Offsets(start, start + len(NAME)),
        text=NAME,
        entity_type=EntityType.PERSON,
        score=1.0,
        recogniser="test",
    )
    return Proposal(
        detection=detection, code="R1", decision=Decision.REDACT, confidence=1.0,
        reason="test", source=Source.RULE,
    )


@pytest.fixture(params=[False, True], ids=["lossless", "jpeg"])
def scan(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[Path, Document]:
    from sever.ingest.releases import to_document

    path = make_scan(tmp_path / "scan.pdf", jpeg=request.param)
    return path, to_document(path, "scan")


def test_a_redacted_page_keeps_its_kind_of_image_and_its_size(
    scan: tuple[Path, Document], tmp_path: Path
) -> None:
    """A JPEG stays a JPEG. Stored losslessly, LAC's pages came back up to seven times
    their size (PLAN.md 12.46)."""
    path, document = scan
    result = redact_scan(path, tmp_path / "out.pdf", document, [withhold(document, 1)])

    def image(p: Path) -> tuple[str, int]:
        doc = pymupdf.open(str(p))
        xref = doc[0].get_images(full=True)[0][0]
        return doc.xref_object(xref, compressed=True), len(doc.xref_stream_raw(xref))

    (before, size_before), (after, size_after) = image(path), image(result.path)
    assert ("DCTDecode" in before) == ("DCTDecode" in after)
    assert size_after < 1.5 * size_before


def test_the_box_is_burned_into_the_image_on_the_occurrence_it_was_put_on(
    scan: tuple[Path, Document], tmp_path: Path
) -> None:
    path, document = scan
    result = redact_scan(path, tmp_path / "out.pdf", document, [withhold(document, 2)])
    checker = LeakChecker(use_ocr=False)
    checker.check(result.path, result.regions, document="scan", scan=True)
    assert checker.report().clean, checker.report().findings
    text = pymupdf.open(str(result.path))[0].get_text()
    # The second occurrence is gone from the text layer and the first, never withheld, is
    # still there: the box went on an occurrence, not on every match of a string.
    assert text.count(NAME) == 1
    assert text.index(NAME) < text.index("inspecting officer")


def test_a_box_drawn_over_the_scan_is_caught_in_the_text_and_in_the_pixels(
    scan: tuple[Path, Document], tmp_path: Path
) -> None:
    path, document = scan
    done = redact_scan(path, tmp_path / "out.pdf", document, [withhold(document, 1)])
    covered = pymupdf.open(str(path))
    for region in done.regions:
        covered[0].draw_rect(pymupdf.Rect(*region.bbox.as_tuple()), color=(0, 0, 0), fill=(0, 0, 0))
    covered.save(str(tmp_path / "covered.pdf"))
    checker = LeakChecker(use_ocr=False)
    checker.check(tmp_path / "covered.pdf", done.regions, document="scan", scan=True)
    channels = {f.channel for f in checker.report().findings}
    assert {"text layer", "image pixels"} <= channels


def test_a_second_copy_of_the_page_or_its_title_is_caught(
    scan: tuple[Path, Document], tmp_path: Path
) -> None:
    path, document = scan
    done = redact_scan(path, tmp_path / "out.pdf", document, [withhold(document, 1)])
    assert check_scan_structure(done.path, "scan") == []
    doc = pymupdf.open(str(done.path))
    doc[0].insert_image(pymupdf.Rect(0, 0, 10, 10), pixmap=pymupdf.open(str(path))[0].get_pixmap(dpi=20))
    doc.set_metadata({"title": NAME})
    doc.save(str(tmp_path / "copy.pdf"))
    found = [f.recovered for f in check_scan_structure(tmp_path / "copy.pdf", "scan")]
    assert any("2 images" in f for f in found) and any("title" in f for f in found)


def test_the_unredacted_scan_fails_the_pixel_check(
    scan: tuple[Path, Document], tmp_path: Path
) -> None:
    path, document = scan
    done = redact_scan(path, tmp_path / "out.pdf", document, [withhold(document, 1)])
    assert check_image_pixels(path, done.regions, "scan")


def test_a_span_no_word_box_covers_is_refused_not_shipped() -> None:
    with pytest.raises(UnplacedSpan):
        rects_on_scan([], "a name here", Offsets(2, 6))


# --- the manifest and the excerpts ----------------------------------------------------------


def _record(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "file_name": "short.pdf", "title": "A short record", "source": "package.pdf",
        "source_sha256": "", "pages": [2], "request_number": "A-0000-00000",
        "institution": "Library and Archives Canada (test)", "retrieved_on": "2026-10-19",
        "details_url": "https://example.org/", "lac_disposition": "Disclosed in part",
        "shows": "test",
    }
    return {**base, **over}


def test_an_excerpt_is_built_only_from_the_package_the_manifest_names(tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    package = pymupdf.open()
    for n in range(3):
        package.new_page().insert_text((72, 72), f"page {n + 1}")
    package.save(str(releases / "package.pdf"))
    digest = hashlib.sha256((releases / "package.pdf").read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"

    manifest.write_text(json.dumps({"records": [_record(source_sha256="0" * 64)]}))
    with pytest.raises(excerpts.ExcerptError, match="sha256"):
        excerpts.build(manifest, releases, tmp_path / "out")

    manifest.write_text(json.dumps({"records": [_record(source_sha256=digest)]}))
    (built,) = excerpts.build(manifest, releases, tmp_path / "out")
    doc = pymupdf.open(str(built))
    assert doc.page_count == 1 and "page 2" in doc[0].get_text()


def test_a_record_longer_than_three_pages_is_refused(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"records": [_record(pages=[1, 2, 3, 4])]}))
    with pytest.raises(excerpts.ExcerptError, match="one to 3"):
        excerpts.read_manifest(manifest)


def test_the_committed_manifest_offers_ten_short_records() -> None:
    records = excerpts.read_manifest()
    assert len(records) == 10
    assert all(1 <= len(r.pages) <= 3 and r.details_url.startswith("https://") for r in records)
    assert len({r.source for r in records}) == 10


# --- in the demonstration ------------------------------------------------------------------


@pytest.fixture(scope="module")
def invented() -> tuple[Item, ...]:
    return demo_items(documents=1)


@pytest.fixture()
def server(
    invented: tuple[Item, ...], tmp_path: Path, scan: tuple[Path, Document]
) -> Iterator[tuple[DemoServer, Item]]:
    path, document = scan
    record = excerpts.Released(
        **{**_record(file_name=path.name), "pages": (1,)},  # type: ignore[arg-type]
    )
    released = Item(
        document=document,
        proposals=(withhold(document, 1),),
        released=replace(record, pdf=path),
    )
    s = DemoServer(items=(*invented, released), secure_cookie=False)
    yield s, released
    s.max_sessions = 0
    s.visitor(None)


def test_a_visitor_gets_the_redacted_scan_and_the_dashboard_counts_it_apart(
    server: tuple[DemoServer, Item],
) -> None:
    s, item = server
    c = TestClient(s)
    page = c.get("/review").text
    assert "Records a public body released" in page and "A short record" in page
    assert "Released by Library and Archives Canada" in c.get(f"/doc/{item.doc_id}/page/1").text
    p = item.proposals[0]
    c.post(
        f"/doc/{item.doc_id}/page/1/span",
        data={"start": p.detection.offsets.start, "end": p.detection.offsets.end, "action": "approve"},
    )
    c.post(f"/doc/{item.doc_id}/page/1/complete")
    r = c.get(f"/doc/{item.doc_id}/released.pdf")
    assert r.status_code == 200
    pdf = pymupdf.open(stream=r.content, filetype="pdf")
    # Withholding the first occurrence spread to the second, as on any record.
    assert len(pdf[0].get_images()) == 1
    assert NAME not in pdf[0].get_text()
    d = TestClient(s).get("/dashboard.json").json()
    assert d["decisions_total"] == 0 and d["agreement"]["withhold"]["decided"] == 0
    assert d["released"]["decisions"]["withhold"] == 1 and d["released"]["spread"] == 1
    assert d["released"]["records_completed"] == 1 and d["pdfs"]["scans"] == 1


# --- the real excerpts, where they have been built ------------------------------------------


@pytest.mark.skipif(
    not all((excerpts.DEFAULT_DIR / r.file_name).is_file() for r in excerpts.read_manifest()),
    reason="the excerpts are built from downloaded packages (`sever demo-records`)",
)
def test_every_real_record_redacts_clean_with_everything_personal_withheld(tmp_path: Path) -> None:
    for item in released_items():
        forced = [
            replace(p, code="R1", decision=Decision.REDACT) for p in item.proposals if p.code != "K6"
        ]
        assert item.released is not None and item.released.pdf is not None
        result = redact_scan(item.released.pdf, tmp_path / f"{item.doc_id}.pdf", item.document, forced)
        checker = LeakChecker(use_ocr=False)
        checker.check(result.path, result.regions, document=item.doc_id, scan=True)
        assert checker.report().clean, (item.doc_id, checker.report().findings)
