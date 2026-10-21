"""The residual decided by a decision model (Jev, Kev): the request, the reply, the boundary.

No network. The request is checked against boundary's own decisions adapter, so a request
this project builds and 04 would refuse fails here rather than on the first paid call.
"""

from __future__ import annotations

import json

import pytest

boundary = pytest.importorskip("boundary", reason="the gateway extra is not installed")

from sever.context.record import ContextBuilder  # noqa: E402
from sever.decide.decision_model import (  # noqa: E402
    DEFAULT_DECISION_MODEL,
    KEV_MODEL,
    NOT_OFFERED,
    QUESTION_ID,
    DecisionModelDecider,
    is_decision_model,
)
from sever.decide.model import GatewayModelDecider, PageView  # noqa: E402
from sever.decide.rules import apply as apply_rules  # noqa: E402
from sever.eval.report import config_for  # noqa: E402

from .test_model_layer import FakeGateway, a_context  # noqa: E402
from .test_no_raw_entity_leaves import MIN_LENGTH, _persona_secrets  # noqa: E402


def a_reply(**probabilities: float) -> str:
    choice = max(probabilities, key=probabilities.__getitem__)
    return json.dumps(
        {QUESTION_ID: {"type": "choice", "choice": choice, "probabilities": probabilities,
                       "confidence": 0.5}}
    )


def test_a_decision_model_is_named_by_its_provider_entry() -> None:
    assert is_decision_model(DEFAULT_DECISION_MODEL) and is_decision_model(KEV_MODEL)
    assert not is_decision_model("anthropic/claude-haiku-5-5")


def test_the_request_is_a_state_and_one_choice_with_no_cannot_tell() -> None:
    gateway = FakeGateway(reply=a_reply(R1=0.9, K2=0.1))
    DecisionModelDecider(gateway=gateway, enabled=True).decide([a_context()])
    request = gateway.calls[0]["request"]
    assert request.model == DEFAULT_DECISION_MODEL
    assert request.system is None and request.temperature is None
    assert isinstance(request.messages[0]["content"], dict)
    question = request.extra["questions"][QUESTION_ID]
    assert question["type"] == "choice"
    offered = set(question["criteria"])
    assert "R1" in offered and "K2" in offered and "E2" in offered
    assert not offered & NOT_OFFERED
    assert gateway.calls[0]["data_class"] == "personal"


def test_boundary_s_own_adapter_accepts_the_request() -> None:
    from boundary.config import load_config
    from boundary.providers.decisions import DecisionsAdapter
    from boundary.routes import resolve
    from boundary.types import Mode

    from sever.cli import DEFAULT_BOUNDARY_CONFIG

    if not DEFAULT_BOUNDARY_CONFIG.is_file():
        pytest.skip("04's configuration is not beside this repository")
    gateway = FakeGateway(reply=a_reply(R1=1.0))
    DecisionModelDecider(gateway=gateway, enabled=True).decide([a_context()])
    request = gateway.calls[0]["request"]
    ref = resolve(request.model, load_config(DEFAULT_BOUNDARY_CONFIG), Mode.STANDARD)
    built = DecisionsAdapter().build_request(ref, request, ref.provider_config, "k")
    body = json.loads(built.body)
    assert built.url.endswith("/alpha/decisions") and body["model"] == "typesafe/jev-1.14"
    assert set(body) == {"model", "state", "questions"}


def test_the_answer_is_the_most_probable_code_at_its_probability() -> None:
    decider = DecisionModelDecider(gateway=FakeGateway(reply=a_reply(K2=0.82, R1=0.15, E1=0.03)),
                                   enabled=True)
    (outcome,) = decider.decide([a_context()])
    assert outcome is not None
    assert outcome.code == "K2" and outcome.confidence == pytest.approx(0.82)
    assert "next R1 at 0.15" in outcome.reason


def test_a_code_it_was_not_offered_is_never_the_answer() -> None:
    decider = DecisionModelDecider(gateway=FakeGateway(reply=a_reply(E1=0.7, R1=0.3)),
                                   enabled=True)
    (outcome,) = decider.decide([a_context()])
    assert outcome is not None and outcome.code == "R1"


def test_a_malformed_reply_is_no_answer_and_so_an_escalation() -> None:
    decider = DecisionModelDecider(gateway=FakeGateway(reply="not json"), enabled=True)
    assert decider.decide([a_context()]) == [None]


def test_the_answer_cache_keys_on_the_question_too(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cache = tmp_path / "answers.jsonl"
    first = FakeGateway(reply=a_reply(R1=0.9, K2=0.1))
    DecisionModelDecider(gateway=first, enabled=True, cache_path=cache).decide([a_context()])
    replay = DecisionModelDecider(gateway=None, enabled=True, cache_path=cache, replay_only=True)
    (outcome,) = replay.decide([a_context()])
    assert outcome is not None and outcome.code == "R1"
    # The same span asked of the language model is a different question, and is not replayed.
    language = GatewayModelDecider(gateway=None, enabled=True, cache_path=cache, replay_only=True)
    with pytest.raises(Exception, match="replay-only"):
        language.decide([a_context()])


def test_no_persona_value_reaches_the_decision_model(corpus, detector) -> None:  # type: ignore[no-untyped-def]
    """The corpus-wide leak test, on the state a decision model is sent, page included."""
    decider = DecisionModelDecider(enabled=True, public_body_domains=("gov.nl.ca.example",))
    offenders: list[str] = []
    sent = 0
    for item in corpus:
        doc = item.rendered.document
        contexts = ContextBuilder(config=config_for(item)).build(doc, tuple(detector.detect(doc)))
        residual = [c for c in contexts if not apply_rules(c).decided_by_rule]
        if not residual:
            continue
        policy = GatewayModelDecider.policy_for(residual, contexts, decider.public_body_domains)
        view = PageView.of(doc, contexts, policy)
        secrets = [s for s in _persona_secrets(item.rendered.cast) if len(s) >= MIN_LENGTH]
        for ctx in residual:
            state, _ = decider.build_request(ctx, policy, view)
            body = (state + decider.system_prompt).casefold()
            sent += 1
            offenders += [f"{doc.doc_id}: {s!r}" for s in secrets if s.casefold() in body]
    assert sent > 0
    assert not offenders, "\n".join(sorted(set(offenders))[:10])


def test_a_decision_model_runs_at_its_own_threshold() -> None:
    """Reported at 0.00, which the rule fixed in advance chose; run at 0.60, so the
    model's coin flips still go to a reviewer (PLAN.md 12.50)."""
    from sever.cli import _default_threshold
    from sever.decide.decision_model import DEFAULT_DECISION_THRESHOLD
    from sever.decide.pipeline import DEFAULT_THRESHOLD

    assert _default_threshold(DEFAULT_DECISION_MODEL) == DEFAULT_DECISION_THRESHOLD == 0.60
    assert _default_threshold("anthropic/claude-haiku-5-5") == DEFAULT_THRESHOLD
