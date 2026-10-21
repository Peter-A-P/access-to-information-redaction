"""In a message about the writer's own affairs, a model's release needs 0.75.

Jev 1.14's first run on the trap set released an employee writing about their own leave or
grievance from their work address on 8 of 240 must-withhold spans: as an official (K2) or
as the requester (K1), each time at 0.60 to 0.70, just above the threshold the tool runs at.
The rules stand aside in such a message (docs/escalation.md case 8) and leave the reading to
the model; this pins that a release there below `OWN_AFFAIRS_RELEASE_THRESHOLD` is withheld
and referred, that a withholding answer is untouched, and that nothing changes outside such
a message. PLAN.md 12.52.
"""

from __future__ import annotations

from collections.abc import Sequence

from sever.context.record import ContextRecord
from sever.decide.pipeline import OWN_AFFAIRS_RELEASE_THRESHOLD, DecisionEngine, Source
from sever.decide.rules import RuleOutcome
from sever.detect.engine import SeverDetector
from sever.ingest.document import BlockKind, Document, DocumentType

from .conftest import make_document, requester_config


class ConfidentModel:
    """Answers every span with one code, at a confidence above the tool's 0.60."""

    name = "fake"
    model = "fake/confident"
    default_threshold = 0.60

    def __init__(self, code: str, confidence: float = 0.65) -> None:
        self.code = code
        self.confidence = confidence

    def decide(
        self,
        contexts: Sequence[ContextRecord],
        *,
        universe: Sequence[ContextRecord] = (),
        document: Document | None = None,
    ) -> list[RuleOutcome | None]:
        return [
            RuleOutcome(
                code=self.code, confidence=self.confidence, reason="it reads that way", rule="model"
            )
            for _ in contexts
        ]


def _leave_request() -> Document:
    return make_document(
        [
            (BlockKind.EMAIL_HEADER, "From: Cecile Bursey <cecilebursey@gov.nl.ca.example>"),
            (
                BlockKind.BODY,
                "I am attaching the note from my doctor and would like my leave to start on "
                "15 June.",
            ),
            (BlockKind.SIGNATURE, "Cecile Bursey\nAssistant Deputy Minister\n709-555-1638"),
        ],
        doc_type=DocumentType.EMAIL_CHAIN,
    )


def test_the_model_cannot_release_the_writer_below_the_bar(
    detector: SeverDetector,
) -> None:
    doc = _leave_request()
    for code in ("K1", "K2", "K6"):
        result = DecisionEngine(
            config=requester_config("Aaron Byrne"),
            detector=detector,
            model=ConfidentModel(code),
        ).propose(doc)
        writer = [
            p
            for p in result
            if p.detection.text in ("Cecile Bursey", "Assistant Deputy Minister", "709-555-1638")
        ]
        assert writer, "the detector found none of the writer's spans"
        for p in writer:
            assert p.withholds, (code, p.detection.text, p.code)
        assert any(
            p.rule == "own_affairs_model_release" and p.source is Source.MODEL for p in writer
        ), code


def test_a_release_at_the_bar_is_taken(detector: SeverDetector) -> None:
    result = DecisionEngine(
        config=requester_config("Aaron Byrne"),
        detector=detector,
        model=ConfidentModel("K2", OWN_AFFAIRS_RELEASE_THRESHOLD),
    ).propose(_leave_request())
    assert not any(p.rule == "own_affairs_model_release" for p in result)


def test_the_model_can_still_withhold_there(detector: SeverDetector) -> None:
    result = DecisionEngine(
        config=requester_config("Aaron Byrne"),
        detector=detector,
        model=ConfidentModel("R1"),
    ).propose(_leave_request())
    assert any(p.code == "R1" and p.source is Source.MODEL for p in result)


def test_an_ordinary_work_email_is_untouched(detector: SeverDetector) -> None:
    doc = make_document(
        [
            (BlockKind.EMAIL_HEADER, "From: Cecile Bursey <cecilebursey@gov.nl.ca.example>"),
            (
                BlockKind.BODY,
                "The client file has been reassigned and the letter will go out this week.",
            ),
            (BlockKind.SIGNATURE, "Cecile Bursey\nAssistant Deputy Minister\n709-555-1638"),
        ],
        doc_type=DocumentType.EMAIL_CHAIN,
    )
    result = DecisionEngine(
        config=requester_config("Aaron Byrne"),
        detector=detector,
        model=ConfidentModel("K2"),
    ).propose(doc)
    assert not any(p.rule == "own_affairs_model_release" for p in result)
