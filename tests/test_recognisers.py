"""The pattern recognisers, against the strings that broke them.

There was no test file here until two bugs of the same shape had shipped, and both were in
the same place: a recogniser that keys off a label word ("case", "file", "ref") and then
captures whatever follows. The failure mode is not a missed entity, which the corpus-wide
recall evaluation would see. It is a *false* entity over ordinary prose, which recall
cannot see at all, because recall only asks whether the things that are there were found.

  * `ref` matched inside "referred" and the group captured "erred", putting a redaction
    box over the middle of a word.
  * "CASE NOTES" matched and "NOTES" was proposed as a case number, which then travelled
    to the model as a span to categorise and came back confidently miscategorised.

The second survived a full corpus evaluation and was caught by a human reading six
proposals on the first live model run. So the point of this file is that the adversarial
strings are written down and checked, rather than rediscovered.
"""

from __future__ import annotations

import pytest

from sever.detect.engine import SeverDetector
from sever.detect.recognisers import (
    CASE_NUMBER,
    EMAIL,
    EMPLOYEE_ID,
    FILE_NUMBER,
    MCP_NUMBER,
    POSTAL_CODE,
    SIN_LABELLED,
    SIN_NUMBER,
    STREET_ADDRESS,
    PatternRecogniser,
)
from sever.detect.types import EntityType
from sever.ingest.document import BlockKind

from .conftest import make_document


def matches(recogniser: PatternRecogniser, text: str) -> list[str]:
    return [m[2] for m in recogniser.finditer(text)]


# --- the label-word recognisers, which is where both bugs were ----------------


@pytest.mark.parametrize(
    "text",
    [
        "CASE NOTES",
        "Case Notes - continued",
        "case REVIEW",
        "file REPORT",
        "The matter was referred 2024",
        "as referenced above",
        "Reference: PENDING",
        "file CLOSED",
    ],
)
def test_a_label_word_beside_ordinary_prose_is_not_a_case_number(text: str) -> None:
    """A case number contains a digit. Everything here is a word that happens to follow a
    label, and redacting any of it would black out ordinary text in a released record."""
    assert matches(CASE_NUMBER, text) == [], f"{text!r} was read as a case number"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Case No. HCS-2024-0881", "HCS-2024-0881"),
        ("file HCS-2021-7489", "HCS-2021-7489"),
        ("request 2026-0042", "2026-0042"),
        ("Reference: ABC-1234", "ABC-1234"),
        ("ref A-2023-00412", "A-2023-00412"),
    ],
)
def test_a_real_case_number_still_matches(text: str, expected: str) -> None:
    """The guards must not cost recall on the thing the recogniser is for. A-2023-00412 is
    the shape the published federal releases use."""
    assert matches(CASE_NUMBER, text) == [expected]


def test_the_label_is_not_redacted_only_the_value() -> None:
    """The group exists so the schedule reads "HCS-2024-0881 withheld" rather than
    "Case No. HCS-2024-0881 withheld", which would black out the word telling the reader
    what kind of thing was removed."""
    assert matches(CASE_NUMBER, "Case No. HCS-2024-0881") == ["HCS-2024-0881"]


@pytest.mark.parametrize(
    "text", ["Staff meeting", "employee handbook", "payroll policy", "staff 12"]
)
def test_a_label_word_without_an_identifier_is_not_an_employee_id(text: str) -> None:
    assert matches(EMPLOYEE_ID, text) == []


def test_an_employee_id_matches() -> None:
    assert matches(EMPLOYEE_ID, "Employee ID: EMP-40912") == ["EMP-40912"]
    assert matches(EMPLOYEE_ID, "staff no. 12345") == ["12345"]


# --- the email pattern, which was silently dead for a while -------------------


def test_a_multi_label_government_domain_is_an_email() -> None:
    """The reason this recogniser exists: Presidio missed this address outright and typed
    only the "gov.nl.ca" inside it as a URL. A missed work address is a leak.

    It is also the pattern that was once broken by a literal backspace character written
    into it in place of a word boundary, which made it match nothing at all while still
    compiling. A dead recogniser is silent, so it gets a test.
    """
    found = matches(EMAIL, "write to aaronpenashue@gov.nl.ca.example for a copy")
    assert found == ["aaronpenashue@gov.nl.ca.example"]


def test_an_apostrophe_in_a_local_part_survives() -> None:
    assert matches(EMAIL, "s.o'brien@gov.nl.ca") == ["s.o'brien@gov.nl.ca"]


# --- the identifiers whose context requirement is doing real work -------------


def test_twelve_grouped_digits_need_the_health_context() -> None:
    """Twelve digits in threes also describe a purchase order and a phone number written
    oddly. Without the label this recogniser would redact both."""
    assert matches(MCP_NUMBER, "purchase order 551 456 120 783") == []
    assert matches(MCP_NUMBER, "MCP 551 456 120 783") == ["551 456 120 783"]


def test_a_label_a_sentence_away_still_counts_for_an_mcp_number() -> None:
    """The incident report's sentence, which reviewer 1 approved twice with the last
    three digits proposed for release."""
    text = "Aaron's MCP number, taken\nfor the ambulance service, is 404 474 556 704 and"
    assert matches(MCP_NUMBER, text) == ["404 474 556 704"]


def test_a_sin_is_never_nine_digits_out_of_a_longer_number() -> None:
    """A span that cuts a number releases the rest of it."""
    assert matches(SIN_NUMBER, "the number is 404 474 556 704 and") == []
    assert matches(SIN_NUMBER, "the number is 404 474 556-704 and") == []
    assert matches(SIN_NUMBER, "ref 12 404 474 556") == []
    assert matches(SIN_NUMBER, "SIN 046 454 286, on file") == ["046 454 286"]


def test_the_whole_mcp_number_is_detected_and_none_of_it_as_a_sin(
    detector: SeverDetector,
) -> None:
    doc = make_document(
        [
            (
                BlockKind.BODY,
                "Gerald's MCP number, taken\nfor the ambulance service, is 404 474 556 704 "
                "and the contact number given was 709-555-1755.",
            )
        ]
    )
    found = [(d.text, d.entity_type) for d in detector.detect(doc) if d.text[0].isdigit()]
    assert ("404 474 556 704", EntityType.HEALTH_NUMBER) in found
    assert not any(t is EntityType.SIN for _, t in found)


def test_a_labelled_social_insurance_number_matches_without_its_label() -> None:
    assert matches(SIN_LABELLED, "SIN: 046 454 286") == ["046 454 286"]


def test_a_postal_code_stands_alone() -> None:
    assert matches(POSTAL_CODE, "St. John's, NL A1B 2C3") == ["A1B 2C3"]


def test_a_file_number_matches_the_published_federal_shape() -> None:
    assert matches(FILE_NUMBER, "request A-2023-00412 refers") == ["A-2023-00412"]


def test_a_street_address_keeps_its_house_number() -> None:
    """The house number is the part that identifies, and it is the part a LOCATION
    detection drops. Project 04's analyzer released it until 0.5.1 resolved containment
    before score; this project's resolver orders by specificity and never did."""
    assert matches(STREET_ADDRESS, "lives at 14 Bannerman Street") == ["14 Bannerman Street"]
