"""The generated block is the one part of the README nobody reviews before it lands.

`sever report --readme README.md` rewrites the results block in place. That is the whole
point: no published number is typed by hand. The cost is that the block is the only part of
the document that changes without a person reading the diff, so a run that produces less
than the last one silently deletes a published result and reports success.

That happened on 2026-09-20. `sever report --readme README.md --no-pdf-leak` removed the PDF
leak table, printed "README.md: updated", and exited zero. Nothing was wrong with the run.
The flag did what it says. The mistake was letting a partial run overwrite a complete one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sever.eval.report import (
    REQUIRED_SECTIONS,
    SpliceWouldRemoveASection,
    missing_sections,
    splice_into_readme,
)

COMPLETE = "\n\n".join(("**Against the baselines**", "x", "**Where the leaks come from**", "y", "**PDF leak test**", "z"))
PARTIAL = "\n\n".join(("**Against the baselines**", "x", "**Where the leaks come from**", "y"))


def readme_with(block: str, tmp_path: Path) -> Path:
    path = tmp_path / "README.md"
    path.write_text(
        f"# Title\n\n<!-- BEGIN RESULTS -->\n\n{block}\n\n<!-- END RESULTS -->\n\nAfter.\n",
        encoding="utf-8",
    )
    return path


def test_a_run_that_would_delete_a_published_section_is_refused(tmp_path: Path) -> None:
    """The case that happened. The command said "updated" and a result disappeared."""
    readme = readme_with(COMPLETE, tmp_path)

    with pytest.raises(SpliceWouldRemoveASection, match="PDF leak test"):
        splice_into_readme(readme, PARTIAL)

    assert "**PDF leak test**" in readme.read_text(encoding="utf-8"), "and nothing was written"


def test_a_complete_run_splices_normally(tmp_path: Path) -> None:
    readme = readme_with(PARTIAL, tmp_path)
    assert splice_into_readme(readme, COMPLETE)
    assert "**PDF leak test**" in readme.read_text(encoding="utf-8")


def test_a_partial_run_into_a_partial_readme_is_allowed(tmp_path: Path) -> None:
    """The guard is about losing something, not about being complete. A README that has
    never published the leak table is not made worse by a run without it."""
    readme = readme_with(PARTIAL, tmp_path)
    assert not splice_into_readme(readme, PARTIAL), "identical content, so no write"


def test_an_unchanged_block_reports_no_change(tmp_path: Path) -> None:
    readme = readme_with(COMPLETE, tmp_path)
    assert not splice_into_readme(readme, COMPLETE)


def test_missing_markers_are_an_error_rather_than_an_append(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text("# No markers here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no result markers"):
        splice_into_readme(path, COMPLETE)


def test_the_guarded_sections_are_the_ones_the_readme_publishes() -> None:
    """Held so that adding a table to the generated block and forgetting to guard it is a
    visible omission rather than an invisible one."""
    published = Path("README.md").read_text(encoding="utf-8")
    for heading in REQUIRED_SECTIONS:
        assert heading in published, f"{heading} is guarded but not published"


def test_only_sections_the_readme_already_has_are_required(tmp_path: Path) -> None:
    assert missing_sections(PARTIAL, COMPLETE) == ()
    assert missing_sections(COMPLETE, PARTIAL) == ("**PDF leak test**",)
