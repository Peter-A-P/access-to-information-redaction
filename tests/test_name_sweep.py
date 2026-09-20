"""The document-wide name sweep: what it recovers, and what it must not touch.

The sweep exists because of a measurement. `results/names.md` attributes the person-recall
loss on this province's names to position rather than spelling: an unfamiliar token
standing alone is missed, the same token with a forename or an honorific beside it is
found. The document usually contains the evidence somewhere, so after the page detectors
run, every person they found licenses the other whole-word occurrences of their name parts
across the whole record.

Its risks are the mirror of its benefit and are what most of this file is about. A sweep
that is too eager puts redaction boxes over ordinary words in a released record, which is
the failure the blunt baseline exists to shame. So the matching is case-sensitive and
whole-word, vocabulary words are refused, and nothing is swept over a span a real detector
already claimed.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from sever.detect.sweep import RECOGNISER, sweep, sweepable_parts, with_sweep
from sever.detect.types import Detection, EntityType
from sever.ingest.document import BlockKind, Offsets

from .conftest import make_document


def person(text: str, *, page: int = 1, start: int = 0) -> Detection:
    return Detection(
        page=page,
        offsets=Offsets(start, start + len(text)),
        text=text,
        entity_type=EntityType.PERSON,
        score=0.9,
        recogniser="test",
    )


# --- which parts a name licenses ----------------------------------------------


def test_a_two_token_surname_is_licensed_as_a_unit() -> None:
    """The shape the sweep was built for. Without the token runs, "Le Drew" would be
    swept as "Drew" alone and a box would cover half a surname."""
    parts = sweepable_parts([person("Bernadette Le Drew")])
    assert "Le Drew" in parts
    assert "Bernadette Le Drew" in parts
    assert "Drew" in parts
    # "Le" on its own is too short to sweep, which is why the run is needed.
    assert "Le" not in parts


def test_the_longest_claim_comes_first() -> None:
    parts = sweepable_parts([person("Bernadette Le Drew")])
    assert parts[0] == "Bernadette Le Drew"


def test_a_vocabulary_word_typed_as_a_person_is_not_swept() -> None:
    """The detector types the heading "Minutes" as a PERSON from time to time. Sweeping it
    would black out the word in every minute in the corpus: a denial of service on the
    reviewer, not a privacy gain."""
    assert sweepable_parts([person("Minutes")]) == []
    assert sweepable_parts([person("January")]) == []


def test_a_lowercase_or_short_fragment_is_not_swept() -> None:
    assert "de" not in sweepable_parts([person("Marie de Souza")])
    assert sweepable_parts([person("Li")]) == []


def test_only_people_license_a_sweep() -> None:
    organisation = Detection(
        page=1,
        offsets=Offsets(0, 10),
        text="Providence",
        entity_type=EntityType.ORGANISATION,
        score=0.9,
        recogniser="test",
    )
    assert sweepable_parts([organisation]) == []


# --- what the sweep finds in a document ---------------------------------------


def test_a_bare_surname_elsewhere_in_the_document_is_recovered() -> None:
    doc = make_document(
        [
            (BlockKind.BODY, "The complainant Bernadette Le Drew wrote in March."),
            (BlockKind.BODY, "Present: Le Drew, Hugh Mercer."),
        ]
    )
    found = sweep(doc, [person("Bernadette Le Drew", start=16)])
    assert "Le Drew" in [d.text for d in found]
    assert all(d.recogniser == RECOGNISER for d in found)
    assert all(d.entity_type is EntityType.PERSON for d in found)


def test_a_swept_span_indexes_the_text_it_claims() -> None:
    """The contract every redaction box downstream depends on."""
    doc = make_document(
        [
            (BlockKind.BODY, "Bernadette Le Drew wrote."),
            (BlockKind.BODY, "Le Drew attended and Bernadette signed."),
        ]
    )
    for d in sweep(doc, [person("Bernadette Le Drew")]):
        assert doc.page(d.page).slice(d.offsets) == d.text


def test_nothing_is_swept_over_an_existing_detection() -> None:
    doc = make_document([(BlockKind.BODY, "Bernadette Le Drew wrote to the department.")])
    existing = [person("Bernadette Le Drew")]
    for d in sweep(doc, existing):
        for e in existing:
            assert not (d.page == e.page and d.offsets.overlaps(e.offsets))


def test_two_swept_spans_never_overlap_each_other() -> None:
    doc = make_document(
        [
            (BlockKind.BODY, "Bernadette Le Drew wrote."),
            (BlockKind.BODY, "Bernadette Le Drew attended again."),
        ]
    )
    found = sorted(sweep(doc, [person("Bernadette Le Drew")]), key=lambda d: d.offsets.start)
    for a, b in pairwise(found):
        if a.page == b.page:
            assert not a.offsets.overlaps(b.offsets)


# --- what it must not touch ----------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "The delegation withdrew from the meeting.",
        "He drew a diagram on the board.",
        "The andrews file was closed.",
        "They had withdrawn the request.",
    ],
)
def test_an_ordinary_word_is_never_swept(sentence: str) -> None:
    """Case-sensitive and whole-word. The surname Le Drew licenses "Drew" and must not
    reach "drew" the verb, "drew" inside "withdrew", or "andrews".

    The outbound guard learned the second half of this the hard way: a substring test made
    a minute recording that a delegation withdrew refuse to send.
    """
    doc = make_document([(BlockKind.BODY, "Bernadette Le Drew wrote."), (BlockKind.BODY, sentence)])
    swept = [d for d in sweep(doc, [person("Bernadette Le Drew")]) if d.page == 1]
    for d in swept:
        assert d.text in ("Le Drew", "Bernadette Le Drew", "Drew", "Bernadette")
        assert d.text[0].isupper()


def test_the_sweep_is_off_when_nothing_was_detected() -> None:
    doc = make_document([(BlockKind.BODY, "A page with no person on it at all.")])
    assert sweep(doc, []) == ()


def test_with_sweep_returns_reading_order() -> None:
    doc = make_document(
        [
            (BlockKind.BODY, "Bernadette Le Drew wrote."),
            (BlockKind.BODY, "Le Drew attended."),
        ]
    )
    merged = with_sweep(doc, [person("Bernadette Le Drew")])
    keys = [(d.page, d.offsets.start) for d in merged]
    assert keys == sorted(keys)


# --- the property the whole project rests on -----------------------------------


def test_a_swept_span_still_has_to_be_decided(detector) -> None:  # type: ignore[no-untyped-def]
    """A recovered name is not a released name. It enters the pipeline as a detection like
    any other and the rules and the model decide it; absent evidence it escalates, which
    withholds. The sweep raises recall, and it cannot release anything by itself.
    """
    from sever.decide.pipeline import DecisionEngine

    from .conftest import requester_config

    doc = make_document(
        [
            (BlockKind.BODY, "The complainant Bernadette Le Drew wrote in March."),
            (BlockKind.BODY, "Present: Le Drew, Hugh Mercer."),
        ]
    )
    result = DecisionEngine(config=requester_config("Aaron Byrne"), detector=detector).propose(doc)
    swept = [p for p in result if p.detection.recogniser == RECOGNISER]
    assert swept, "the sweep found nothing, so this test proved nothing"
    for p in swept:
        assert p.withholds, f"{p.detection.text!r} was released with code {p.code}"
