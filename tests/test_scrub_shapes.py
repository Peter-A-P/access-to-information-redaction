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


# --- the shapes the second pass could not see --------------------------------------


def test_an_email_address_is_masked_even_though_nothing_detected_it() -> None:
    """Project 04, 2026-09-20, on finding this hole in their own second pass:
    therese.gagne@example.gov.nl.ca "matched neither layer... an address carrying no digit
    is not identifier-shaped and a lowercase word is not name-shaped. It left in clear with
    no refusal."

    It was here too. This project's EMAIL recogniser happens to find these, so the
    corpus-wide test passed and this layer was never asked the question. Presidio has
    already missed an address here once, and on that occasion nothing would have caught it.
    """
    assert scrub_unrecognised("therese.gagne@example.gov.nl.ca") == "[EMAIL?]"
    assert scrub_unrecognised("a.penashue@gov.nl.ca.example") == "[EMAIL?]"


def test_an_accented_address_is_masked_too() -> None:
    """The corpus cannot produce one of these: `_slug` transliterates before it builds an
    address, so every generated email is ASCII. An internationalised address is ordinary in
    a province with French, Innu and Mi'kmaq names, and a test is the only thing standing
    between this layer and a shape the corpus will never show it."""
    accented = "th\u00e9r\u00e8se.gagn\u00e9@example.gov.nl.ca"
    assert scrub_unrecognised(accented) == "[EMAIL?]"


def test_the_whole_address_goes_and_not_just_its_name_shaped_parts() -> None:
    """The word pass would otherwise chew an address into masked fragments and leave the
    domain standing, which reads as scrubbed and is not. The order of the passes is what
    makes this true, so it is asserted rather than assumed."""
    out = scrub_unrecognised("Write to Marie.Chaulk@gov.nl.ca.example before Friday.")
    assert "gov.nl.ca" not in out
    assert "Chaulk" not in out
    assert "[EMAIL?]" in out


def test_a_postal_code_is_masked() -> None:
    """Six characters that identify a household in a rural community, and caught by neither
    existing pass: all caps so not name-shaped, starts with a letter so the digit run does
    not reach it."""
    assert scrub_unrecognised("A1B 2C3") == "[POSTCODE?]"
    assert scrub_unrecognised("A1B2C3") == "[POSTCODE?]"
    assert "[POSTCODE?]" in scrub_unrecognised("The address is 14 Bannerman Street, A1C 5H6.")


def test_a_year_still_survives_both_new_passes() -> None:
    """K4 turns on how long ago someone died, so the year is the evidence. Neither new
    pattern may eat one."""
    assert scrub_unrecognised("The death was recorded in 2024.") == (
        "The death was recorded in 2024."
    )


def test_ordinary_prose_is_not_mistaken_for_an_address() -> None:
    """The cost of a shape-based mask is what it fires on by accident, so the cases that
    look like an address and are not belong here."""
    assert "[EMAIL?]" not in scrub_unrecognised("Discussed the matter at 3 p.m. on Tuesday.")
    assert "[EMAIL?]" not in scrub_unrecognised("See section 40(2)(f) of the Act.")
    assert "[POSTCODE?]" not in scrub_unrecognised("Case HCS-2021-7489 was opened.")
