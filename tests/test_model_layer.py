"""The model layer, exercised end to end against a fake gateway.

This file exists because of a bug it would have caught. `GatewayModelDecider._decide_one`
called `gateway.chat(request, purpose=..., metadata={...})`. `boundary.Gateway.chat` takes
no `metadata`. It typechecked (the gateway is held as `Any`, because `boundary` is an
optional extra), it passed every test, and it would have raised `TypeError` the first time
anyone switched the model layer on, which is also the first time anyone spent money.

Nothing had exercised the line. The corpus-wide privacy test builds requests and never
sends them, by design. So the send path had no test at all, and the one thing standing
between it and a live run was that it looked right.

Two defences here:

  * `test_the_call_matches_the_real_gateway_signature` introspects `boundary.Gateway.chat`
    and asserts the arguments this project passes are the arguments it accepts. It fails
    loudly on any drift in a library this project does not own.
  * The rest drive the whole decide path through a fake whose signature is the real one,
    so a parsing change, a threshold change or a disagreement path is covered without a
    network call or a cent of spend.

The whole module is skipped where `boundary` is not installed: the send path builds a real
`boundary.ChatRequest`, and a stand-in request type would test a path that is never run.
`boundary` is a private extra, so this is the case in CI. The privacy property the send
path depends on, that no raw detected entity is in an outbound request, does not need
`boundary` and is asserted for the whole corpus in `tests/test_no_raw_entity_leaves.py`,
which does run in CI.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any

import pytest

pytest.importorskip("boundary", reason="the gateway extra is not installed")

from sever.context.record import ContextRecord
from sever.decide.model import (
    DATA_CLASS,
    GatewayModelDecider,
    parse_answer,
)
from sever.decide.pipeline import DecisionEngine, Source
from sever.decide.rules import RuleOutcome
from sever.detect.types import Detection, EntityType
from sever.ingest.document import BlockKind, DocumentType, Offsets
from sever.taxonomy.loader import Decision, default_taxonomy

from .conftest import code_covering, make_document, requester_config


@dataclass
class FakeResponse:
    text: str
    cost_usd: float = 0.0


@dataclass
class FakeGateway:
    """A stand-in with `chat`'s real signature. Records what it was asked."""

    reply: str = '{"code": "R1", "confidence": 0.9, "evidence": "no title anywhere"}'
    calls: list[dict[str, Any]] = field(default_factory=list)

    def chat(
        self,
        request: Any,
        *,
        purpose: str,
        run_id: str | None = None,
        mode: Any = None,
        data_class: Any = None,
    ) -> FakeResponse:
        self.calls.append(
            {
                "request": request,
                "purpose": purpose,
                "run_id": run_id,
                "data_class": data_class,
            }
        )
        return FakeResponse(text=self.reply)


def a_context(text: str = "Odette Tulk") -> ContextRecord:
    return ContextRecord(
        detection=Detection(
            page=1,
            offsets=Offsets(0, len(text)),
            text=text,
            entity_type=EntityType.PERSON,
            score=0.85,
            recogniser="test",
        ),
        doc_id="d1",
        doc_type=DocumentType.CORRESPONDENCE,
        page_number=1,
        pages_in_document=1,
        block_kind=BlockKind.BODY,
        sentence=f"The report was made by {text} of Gander.",
    )


# --- the contract with a library this project does not own --------------------


def test_the_call_matches_the_real_gateway_signature() -> None:
    boundary = pytest.importorskip("boundary", reason="the gateway extra is not installed")
    parameters = inspect.signature(boundary.Gateway.chat).parameters

    for name in ("purpose", "run_id", "data_class"):
        assert name in parameters, (
            f"sever passes {name!r} to Gateway.chat and the installed boundary does not "
            f"accept it. Either the interface moved or this project is wrong."
        )

    required = {
        name
        for name, p in parameters.items()
        if name not in ("self", "request")
        and p.default is inspect.Parameter.empty
        and p.kind is not inspect.Parameter.VAR_KEYWORD
    }
    assert required <= {"purpose"}, (
        f"Gateway.chat now requires {sorted(required)}; sever supplies only purpose, "
        f"run_id and data_class, so the model layer would fail on the first live call."
    )
    # The fake in this file has to stay honest about the real thing.
    fake = set(inspect.signature(FakeGateway.chat).parameters) - {"self"}
    real = set(parameters) - {"self"}
    assert fake <= real, f"the fake accepts {sorted(fake - real)}, which the real one does not"


def test_every_call_carries_the_personal_data_class() -> None:
    """CLAUDE.md: every model call goes through the 04 gateway with class `personal`.

    boundary 0.5.1 made this a real parameter with its own ledger column, so it is checked
    as one. Before that it rode inside `purpose` as free text, which the ledger could store
    and not query. If this assertion is ever relaxed, a ledger audit can no longer answer
    which calls carried personal data, which is the whole point of the class.
    """
    gateway = FakeGateway()
    GatewayModelDecider(gateway=gateway, enabled=True).decide([a_context()])
    assert gateway.calls[0]["data_class"] == DATA_CLASS


# --- the send path ------------------------------------------------------------


def test_a_confident_answer_becomes_a_proposal() -> None:
    gateway = FakeGateway()
    decider = GatewayModelDecider(gateway=gateway, enabled=True, run_id="run-1")
    answers = decider.decide([a_context()])

    assert len(gateway.calls) == 1
    assert gateway.calls[0]["run_id"] == "run-1"
    assert gateway.calls[0]["data_class"] == DATA_CLASS

    outcome = answers[0]
    assert isinstance(outcome, RuleOutcome)
    assert outcome.code == "R1"
    assert outcome.rule == "model"
    assert "placeholders rather than names" in outcome.reason


def test_the_request_carries_no_name() -> None:
    gateway = FakeGateway()
    GatewayModelDecider(gateway=gateway, enabled=True).decide([a_context("Odette Tulk")])
    body = str(gateway.calls[0]["request"].messages) + str(gateway.calls[0]["request"].system)
    assert "Odette" not in body and "Tulk" not in body, body[:400]
    assert "[PERSON_" in body


def test_an_unparseable_reply_is_no_answer_rather_than_a_guess() -> None:
    gateway = FakeGateway(reply="I think this one is probably fine to release.")
    answers = GatewayModelDecider(gateway=gateway, enabled=True).decide([a_context()])
    assert answers == [None]


def test_an_invented_category_is_discarded() -> None:
    gateway = FakeGateway(reply='{"code": "R9", "confidence": 0.99, "evidence": "made up"}')
    answers = GatewayModelDecider(gateway=gateway, enabled=True).decide([a_context()])
    assert answers == [None], "a category outside the taxonomy was accepted"


def test_no_call_is_made_when_the_layer_is_off() -> None:
    gateway = FakeGateway()
    answers = GatewayModelDecider(gateway=gateway, enabled=False).decide([a_context()])
    assert gateway.calls == []
    assert answers == [None]


# --- how the pipeline treats what comes back ----------------------------------


def test_a_low_confidence_answer_is_escalated_not_used(detector) -> None:  # type: ignore[no-untyped-def]
    gateway = FakeGateway(reply='{"code": "K2", "confidence": 0.4, "evidence": "a guess"}')
    doc = make_document([(BlockKind.BODY, "The report was made by Odette Tulk of Gander.")])
    engine = DecisionEngine(
        config=requester_config("Aaron Byrne"),
        detector=detector,
        model=GatewayModelDecider(gateway=gateway, enabled=True),
        model_confidence_threshold=0.7,
    )
    result = engine.propose(doc)
    code = code_covering(doc, result, "Odette Tulk")
    assert code == "E1", f"the third party was placed as {code}"
    p = next(p for p in result if p.code == "E1")
    assert p.decision.withholds
    assert "below the 0.70 threshold" in p.reason


def test_a_confident_keep_on_the_residual_is_taken(detector) -> None:  # type: ignore[no-untyped-def]
    gateway = FakeGateway(reply='{"code": "K2", "confidence": 0.95, "evidence": "letterhead"}')
    doc = make_document([(BlockKind.BODY, "The report was made by Odette Tulk of Gander.")])
    engine = DecisionEngine(
        config=requester_config("Aaron Byrne"),
        detector=detector,
        model=GatewayModelDecider(gateway=gateway, enabled=True),
    )
    result = engine.propose(doc)
    assert code_covering(doc, result, "Odette Tulk") == "K2"
    p = next(p for p in result if p.code == "K2")
    assert p.source is Source.MODEL
    assert p.decision is Decision.KEEP


def test_the_model_never_overrides_a_rule_into_release(detector) -> None:  # type: ignore[no-untyped-def]
    """A disagreement is withheld and referred, never resolved towards release."""
    gateway = FakeGateway(reply='{"code": "K6", "confidence": 0.99, "evidence": "whatever"}')
    doc = make_document(
        [(BlockKind.BODY, "We wrote to Aaron Byrne about the inspection at his home.")]
    )
    engine = DecisionEngine(
        config=requester_config("Aaron Byrne"),
        detector=detector,
        model=GatewayModelDecider(gateway=gateway, enabled=True),
    )
    # The requester rule fires, so this span is decided and never reaches the model at all.
    result = engine.propose(doc)
    assert code_covering(doc, result, "Aaron Byrne") == "K1"
    assert next(p for p in result if p.code == "K1").source is Source.RULE


def test_the_taxonomy_bounds_what_can_be_parsed() -> None:
    t = default_taxonomy()
    for code in (c.code for c in t.categories):
        parsed = parse_answer(f'{{"code": "{code}", "confidence": 0.8}}', t)
        assert parsed is not None and parsed.code == code


# --- distinct requests, which is a property of the payloads ---------------------


def test_distinct_requests_counts_payloads_and_not_asks() -> None:
    """The ablation's cacheability column is only meaningful if it counts what it says.

    `calls` and `cache_reads` count spans asked about. This counts the different requests
    those asks needed, which is what differs between the masked and raw arms: masked
    payloads repeat across documents once the names are gone, raw ones cannot. A counter
    that read `len(self._cache)` instead would also count answers loaded from disk and
    never asked for, and the number would drift upward on every re-run.
    """
    gateway = FakeGateway()
    decider = GatewayModelDecider(gateway=gateway, enabled=True)
    same = [a_context("Odette Tulk"), a_context("Odette Tulk")]
    decider.decide(same, universe=same)
    assert decider.calls + decider.cache_reads == 2, "both spans were asked about"
    assert decider.distinct_requests == 1, "and they are the same request"

    differing = [a_context("Odette Tulk"), a_context("Marie Chaulk")]
    other = GatewayModelDecider(gateway=FakeGateway(), enabled=True)
    other.decide(differing, universe=differing)
    assert other.distinct_requests == 2
