"""A leak caused by a wrong label, counted separately from a leak caused by a miss.

Project 04, after both projects had fixed the same defect independently: "Neither project
has a measurement that would catch a wrong label, on either side, without someone going
looking." That is accurate, and it was accurate here for months.

The defect was a bare surname typed as a LOCATION. A LOCATION is not information about an
identifiable individual, so `not_personal_information` returns K6, and K6 releases. Three
numbers all stayed healthy while it happened:

  * **recall**, because the span was found;
  * **coverage**, because the detection covered it entirely;
  * the **leak decomposition**, because with two buckets the span was detected, so the
    leak was filed under "the decision was wrong" and pointed at the rules.

The rules were right. They were reasoning correctly from a false premise, and the fix
belonged in the detector. A decomposition that sends the reader to the wrong module is
worse than no decomposition, because it is confident.

So the decomposition has three buckets now, and this file holds the middle one to its
meaning. It is a regression test for a *measurement*, which is unusual and is the point:
the measurement is the deliverable here, not the fix it once would have caught.
"""

from __future__ import annotations

from sever.corpus.labels import LabelledSpan, LabelSource
from sever.decide.pipeline import Proposal, Source
from sever.detect.types import Detection, EntityType
from sever.eval.confusion import Scored, SpanOutcome
from sever.ingest.document import Offsets
from sever.taxonomy.loader import Decision, default_taxonomy


def _label(code: str) -> LabelledSpan:
    return LabelledSpan(
        page=1,
        offsets=Offsets(0, 9),
        text="Tuglavina",
        code=code,
        persona_id="p001",
        field_name="third_party.surname",
    )


def _proposal(entity_type: EntityType, code: str) -> Proposal:
    taxonomy = default_taxonomy()
    return Proposal(
        detection=Detection(
            page=1,
            offsets=Offsets(0, 9),
            text="Tuglavina",
            entity_type=entity_type,
            score=0.85,
            recogniser="presidio",
        ),
        code=code,
        decision=taxonomy.decision(code),
        confidence=0.9,
        reason="test",
        source=Source.RULE,
    )


def _outcome(entity_type: EntityType, proposed_code: str) -> SpanOutcome:
    taxonomy = default_taxonomy()
    proposal = _proposal(entity_type, proposed_code)
    return SpanOutcome(
        doc_id="d1",
        label=_label("R1"),
        proposal=proposal,
        true_decision=Decision.REDACT,
        proposed_decision=taxonomy.decision(proposed_code),
    )


def test_a_person_typed_as_a_place_and_released_is_a_mislabel_not_a_decision_error() -> None:
    """The case that prompted the measurement."""
    o = _outcome(EntityType.LOCATION, "K6")
    assert o.is_leak
    assert o.detected, "the span was found, which is why recall could not see this"
    assert o.failed_because_mislabelled
    assert not o.failed_because_undetected


def test_a_person_typed_as_an_organisation_counts_the_same_way() -> None:
    o = _outcome(EntityType.ORGANISATION, "K6")
    assert o.failed_because_mislabelled


def test_a_person_correctly_typed_and_wrongly_decided_is_a_decision_error() -> None:
    """The other side of the split. Typed as a person, released as an official: the
    detector did its job and the decision layer did not, and the fix belongs there."""
    o = _outcome(EntityType.PERSON, "K2")
    assert o.is_leak
    assert not o.failed_because_mislabelled
    assert not o.failed_because_undetected


def test_a_span_that_was_never_found_is_neither() -> None:
    taxonomy = default_taxonomy()
    o = SpanOutcome(
        doc_id="d1",
        label=_label("R1"),
        proposal=None,
        true_decision=Decision.REDACT,
        proposed_decision=None,
    )
    assert o.is_leak
    assert o.failed_because_undetected
    assert not o.failed_because_mislabelled
    assert taxonomy is not None


def test_a_correctly_withheld_span_is_not_a_leak_however_it_was_typed() -> None:
    """The measurement must not fire on a mistype that did no harm. A person typed as a
    place and withheld anyway is a labelling wart, not a leak, and counting it here would
    inflate the number that is supposed to mean something."""
    o = _outcome(EntityType.LOCATION, "R1")
    assert not o.is_leak
    assert not o.failed_because_mislabelled


def test_the_three_buckets_partition_the_leaks() -> None:
    """Every leak lands in exactly one bucket, which is what makes the table readable."""
    outcomes = (
        _outcome(EntityType.LOCATION, "K6"),
        _outcome(EntityType.ORGANISATION, "K6"),
        _outcome(EntityType.PERSON, "K2"),
        SpanOutcome(
            doc_id="d1",
            label=_label("R1"),
            proposal=None,
            true_decision=Decision.REDACT,
            proposed_decision=None,
        ),
    )
    d = Scored(outcomes=outcomes, label_source=LabelSource.CONSTRUCTED).decomposition()
    assert d["leaks"] == 4
    assert d["detector_missed"] == 1
    assert d["detector_mislabelled"] == 2
    assert d["decision_wrong"] == 1
    assert d["detector_missed"] + d["detector_mislabelled"] + d["decision_wrong"] == d["leaks"]
