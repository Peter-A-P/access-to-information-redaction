"""The ablation's interlock: the raw arm cannot be pointed at a vendor.

`sever/eval/placeholders.py` is the one module in this repository that deliberately builds
a payload containing names. It exists because the paired ablation cannot be run any other
way, and everything about it is arranged so that the payload can only ever reach a model on
this machine.

That arrangement is worth more than the number it produces, so it is tested first and
tested hard. The property is not "we remembered to pass the right model string". It is that
passing the wrong one raises before a payload exists, because a payload that exists is a
payload something can send.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sever.eval.placeholders import NotLoopback, RawTextDecider, assert_loopback, raw_context


@dataclass
class FakeProvider:
    base_url: str
    price_zero: bool = False
    residency: str | None = None


@dataclass
class FakeConfig:
    providers: dict[str, FakeProvider]


@dataclass
class FakeGateway:
    config: FakeConfig


def gateway_with(**providers: FakeProvider) -> FakeGateway:
    return FakeGateway(config=FakeConfig(providers=dict(providers)))


LOCAL = FakeProvider(
    base_url="http://127.0.0.1:11434/v1", price_zero=True, residency="single-region"
)


def test_a_local_provider_is_allowed() -> None:
    assert_loopback(gateway_with(local=LOCAL), "local/qwen2.5:7b")


@pytest.mark.parametrize(
    ("label", "provider"),
    [
        (
            "a vendor",
            FakeProvider(base_url="https://api.anthropic.com", price_zero=False),
        ),
        (
            "a paid host that happens to be on localhost",
            FakeProvider(
                base_url="http://127.0.0.1:8080/v1", price_zero=False, residency="single-region"
            ),
        ),
        (
            "a free host that is not on this machine",
            FakeProvider(
                base_url="https://free.example.com/v1", price_zero=True, residency="single-region"
            ),
        ),
        (
            "a local host that does not declare its residency",
            FakeProvider(base_url="http://127.0.0.1:11434/v1", price_zero=True, residency=None),
        ),
        (
            "a local host declaring a residency it cannot have",
            FakeProvider(
                base_url="http://127.0.0.1:11434/v1", price_zero=True, residency="global"
            ),
        ),
    ],
)
def test_anything_that_is_not_a_model_on_this_machine_is_refused(
    label: str, provider: FakeProvider
) -> None:
    """All three conditions are required, so each one is tested alone.

    The second case is the one worth having: a billing host reachable on loopback is still
    a billing host, and a check that looked only at the URL would wave it through.
    """
    with pytest.raises(NotLoopback):
        assert_loopback(gateway_with(candidate=provider), "candidate/some-model")


def test_an_unknown_provider_is_refused_rather_than_assumed() -> None:
    with pytest.raises(NotLoopback, match="not in the gateway configuration"):
        assert_loopback(gateway_with(local=LOCAL), "mystery/model")


def test_a_bare_model_name_with_no_provider_is_refused() -> None:
    """`chat` would resolve this through the route aliases, every one of which points at a
    vendor. It is refused here rather than resolved."""
    with pytest.raises(NotLoopback):
        assert_loopback(gateway_with(local=LOCAL), "qwen2.5:7b")


def test_the_raw_decider_refuses_to_exist_against_a_vendor() -> None:
    """The check is in `__post_init__`, so there is no window in which a raw decider
    pointed at a vendor is constructed and then validated."""
    vendor = gateway_with(anthropic=FakeProvider(base_url="https://api.anthropic.com"))
    with pytest.raises(NotLoopback):
        RawTextDecider(gateway=vendor, model="anthropic/claude-haiku-4-5", enabled=True)


def test_a_disabled_raw_decider_is_inert_and_needs_no_gateway() -> None:
    """`enabled=False` cannot send, so it is allowed to exist: the corpus-wide tests build
    deciders without a gateway and must keep working."""
    RawTextDecider(gateway=None, model="anthropic/claude-haiku-4-5", enabled=False)


# --- the control payload -------------------------------------------------------


def test_the_raw_payload_has_the_same_fields_as_the_redacted_one(detector) -> None:  # type: ignore[no-untyped-def]
    """The arms must differ in exactly one respect: whether the names are there.

    If the raw payload gained or lost a field, the ablation would be measuring the payload
    shape as well as the boundary, and the number would not mean what the table says.
    """
    from sever.context.record import ContextBuilder
    from sever.context.requester import RequestConfig
    from sever.decide.model import GatewayModelDecider
    from sever.decide.placeholders import redact_context
    from sever.ingest.document import BlockKind

    from .conftest import make_document

    doc = make_document(
        [(BlockKind.BODY, "The complainant Odette Tulk wrote to the department in March.")]
    )
    contexts = ContextBuilder(config=RequestConfig(request_id="d1")).build(
        doc, tuple(detector.detect(doc))
    )
    assert contexts, "nothing was detected, so this test proved nothing"
    policy = GatewayModelDecider.policy_for(contexts, contexts)
    for ctx in contexts:
        assert set(raw_context(ctx)) == set(redact_context(ctx, policy))


def test_the_raw_payload_keeps_the_name_that_the_redacted_one_removes(detector) -> None:  # type: ignore[no-untyped-def]
    """The control arm is only a control if it actually carries the name. This is the one
    assertion in the repository that wants a raw name in a payload, and it never leaves
    this process."""
    from sever.context.record import ContextBuilder
    from sever.context.requester import RequestConfig
    from sever.decide.model import GatewayModelDecider
    from sever.decide.placeholders import redact_context
    from sever.ingest.document import BlockKind

    from .conftest import make_document

    doc = make_document([(BlockKind.BODY, "The complainant Odette Tulk wrote in March.")])
    contexts = ContextBuilder(config=RequestConfig(request_id="d1")).build(
        doc, tuple(detector.detect(doc))
    )
    policy = GatewayModelDecider.policy_for(contexts, contexts)
    raws = " ".join(str(raw_context(c)["sentence"]) for c in contexts)
    masked = " ".join(str(redact_context(c, policy)["sentence"]) for c in contexts)
    assert "Tulk" in raws, "the control arm is not carrying the name it is supposed to"
    assert "Tulk" not in masked, masked


# --- the cacheability column ----------------------------------------------------


def test_the_table_reports_each_arm_s_cacheability_separately() -> None:
    """A blended hit rate would average away the only effect this column exists to show.

    04 made the same change to their cache measurement after seeing this number: the
    finding is the gap between the arms, so a measurement that cannot show two arms cannot
    show the finding.
    """
    from sever.corpus.labels import LabelSource
    from sever.eval.confusion import Scored
    from sever.eval.placeholders import Ablation, Arm

    empty = Scored(outcomes=(), label_source=LabelSource.CONSTRUCTED)
    table = Ablation(
        arms=[
            Arm(name="typed placeholders", note="", scored=empty, calls=244, distinct=171),
            Arm(name="raw text", note="", scored=empty, calls=244, distinct=239),
        ],
        model="local/qwen2.5:7b",
    ).to_markdown()
    assert "171 of 244 asks (30% repeated)" in table
    assert "239 of 244 asks (2% repeated)" in table


def test_an_arm_that_asked_nothing_reports_no_repetition_rather_than_dividing_by_zero() -> None:
    from sever.corpus.labels import LabelSource
    from sever.eval.confusion import Scored
    from sever.eval.placeholders import Arm

    arm = Arm(name="x", note="", scored=Scored(outcomes=(), label_source=LabelSource.CONSTRUCTED))
    assert arm.repetition == 0.0
