"""The real-record track, and the guard that decides whether a package can be used at all.

No real release package is committed, so every test here builds a PDF that stands in for
one. That is a weaker test of the loader than real data would be and a perfectly good test
of the two things that can go wrong quietly:

  1. **A package whose boxes still have text under them must be excluded.** Its visible text
     carries values a reviewer decided to withhold. Score it and this tool is marked down
     for proposing to redact exactly the spans the reviewer redacted, which would be a
     measurement that punishes agreement.
  2. **A file that does not match its checksum must be refused.** The manifest is committed
     and the PDFs are not, so the entire reproducibility claim of this track is that someone
     else can obtain the same bytes. A file that differs is not the file the number came
     from, and reporting on it anyway would quietly break that claim.

The measurement itself needs no fixture beyond a page of text: over-redaction here is the
share of visible spans the tool would box, and a page with names on it exercises that.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from sever.eval.releases import RELEASED_BY_DESIGN, ReleaseResult, VisibleSpan
from sever.eval.releases import run as run_releases
from sever.ingest.document import BlockKind
from sever.ingest.releases import (
    ManifestError,
    add,
    inspect_redaction,
    load,
    read_manifest,
    sha256_of,
    to_document,
    verify,
)

TEXT = (
    "MEMORANDUM TO THE DEPUTY MINISTER\n\n"
    "The complainant Odette Tulk wrote to the Department of Health on 14 March.\n\n"
    "Her file is HCS-2021-7489 and her telephone number is 709-555-0134.\n\n"
    "Prepared by Aaron Penashue, Director of Records, St. John's.\n"
)


def a_pdf(path: Path, *, box_over_text: bool = False, boxes: bool = True) -> Path:
    """A stand-in for a released package.

    `box_over_text` draws a rectangle and leaves the text under it, which is the real
    redaction failure this track has to detect in somebody else's file.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((54, 90), TEXT, fontname="cour", fontsize=10)
    if boxes:
        rect = pymupdf.Rect(54, 150, 260, 165)
        if box_over_text:
            page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0))
        else:
            page.add_redact_annot(rect, fill=(0, 0, 0))
            page.apply_redactions()
            page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


# --- the guard on somebody else's redactions ---------------------------------------


def test_a_box_with_live_text_under_it_is_detected(tmp_path: Path) -> None:
    """The failure that makes a package unusable, and it is not the package's fault that
    matters here: it is that its visible text would become must-keep labels."""
    check = inspect_redaction(a_pdf(tmp_path / "bad.pdf", box_over_text=True))

    assert check.checked
    assert check.boxes > 0
    assert check.boxes_with_text > 0
    assert not check.sound


def test_a_properly_redacted_package_passes(tmp_path: Path) -> None:
    check = inspect_redaction(a_pdf(tmp_path / "good.pdf"))

    assert check.checked
    assert check.boxes > 0
    assert check.boxes_with_text == 0
    assert check.sound


def test_a_package_with_no_boxes_is_unchecked_rather_than_sound(tmp_path: Path) -> None:
    """Not the same as passing. A scan, or a package redacted by deleting text without
    drawing anything, gives nothing to check, and saying "sound" would claim a check that
    did not happen."""
    check = inspect_redaction(a_pdf(tmp_path / "plain.pdf", boxes=False))

    assert not check.checked
    assert not check.sound
    assert "nothing could be checked" in check.note


def test_an_unsound_package_is_excluded_from_the_measurement(tmp_path: Path) -> None:
    root = tmp_path / "releases"
    manifest = root / "manifest.json"
    add(
        a_pdf(root / "bad.pdf", box_over_text=True),
        source_url="https://example.invalid/bad.pdf",
        manifest=manifest,
    )

    loaded = load(manifest, root)

    assert loaded.releases == []
    assert len(loaded.excluded) == 1
    assert "still have text under them" in loaded.excluded[0]


# --- the checksum, which is the whole reproducibility claim -------------------------


def test_a_file_that_does_not_match_its_checksum_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "releases"
    manifest = root / "manifest.json"
    pdf = a_pdf(root / "one.pdf")
    add(pdf, source_url="https://example.invalid/one.pdf", manifest=manifest)

    a_pdf(root / "one.pdf", boxes=False)  # the same name, different bytes

    good, problems = verify(read_manifest(manifest), root)

    assert good == ()
    assert len(problems) == 1
    assert "not the file that was measured" in problems[0]


def test_a_package_in_the_manifest_but_not_downloaded_says_where_to_put_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "releases"
    manifest = root / "manifest.json"
    pdf = a_pdf(root / "gone.pdf")
    add(pdf, source_url="https://example.invalid/gone.pdf", manifest=manifest)
    pdf.unlink()

    _, problems = verify(read_manifest(manifest), root)

    assert "not downloaded" in problems[0]
    assert "gone.pdf" in problems[0]


def test_adding_the_same_file_twice_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    root = tmp_path / "releases"
    manifest = root / "manifest.json"
    pdf = a_pdf(root / "one.pdf")
    add(pdf, source_url="https://example.invalid/first", manifest=manifest)
    add(pdf, source_url="https://example.invalid/second", manifest=manifest)

    records = read_manifest(manifest)

    assert len(records) == 1
    assert records[0].source_url == "https://example.invalid/second"


def test_the_manifest_records_what_a_reader_needs_to_obtain_the_same_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "releases"
    manifest = root / "manifest.json"
    pdf = a_pdf(root / "one.pdf")

    record = add(
        pdf,
        source_url="https://example.invalid/one.pdf",
        institution="Library and Archives Canada",
        request_number="A-2024-00001",
        manifest=manifest,
    )

    assert record.sha256 == sha256_of(pdf)
    assert record.source_url and record.retrieved_on and record.institution
    assert read_manifest(manifest) == (record,)


def test_adding_a_file_that_is_not_there_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="no file at"):
        add(tmp_path / "absent.pdf", source_url="x", manifest=tmp_path / "m.json")


# --- reading the visible text -------------------------------------------------------


def test_the_document_carries_the_visible_text_and_not_the_redacted_text(
    tmp_path: Path,
) -> None:
    doc = to_document(a_pdf(tmp_path / "one.pdf"), "one.pdf")
    text = "\n".join(p.text for p in doc)

    assert "Odette Tulk" in text, "visible text is what a reviewer released"
    assert doc.page(1).blocks, "paragraphs are recovered as blocks"


def test_without_recovery_every_block_is_body(tmp_path: Path) -> None:
    """How this track was scored until 2026-10-17, kept so the ablation in
    results/releases.md can show what the recovery is worth. Nothing in the file says which
    paragraph was a signature block, so a flat reading has none."""
    doc = to_document(a_pdf(tmp_path / "one.pdf"), "one.pdf", recover_layout=False)

    assert doc.page(1).blocks
    assert all(b.kind is BlockKind.BODY for b in doc.page(1).blocks)


def test_a_released_signature_block_is_read_back_from_the_text(tmp_path: Path) -> None:
    """The point of recovering the layout: a name on its own line with a title under it is
    a signature in a released PDF as much as in a native one."""
    path = tmp_path / "signed.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(
        (54, 90),
        "I write to confirm the arrangements described in your letter of 3 May,\n"
        "which are acceptable to the Department.\n\n"
        "Chris McGuffin\nLCol (OF-4)\nCO TFK HQ & Sig Sqn",
        fontname="cour",
        fontsize=10,
    )
    doc.save(str(path))
    doc.close()

    blocks = to_document(path, "signed.pdf").page(1).blocks

    signature = [b for b in blocks if b.kind is BlockKind.SIGNATURE]
    assert signature and "Chris McGuffin" in signature[0].text
    assert "LCol" in signature[0].text


# --- the measurement -----------------------------------------------------------------


def test_over_redaction_is_the_share_of_visible_spans_the_tool_would_box(  # type: ignore[no-untyped-def]
    tmp_path: Path, detector
) -> None:
    root = tmp_path / "releases"
    manifest = root / "manifest.json"
    add(
        a_pdf(root / "one.pdf"),
        source_url="https://example.invalid/one.pdf",
        institution="Test Department",
        manifest=manifest,
    )

    result = run_releases(manifest=manifest, root=root, detector=detector)

    assert result.packages == 1
    assert result.spans, "nothing was detected, so this proved nothing"
    rate = result.over_redaction()
    assert rate.is_defined
    assert 0.0 <= rate.point <= 1.0
    assert "Track: real releases" in result.to_markdown()


def test_the_types_the_tool_releases_by_design_are_counted_separately() -> None:
    """A package full of department names would move a blended rate without saying anything
    about a decision anybody would argue with, so the two denominators are both printed."""
    from sever.decide.pipeline import Proposal, Source
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import Offsets
    from sever.taxonomy.loader import Decision

    def span(kind: EntityType, withholds: bool) -> VisibleSpan:
        return VisibleSpan(
            doc_id="d1",
            proposal=Proposal(
                detection=Detection(
                    page=1,
                    offsets=Offsets(0, 4),
                    text="Tulk",
                    entity_type=kind,
                    score=0.9,
                    recogniser="test",
                ),
                code="R1" if withholds else "K6",
                decision=Decision.REDACT if withholds else Decision.KEEP,
                confidence=0.9,
                reason="test",
                source=Source.RULE,
            ),
        )

    result = ReleaseResult(
        packages=1,
        pages=1,
        spans=(
            span(EntityType.PERSON, True),
            span(EntityType.PERSON, False),
            *[span(EntityType.ORGANISATION, False) for _ in range(8)],
        ),
    )

    assert len(result.personal_candidates) == 2
    assert result.over_redaction().point == pytest.approx(0.5)
    assert result.over_redaction(all_types=True).point == pytest.approx(0.1)


def test_an_empty_track_says_how_to_populate_it_rather_than_reporting_zero() -> None:
    body = ReleaseResult().to_markdown()

    assert "No release packages have been added yet" in body
    assert "sever releases add" in body
    assert "0.0%" not in body, "a rate of zero would read as a perfect score"


def test_the_types_released_by_design_are_the_ones_the_rules_release() -> None:
    """Held so that adding a releasing type to the rules and forgetting it here is a visible
    omission. The set exists to keep those out of the headline denominator."""
    from sever.detect.sweep import _RELEASING_TYPES

    assert _RELEASING_TYPES <= RELEASED_BY_DESIGN
