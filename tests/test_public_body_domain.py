"""The public body's email domain reaches the model as a label, and nothing else does.

An address on the body's own domain becomes [EMAIL_PUBLIC_BODY_n]. That tells the model
which kind of address it is without telling it whose, and it is only told when the
operator configures the domain. Three things are pinned here: the label is right, the
address itself still never leaves, and with no domain configured the request is byte for
byte what it was before, so the committed answer cache still replays.
"""

from __future__ import annotations

import json

from sever.context.record import ContextBuilder
from sever.context.requester import RequestConfig
from sever.decide.model import SYSTEM_PROMPT, GatewayModelDecider
from sever.decide.placeholders import (
    PUBLIC_BODY_EMAIL,
    PlaceholderPolicy,
    on_public_body_domain,
)
from sever.decide.rules import apply as apply_rules
from sever.detect.types import Detection, EntityType
from sever.ingest.document import Offsets

DOMAIN = "gov.nl.ca.example"


def _email(text: str, start: int = 0) -> Detection:
    return Detection(
        page=0, offsets=Offsets(start, start + len(text)), text=text,
        entity_type=EntityType.EMAIL, score=1.0, recogniser="test",
    )


def test_domain_match_is_exact_or_a_subdomain() -> None:
    assert on_public_body_domain("ab@gov.nl.ca.example", [DOMAIN])
    assert on_public_body_domain("ab@health.gov.nl.ca.example", [DOMAIN])
    assert on_public_body_domain("AB@GOV.NL.CA.EXAMPLE", ["@" + DOMAIN])
    # A look-alike that merely ends in the same letters is not the body's domain.
    assert not on_public_body_domain("ab@notgov.nl.ca.example", [DOMAIN])
    assert not on_public_body_domain("ab@example.com", [DOMAIN])
    assert not on_public_body_domain("ab@gov.nl.ca.example", [])


def test_work_and_personal_addresses_get_different_labels() -> None:
    work, home = "marychaulk@gov.nl.ca.example", "mary.chaulk@example.com"
    policy = PlaceholderPolicy.for_detections(
        [_email(work), _email(home, 40)], public_body_domains=[DOMAIN]
    )
    out = policy.apply(f"From {work}, copied to {home}")
    assert f"[{PUBLIC_BODY_EMAIL}_1]" in out
    assert "[EMAIL_1]" in out
    assert "chaulk" not in out.casefold()
    assert policy.rehydrate(out) == f"From {work}, copied to {home}"


def test_without_a_domain_the_request_is_unchanged() -> None:
    decider = GatewayModelDecider(enabled=True, with_page=False)
    assert decider.system_prompt == SYSTEM_PROMPT
    policy = PlaceholderPolicy.for_detections([_email("marychaulk@gov.nl.ca.example")])
    assert policy.apply("marychaulk@gov.nl.ca.example") == "[EMAIL_1]"


def test_domain_label_leaks_no_persona_value(corpus, detector) -> None:  # type: ignore[no-untyped-def]
    """The corpus-wide leak test again, with the domain configured. The label is new text
    in the request, so the property is re-checked rather than assumed."""
    decider = GatewayModelDecider(enabled=True, public_body_domains=(DOMAIN,))
    labelled = 0
    for item in corpus:
        doc = item.rendered.document
        contexts = ContextBuilder(
            config=RequestConfig(request_id=doc.doc_id, requester_name="")
        ).build(doc, tuple(detector.detect(doc)))
        residual = [c for c in contexts if not apply_rules(c).decided_by_rule]
        if not residual:
            continue
        policy = GatewayModelDecider.policy_for(residual, contexts, (DOMAIN,))
        for ctx in residual:
            message, payload = decider.build_request(ctx, policy)
            body = (message + json.dumps(payload)).casefold()
            labelled += PUBLIC_BODY_EMAIL.casefold() in body
            for p in item.rendered.cast.values():
                for value in (p.work_email, p.personal_email, p.full_name):
                    if value and len(value) >= 5:
                        assert value.casefold() not in body, (doc.doc_id, value)
    assert labelled > 0, "no request carried the label, so this proved nothing"
