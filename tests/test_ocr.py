"""The scan track's arithmetic, and the label that did not survive.

Most of this file needs no Tesseract, deliberately. The OCR engine is a system binary and
CI does not have one, but the parts of this track that can be wrong in a quiet,
result-changing way are all pure functions: the edit distance, the character alignment, and
the decision about what to do with a label the scan destroyed.

That last one is the one to get right. A destroyed label could be dropped, kept at its old
offsets, or kept as a zero-length span. Dropping it flatters recall by removing the hardest
cases from the denominator. Keeping it at its old offsets points at whatever characters
happen to sit there now. A zero-length span is a phantom the detector is then marked down
for missing. It is returned separately and counted, and the generated table reports the
count beside recall, because a value the scan destroyed is not a detection failure.
"""

from __future__ import annotations

import pytest

from sever.corpus.labels import LabelledSpan
from sever.ingest.document import Offsets
from sever.ingest.ocr import (
    CLEAN,
    FAX,
    PROFILES,
    SCANNER,
    Degradation,
    character_error_rate,
    edit_distance,
    paragraph_blocks,
    reproject,
)


def label(text: str, start: int, code: str = "R1") -> LabelledSpan:
    return LabelledSpan(
        page=1,
        offsets=Offsets(start, start + len(text)),
        text=text,
        code=code,
        persona_id="p1",
        field_name="third_party.surname",
    )


# --- the error rate --------------------------------------------------------------


def test_an_identical_page_has_no_error() -> None:
    assert edit_distance("Odette Tulk", "Odette Tulk") == 0
    assert character_error_rate("Odette Tulk", "Odette Tulk") == 0.0


@pytest.mark.parametrize(
    ("truth", "recovered", "distance"),
    [
        ("Tulk", "TuIk", 1),  # the classic OCR substitution, lowercase L for capital i
        ("Tulk", "Tuk", 1),  # a dropped character
        ("Tulk", "Tullk", 1),  # a doubled one
        ("Penashue", "Pcnashuc", 2),
        ("", "noise", 5),
        ("gone", "", 4),
    ],
)
def test_the_distance_is_levenshtein_and_not_an_indel_count(
    truth: str, recovered: str, distance: int
) -> None:
    """A substitution is one edit, not two.

    difflib counts a substitution as a delete plus an insert, which would inflate the error
    rate on exactly the mistake OCR makes most: reading one character as another. On
    "Tulk" against "TuIk" that is the difference between 25 percent and 50 percent.
    """
    assert edit_distance(truth, recovered) == distance


def test_the_rate_is_over_the_length_of_the_truth() -> None:
    assert character_error_rate("Tulk", "TuIk") == 0.25


def test_an_empty_truth_is_not_a_division_by_zero() -> None:
    assert character_error_rate("", "") == 0.0
    assert character_error_rate("", "hallucinated") == 0.0


# --- moving the labels -----------------------------------------------------------


def test_a_label_moves_with_the_text_that_shifted_under_it() -> None:
    """The whole reason re-projection exists: one dropped character earlier on the page
    moves every offset after it, and a label left where it was points at the wrong
    characters."""
    truth = "Dear Sir, the complainant Odette Tulk wrote."
    recovered = "Dear Sir the complainant Odette Tulk wrote."  # the comma is gone
    name = label("Odette Tulk", truth.index("Odette Tulk"))

    moved = reproject((name,), truth, recovered)

    assert len(moved.labels) == 1
    assert moved.labels[0].text == "Odette Tulk"
    assert recovered[moved.labels[0].offsets.start : moved.labels[0].offsets.end] == "Odette Tulk"


def test_a_label_whose_value_was_mangled_still_points_at_the_mangled_value() -> None:
    """A partly destroyed value is still on the page and a detector could still find it,
    so it stays in the denominator and the span covers what OCR produced."""
    truth = "The worker was Marie Chaulk that day."
    recovered = "The worker was Marie Chaulk that day.".replace("Chaulk", "Chauik")
    name = label("Marie Chaulk", truth.index("Marie Chaulk"))

    moved = reproject((name,), truth, recovered)

    assert len(moved.labels) == 1
    assert moved.destroyed == ()
    assert "Marie" in moved.labels[0].text


def test_a_label_the_scan_destroyed_is_counted_and_not_dropped() -> None:
    """The case this file exists for.

    Dropping it silently would remove the hardest values from the recall denominator and
    make the detector look better on scans than on native text, which is the opposite of
    the truth.
    """
    truth = "Reference: A1B 2C3 for the file."
    recovered = "Reference: for the file."
    postcode = label("A1B 2C3", truth.index("A1B 2C3"))

    moved = reproject((postcode,), truth, recovered)

    assert moved.labels == ()
    assert len(moved.destroyed) == 1
    assert moved.destroyed[0].text == "A1B 2C3"
    assert moved.survival == 0.0


def test_survival_is_the_share_that_made_it() -> None:
    truth = "Odette Tulk and A1B 2C3 and Marie Chaulk."
    recovered = "Odette Tulk and and Marie Chaulk."
    labels = (
        label("Odette Tulk", truth.index("Odette Tulk")),
        label("A1B 2C3", truth.index("A1B 2C3")),
        label("Marie Chaulk", truth.index("Marie Chaulk")),
    )

    moved = reproject(labels, truth, recovered)

    assert len(moved.labels) == 2
    assert len(moved.destroyed) == 1
    assert moved.survival == pytest.approx(2 / 3)


def test_every_reprojected_label_is_consistent_with_the_text_it_points_at() -> None:
    """`LabelledSpan.__post_init__` refuses a span whose text and offsets disagree, so this
    is really a test that the re-projection cannot produce one. It is worth stating
    separately because the failure would be an exception deep inside a 50-document run."""
    truth = "Aaron Penashue, Director of Records, replied on 2 April."
    recovered = "Aaron Penashuc, Dircctor of Rccords, rcplied on 2 April."
    labels = (label("Aaron Penashue", 0), label("Director of Records", truth.index("Director")))

    for moved in reproject(labels, truth, recovered).labels:
        assert recovered[moved.offsets.start : moved.offsets.end] == moved.text
        assert len(moved.text) == len(moved.offsets)


# --- what a scan does to structure ------------------------------------------------


def test_paragraphs_become_body_blocks_and_nothing_else() -> None:
    """A scan carries no semantic structure. This is the weakest honest reconstruction, and
    the point is what it costs: nothing is role-bearing, so the rules lose the signature
    block, which is the evidence they lean on hardest."""
    text = "MEMORANDUM\n\nThe complainant wrote.\n\nYours,\nA. Penashue, Director"
    blocks = paragraph_blocks(text)

    assert len(blocks) == 3
    assert not any(b.kind.is_role_bearing for b in blocks)
    for b in blocks:
        assert text[b.offsets.start : b.offsets.end] == b.text


def test_blank_input_produces_no_blocks_rather_than_one_empty_one() -> None:
    assert paragraph_blocks("") == ()
    assert paragraph_blocks("\n\n\n\n") == ()


# --- the profiles ------------------------------------------------------------------


def test_the_clean_profile_does_nothing_and_says_so() -> None:
    assert CLEAN.is_clean
    assert "no degradation" in CLEAN.describe()


def test_every_other_profile_degrades_and_describes_what_it_did() -> None:
    for name, profile in PROFILES.items():
        if name == "clean":
            continue
        assert not profile.is_clean
        assert "dpi" in profile.describe()


def test_the_profiles_are_ordered_from_easiest_to_hardest() -> None:
    """Not enforced anywhere in the code, and the generated table reads as a progression,
    so it is held here. A table whose rows are not monotone in difficulty invites the
    reader to draw a trend that is not there."""
    assert CLEAN.dpi >= SCANNER.dpi > PROFILES["photocopy"].dpi > FAX.dpi
    assert SCANNER.blur_radius < PROFILES["photocopy"].blur_radius < FAX.blur_radius
    assert SCANNER.noise_sigma < PROFILES["photocopy"].noise_sigma < FAX.noise_sigma


def test_the_same_page_scans_the_same_way_twice() -> None:
    """The sensor noise is seeded per page, so a rerun of the track is the same scan rather
    than a new one. Without this the scan track would be unreproducible and every rerun
    would move the published number a little."""
    a = Degradation(seed=7)
    b = Degradation(seed=7)
    assert a == b
    assert a.describe() == b.describe()
