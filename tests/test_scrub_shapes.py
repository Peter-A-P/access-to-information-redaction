"""The detector-independent scrub, against the name shapes of this province.

`scrub_unrecognised` is the backstop. `docs/rejected.md` says in as many words that a
privacy boundary whose strength equals a detector's recall is not a boundary, and this
function is what that sentence is about: it masks anything name-shaped whether or not
anything detected it.

It was ASCII, and so it was not a backstop for anyone whose name has an accent, an
apostrophe or a Mac. `Renee` with an acute accent and `MacDonald` passed through it
completely untouched, and `O'Brien` came out as `O'[NAME?]`.

The corpus could not see this. All 5,355 labelled spans were plain ASCII single-token
names, so every test passed and the number published was measured on an easier problem
than the province the tool is named after. The report came from outside: project 04 found
the same three shapes getting past their own second pass and warned that re-running this
project's evaluation would not show the difference. It did not, to the decimal.

So the shapes live here as fixtures, and `NameProfile.NL` puts them in a corpus.
"""

from __future__ import annotations

import pytest

from sever.decide.placeholders import UNKNOWN_NAME, scrub_unrecognised

# Written as escapes rather than literals so that a file re-encoded by an editor cannot
# quietly turn this test into the ASCII one it exists to replace.
SEAN = "Seán"
RENEE = "Renée"
DUHE = "Duhé"
BENOIT = "Benoît"


@pytest.mark.parametrize(
    "name",
    [
        SEAN,
        RENEE,
        DUHE,
        BENOIT,
        "O'Brien",
        "O'Keefe",
        "D'Arcy",
        "MacDonald",
        "MacKenzie",
        "McCarthy",
        "McGrath",
        "Coady-Vokey",
        "Anne-Marie",
        "Penashue",
        "Noseworthy",
    ],
)
def test_a_name_is_masked_whole(name: str) -> None:
    """Whole, not partly. A surname with its first two letters left behind is still a
    surname, and `O'[NAME?]` was what this function used to produce."""
    out = scrub_unrecognised(f"The complainant is {name} of Torbay.")
    assert name not in out, f"{name!r} survived the scrub: {out!r}"
    assert UNKNOWN_NAME in out
    for fragment in ("Mac", "Mc", "O'", "D'"):
        if name.startswith(fragment) and fragment.rstrip("'").isalpha():
            assert f"{fragment}{UNKNOWN_NAME}" not in out, (
                f"only part of {name!r} was masked: {out!r}"
            )


@pytest.mark.parametrize(
    "text",
    [
        "CASE NOTES",
        "ATIPPA",
        "MCP",
        "The Deputy Minister of Health and Community Services",
        "Newfoundland and Labrador Health Services",
        "Department of Justice and Public Safety",
        "Monday 14 January",
        "Access to Information and Protection of Privacy Act",
    ],
)
def test_what_the_model_needs_to_reason_with_survives(text: str) -> None:
    """The other half of the trade. Over-masking is the safe direction but it is not free:
    a model that cannot see the title, the public body or the month has nothing left to
    decide K2, K3 or K4 with."""
    assert scrub_unrecognised(text) == text


def test_an_all_capitals_token_is_not_masked() -> None:
    """Deliberate, and inherited from the pattern this replaced. An all-capitals token is
    a heading or an acronym, and a page of masked headings tells the model nothing."""
    assert scrub_unrecognised("SUBJECT: CASE REVIEW") == "SUBJECT: CASE REVIEW"


def test_a_compound_of_safe_words_survives_but_a_compound_with_an_unknown_part_does_not() -> None:
    assert scrub_unrecognised("Newfoundland-Labrador") == "Newfoundland-Labrador"
    assert scrub_unrecognised("Coady-Vokey") == UNKNOWN_NAME


def test_boundary_placeholders_pass_through_untouched() -> None:
    """`LayeredPolicy` runs this scrub over text project 04's policy has already
    substituted, so mangling `<PERSON_1>` here would break their rehydration and, with it,
    the reviewer's ability to see what was sent."""
    text = "<PERSON_1> met <PERSON_2.1> and <HEALTH_NUMBER_1> was discussed."
    assert scrub_unrecognised(text) == text


def test_initials_and_short_particles_are_left_alone() -> None:
    """Two letters identify nobody, and masking "St" would take the saint out of every
    place name in the province."""
    out = scrub_unrecognised("St. John's and Mt. Pearl")
    assert out.startswith("St.")
