"""The masked page goes to the model, and nothing on it identifies anyone.

A page is many times more text than the one sentence the model used to get, so the
corpus-wide leak property is checked again with the page attached rather than assumed from
the sentence-level test. With the page off, the request is unchanged, which is what keeps
the committed answer cache replaying.
"""

from __future__ import annotations

import json

from sever.context.record import ContextBuilder
from sever.context.requester import RequestConfig
from sever.decide.model import SYSTEM_PROMPT, GatewayModelDecider, PageView
from sever.decide.rules import apply as apply_rules
from sever.eval.report import config_for

from .test_no_raw_entity_leaves import MIN_LENGTH, _persona_secrets


def test_page_off_leaves_the_request_unchanged() -> None:
    assert GatewayModelDecider(enabled=True, with_page=False).system_prompt == SYSTEM_PROMPT


def test_no_persona_value_appears_on_the_masked_page(corpus, detector) -> None:  # type: ignore[no-untyped-def]
    decider = GatewayModelDecider(
        enabled=True, public_body_domains=("gov.nl.ca.example",), with_page=True
    )
    offenders: list[str] = []
    pages_sent = 0
    requester_named = 0
    for item in corpus:
        doc = item.rendered.document
        contexts = ContextBuilder(config=config_for(item)).build(
            doc, tuple(detector.detect(doc))
        )
        residual = [c for c in contexts if not apply_rules(c).decided_by_rule]
        if not residual:
            continue
        policy = GatewayModelDecider.policy_for(residual, contexts, decider.public_body_domains)
        view = PageView.of(doc, contexts, policy)
        requester_named += view.requester is not None
        secrets = [s for s in _persona_secrets(item.rendered.cast) if len(s) >= MIN_LENGTH]
        for ctx in residual:
            message, payload = decider.build_request(ctx, policy, view)
            assert payload["page_text"], "the page was not attached"
            pages_sent += 1
            body = (decider.system_prompt + message + json.dumps(payload)).casefold()
            offenders += [
                f"{doc.doc_id}: {s!r}" for s in secrets if s.casefold() in body
            ]
    assert pages_sent > 0
    assert requester_named > 0, "the requester was never identified, so that field is untested"
    assert not offenders, "\n".join(sorted(set(offenders))[:10])


def test_the_requester_is_a_placeholder_not_a_name(corpus, detector) -> None:  # type: ignore[no-untyped-def]
    item = corpus.items[0]
    doc = item.rendered.document
    contexts = ContextBuilder(
        config=RequestConfig(request_id=doc.doc_id, requester_name="")
    ).build(doc, tuple(detector.detect(doc)))
    policy = GatewayModelDecider.policy_for(contexts, contexts)
    # No requester configured: the field says so rather than guessing.
    assert PageView.of(doc, contexts, policy).requester is None


def test_a_value_copied_in_another_form_is_masked_not_refused() -> None:
    """On a scanned page `accès` came back where the detector found `accés`, and `TE 18`
    with a line break in it. The guard saw both copies and refused; now they are masked."""
    from sever.decide.placeholders import PlaceholderPolicy, outbound
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import Offsets

    found = [
        Detection(page=1, offsets=Offsets(0, 5), text=t, entity_type=k, score=1.0, recogniser="t")
        for t, k in (("accés", EntityType.PERSON), ("TE 18", EntityType.ADDRESS))
    ]
    policy = PlaceholderPolicy.for_detections(found)
    out = outbound("Demande d'accès: TE\n18 and accés here.", policy)
    policy.guard(out)
    assert "acc" not in out.casefold() and "18" not in out
    assert outbound("Nothing to see.", policy) == "Nothing to see."


def test_a_longer_number_is_not_a_copy_of_a_shorter_one() -> None:
    """"TE: 181" on a scanned page was refused as a copy of a detected "TE 18"."""
    from sever.decide.placeholders import PlaceholderPolicy

    assert not PlaceholderPolicy._contains_word("registration date for te 181 is", "te 18")
    assert PlaceholderPolicy._contains_word("registration date for te 18 is", "te 18")


def test_a_surname_span_is_the_person_its_sentence_names() -> None:
    """Only "Yetman" of the official Odette Yetman was detected, and the witness Maeve
    Yetman was. The span went out as the witness's placeholder while the page beside it
    gave the official her own, and the model called the official a third party."""
    from sever.decide.placeholders import PlaceholderPolicy
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import Offsets

    found = [
        Detection(page=1, offsets=Offsets(0, 12), text="Maeve Yetman",
                  entity_type=EntityType.PERSON, score=1.0, recogniser="t")
    ]
    policy = PlaceholderPolicy.for_detections(found)
    witness = policy.apply("Maeve Yetman")
    official = policy.span_in("Yetman", "To: Odette Yetman <o@example.com>")
    assert official is not None and official != witness
    assert official in policy.apply("To: Odette Yetman <o@example.com>")
    assert policy.span_in("Yetman", "From: Maeve Yetman") is None
