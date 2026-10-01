"""What 07 hands project 03's release gate.

The gate refuses a file it cannot read exactly, so the shape is tested against what its
adapter reads (docs/gate-adapter.md in 03). The other thing tested is the unit: the gate
treats every item as independent, so the items have to be documents and never spans.
"""

from __future__ import annotations

from sever.corpus.labels import LabelledSpan
from sever.eval.confusion import Scored, SpanOutcome
from sever.eval.gate import SUITES, side, spec
from sever.ingest.document import Offsets
from sever.taxonomy.loader import Decision

SIDE_KEYS = {"label", "source", "suites"}
SUITE_KEYS = {
    "suite", "outcomes", "ungradeable_items", "calls", "latency_p50_ms", "cost_usd",
    "uncosted_calls",
}


def outcome(doc: str, code: str, start: int, *, withheld: bool) -> SpanOutcome:
    label = LabelledSpan(page=1, offsets=Offsets(start, start + 4), text="Abcd", code=code)
    decision = Decision.REDACT if code.startswith("R") else Decision.KEEP
    return SpanOutcome(
        doc_id=doc,
        label=label,
        proposal=None,
        true_decision=decision,
        proposed_decision=None,
    ) if not withheld else _withheld(doc, label, decision)


def _withheld(doc: str, label: LabelledSpan, decision: Decision) -> SpanOutcome:
    from sever.decide.pipeline import Proposal, Source
    from sever.detect.types import Detection, EntityType

    det = Detection(page=1, offsets=label.offsets, text=label.text,
                    entity_type=EntityType.PERSON, score=1.0, recogniser="test")
    p = Proposal(detection=det, code="R1", decision=Decision.REDACT, confidence=1.0,
                 reason="", source=Source.RULE)
    return SpanOutcome(doc_id=doc, label=label, proposal=p, true_decision=decision,
                       proposed_decision=Decision.REDACT)


def test_the_item_is_the_document_and_one_bad_span_fails_it() -> None:
    scored = Scored(outcomes=(
        outcome("d1", "R1", 0, withheld=True),
        outcome("d1", "R1", 10, withheld=False),   # one leak in d1
        outcome("d2", "R1", 0, withheld=True),
        outcome("d2", "K1", 10, withheld=False),
        outcome("d3", "K1", 0, withheld=True),     # over-redacted requester
    ))
    suites = side("x", scored, source={"k": "v"})["suites"]
    assert suites["no_leak"]["outcomes"] == {"d1": False, "d2": True}
    assert suites["k1_requester"]["outcomes"] == {"d2": True, "d3": False}
    # A document without the category is not an item in that suite.
    assert suites["k3_public"]["outcomes"] == {}


def test_the_files_have_exactly_the_keys_the_gate_reads() -> None:
    body = side("x", Scored(outcomes=()), source={"k": "v"})
    assert set(body) == SIDE_KEYS
    for key, suite in body["suites"].items():
        assert set(suite) == SUITE_KEYS
        assert suite["suite"] == key
    s = spec()
    assert [x["key"] for x in s["suites"]] == [k for k, _, _ in SUITES]
    assert all(x["source"] == {"kind": "outcomes_file", "block": x["key"]} for x in s["suites"])
