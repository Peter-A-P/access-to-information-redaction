"""Redaction is destructive, and this is the test that says so.

Two halves. The first proves the tool removes text: every applied box is checked and must
contain nothing. The second proves the *test itself* works, by building a deliberately
broken export (a black rectangle drawn over the text, which is the real-world failure) and
asserting that the checker catches it. A leak test that has never caught a leak is not
evidence of anything.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from sever.context.requester import RequestConfig
from sever.corpus.personas import PersonaRole
from sever.decide.pipeline import DecisionEngine
from sever.eval.pdf_leak import LeakChecker, check_text_layer
from sever.review.export import (
    RedactedRegion,
    apply_redactions,
    build_schedule,
    extract_text,
    lay_out,
    rects_for,
    render_pdf,
)


def test_no_redacted_box_has_recoverable_text(corpus, detector, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    checker = LeakChecker(use_ocr=False)
    for item in corpus:
        doc = item.rendered.document
        requester = next(
            (p for p in item.rendered.cast.values() if p.role is PersonaRole.REQUESTER), None
        )
        config = RequestConfig(
            request_id=doc.doc_id, requester_name=requester.full_name if requester else ""
        )
        proposals = DecisionEngine(config=config, detector=detector).propose(doc)
        source = render_pdf(doc, tmp_path / f"{doc.doc_id}.pdf")
        result = apply_redactions(
            source, tmp_path / f"{doc.doc_id}-released.pdf", doc, proposals
        )
        checker.check(result.path, result.regions, document=doc.doc_id)

    report = checker.report()
    assert report.boxes_tested > 0, "nothing was redacted, so this test proved nothing"
    assert report.clean, (
        f"{report.recoverable} redactions left recoverable text:\n  "
        + "\n  ".join(str(f) for f in report.findings[:10])
    )


def test_the_checker_catches_a_box_that_only_covers(tmp_path: Path) -> None:
    """The failure this project refuses to ship, built on purpose."""
    path = tmp_path / "covered.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((50, 100), "Marie Doucette", fontname="cour", fontsize=10)
    rect = pymupdf.Rect(48, 88, 160, 104)
    # A filled rectangle over the top. Looks redacted, is not.
    page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(str(path))
    doc.close()

    from sever.ingest.document import BBox

    region = RedactedRegion(
        page=1, bbox=BBox(*rect), text="Marie Doucette", code="R1"
    )
    findings, _ = check_text_layer(path, [region], "covered")
    assert findings, "the checker passed a document where the text is still selectable"
    assert "Doucette" in findings[0].recovered


def test_redaction_actually_shortens_the_text_layer(corpus, detector, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    item = corpus.items[0]
    doc = item.rendered.document
    proposals = DecisionEngine(
        config=RequestConfig(request_id=doc.doc_id), detector=detector
    ).propose(doc)
    source = render_pdf(doc, tmp_path / "before.pdf")
    result = apply_redactions(source, tmp_path / "after.pdf", doc, proposals)
    assert result.boxes > 0
    before = len(extract_text(source))
    after = len(extract_text(result.path))
    assert after < before, (
        f"the text layer did not shrink ({before} to {after}); the boxes were drawn but "
        f"apply_redactions did not remove anything"
    )


def test_layout_covers_every_character(corpus) -> None:  # type: ignore[no-untyped-def]
    """A character that is not laid out is never rendered and can never be redacted."""
    for item in corpus:
        for page in item.rendered.document:
            segments = lay_out(page.text)
            covered = sum(len(s.text) for s in segments)
            # Newlines and the spaces consumed at wrap points are not rendered, so the
            # rendered count is at most the text length; what must not happen is a large
            # shortfall, which would mean text silently dropped off the page.
            assert covered >= len(page.text.replace("\n", "")) * 0.95, (
                f"{item.doc_id} page {page.number}: only {covered} of "
                f"{len(page.text)} characters were laid out"
            )


def test_a_span_maps_to_at_least_one_rectangle(corpus, detector) -> None:  # type: ignore[no-untyped-def]
    for item in corpus.items[:4]:
        doc = item.rendered.document
        for detection in detector.detect(doc):
            page = doc.page(detection.page)
            rects = rects_for(page, detection.offsets)
            assert rects, (
                f"{doc.doc_id} p{detection.page}: {detection.text!r} at "
                f"{detection.offsets} maps to no rectangle, so it could never be redacted"
            )


def test_the_schedule_lists_every_withheld_span(corpus, detector) -> None:  # type: ignore[no-untyped-def]
    item = corpus.items[0]
    doc = item.rendered.document
    proposals = DecisionEngine(
        config=RequestConfig(request_id=doc.doc_id), detector=detector
    ).propose(doc)
    schedule = build_schedule(doc.doc_id, doc, tuple(proposals))
    assert len(schedule.rows) == len(proposals.withheld)
    markdown = schedule.to_markdown()
    assert "Schedule of severances" in markdown
    for row in schedule.rows:
        assert row[2], "a schedule row has no category"
