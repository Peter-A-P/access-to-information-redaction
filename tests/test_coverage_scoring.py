"""The headline scorer and the reviewer study count a partial box the same way.

Until 2026-10-10 the headline tables asked whether the box overlapping a label most
withheld, so nine digits of a twelve-digit MCP number boxed counted as the whole number
withheld, and so did "Coordinator" alone in "Access and Privacy Coordinator". The study
asked whether every letter and digit was covered. Now both use `sever.eval.coverage`.
"""

from __future__ import annotations

from sever.corpus.labels import LabelledSpan, LabelSet
from sever.decide.pipeline import DocumentProposals, Proposal, Source
from sever.detect.types import Detection, EntityType
from sever.eval.confusion import Scored, SpanOutcome, score
from sever.ingest.document import BlockKind, Offsets
from sever.taxonomy.loader import Decision

from .conftest import make_document

TEXT = (
    "MCP 404 474 556 704 for Marie Doucette, Access and Privacy Coordinator, "
    "and the Regional Director, Fiona Byrne."
)


def _label(needle: str, code: str, field: str) -> LabelledSpan:
    start = TEXT.index(needle)
    return LabelledSpan(
        page=1, offsets=Offsets(start, start + len(needle)), text=needle, code=code,
        field_name=field,
    )


def _box(needle: str, decision: Decision, entity: EntityType = EntityType.PERSON) -> Proposal:
    start = TEXT.index(needle)
    return Proposal(
        detection=Detection(
            page=1, offsets=Offsets(start, start + len(needle)), text=needle,
            entity_type=entity, score=0.9, recogniser="test",
        ),
        code="R1" if decision is Decision.REDACT else "K6",
        decision=decision,
        confidence=0.9,
        reason="test",
        source=Source.RULE,
    )


def _scored(boxes: list[Proposal]) -> Scored:
    doc = make_document([(BlockKind.BODY, TEXT)], doc_id="d1")
    labels = LabelSet(
        doc_id="d1",
        spans=(
            _label("404 474 556 704", "R1", "injured.mcp"),
            _label("Marie Doucette", "R1", "grievant.full_name"),
            _label("Access and Privacy Coordinator", "R1", "grievant.title"),
            _label("Fiona Byrne", "K2", "adm.full_name"),
        ),
    )
    return score({"d1": (DocumentProposals(document=doc, proposals=tuple(boxes)), labels)})


def _outcomes(boxes: list[Proposal]) -> dict[str, SpanOutcome]:
    return {o.label.text: o for o in _scored(boxes).outcomes}


def test_a_number_with_three_digits_showing_is_withheld() -> None:
    out = _outcomes([_box("404 474 556", Decision.REDACT, EntityType.SIN)])
    assert not out["404 474 556 704"].is_leak


def test_a_number_with_seven_digits_showing_is_a_leak_under_a_short_box() -> None:
    out = _outcomes([_box("404 474", Decision.REDACT, EntityType.SIN)])
    o = out["404 474 556 704"]
    assert o.is_leak and o.failed_because_box_too_short


def test_a_forename_boxed_alone_leaks_the_surname() -> None:
    scored = _scored([_box("Marie", Decision.REDACT)])
    o = {x.label.text: x for x in scored.outcomes}["Marie Doucette"]
    assert o.is_leak and o.failed_because_box_too_short
    assert scored.decomposition()["box_too_short"] == 1


def test_a_title_with_its_role_word_boxed_is_withheld() -> None:
    out = _outcomes([_box("Coordinator", Decision.REDACT, EntityType.JOB_TITLE)])
    assert not out["Access and Privacy Coordinator"].is_leak


def test_a_title_with_only_its_qualifier_boxed_is_a_leak() -> None:
    out = _outcomes([_box("Access and Privacy", Decision.REDACT, EntityType.ORGANISATION)])
    assert out["Access and Privacy Coordinator"].is_leak


def test_two_boxes_that_together_cover_a_span_withhold_it() -> None:
    out = _outcomes([_box("Marie", Decision.REDACT), _box("Doucette", Decision.REDACT)])
    assert not out["Marie Doucette"].is_leak


def test_any_box_over_a_must_keep_span_is_over_redaction() -> None:
    out = _outcomes([_box("Byrne", Decision.REDACT)])
    assert out["Fiona Byrne"].is_over_redaction


def test_a_releasing_box_is_not_a_withholding_one() -> None:
    out = _outcomes([_box("Marie Doucette", Decision.KEEP)])
    o = out["Marie Doucette"]
    assert o.is_leak and not o.failed_because_box_too_short
