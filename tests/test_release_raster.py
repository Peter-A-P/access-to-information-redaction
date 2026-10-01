"""The redaction check for packages that are scans with an OCR text layer.

Library and Archives Canada publishes its completed requests as one image per page with an
invisible OCR text layer, and the boxes burned into the pixels. The vector check finds
nothing to read inside there, so these packages were excluded as unchecked. The raster
check has to accept a sound one and, more importantly, refuse one whose invisible text
layer holds words under a box, which is what a text layer copied from an unredacted
original looks like.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from sever.ingest.releases import inspect_raster, inspect_redaction

BOX = pymupdf.Rect(100, 200, 260, 222)


def scanned(path: Path, *, hidden: str | None) -> Path:
    """A one-page 'scan': a rendered page with a grey box, as an image, plus OCR text."""
    src = pymupdf.open()
    page = src.new_page(width=400, height=500)
    page.insert_text((60, 100), "Briefing note for the Minister", fontsize=12)
    page.insert_text((60, 214), "Prepared by", fontsize=12)
    page.draw_rect(BOX, color=None, fill=(0.75, 0.75, 0.75))
    pix = page.get_pixmap(dpi=150)
    out = pymupdf.open()
    scan = out.new_page(width=400, height=500)
    scan.insert_image(scan.rect, pixmap=pix)
    scan.insert_text((60, 100), "Briefing note for the Minister", fontsize=12, render_mode=3)
    if hidden is not None:
        scan.insert_text((BOX.x0 + 4, BOX.y1 - 6), hidden, fontsize=12, render_mode=3)
    out.save(str(path))
    return path


def test_a_sound_scan_is_checked_and_passes(tmp_path: Path) -> None:
    check = inspect_redaction(scanned(tmp_path / "sound.pdf", hidden=None))
    assert check.checked and check.sound
    assert check.boxes >= 1


def test_a_text_layer_with_a_word_under_a_box_fails(tmp_path: Path) -> None:
    check = inspect_redaction(scanned(tmp_path / "leaky.pdf", hidden="Bernadette Doucette"))
    assert check.checked and not check.sound
    assert check.boxes_with_text >= 1


def test_a_package_with_visible_text_is_not_a_scan(tmp_path: Path) -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "A born-digital page with visible text")
    path = tmp_path / "digital.pdf"
    doc.save(str(path))
    assert inspect_raster(path) is None
