"""No raw detected entity leaves the boundary.

CLAUDE.md states this as a rule of the repository and PLAN.md section 2.3 states it as the
composition argument the whole project exists to demonstrate: a frontier model used on
access-to-information records without personal data reaching the vendor.

The test does not check one hand-written request. It builds the outbound request for every
residual span in the generated corpus and asserts that no persona's name, address,
telephone number, email, health number or file number appears in any of them, in literal,
accent-normalised or digits-only form. The personas are the ground truth here, which is
stronger than checking against the detector's own output: a name the detector missed is
exactly the one that would slip through a guard built from detections alone.
"""

from __future__ import annotations

import json

import pytest

from sever.context.record import ContextBuilder
from sever.context.requester import RequestConfig, normalise, normalise_identifier
from sever.decide.model import SYSTEM_PROMPT, GatewayModelDecider, parse_answer
from sever.decide.placeholders import PlaceholderPolicy, RawEntityLeak
from sever.decide.rules import apply as apply_rules
from sever.taxonomy.loader import default_taxonomy

# Values shorter than this are not distinctive enough for a containment test to mean
# anything: a three-letter fragment occurs in ordinary English.
MIN_LENGTH = 5


def _persona_secrets(cast) -> list[str]:  # type: ignore[no-untyped-def]
    out: list[str] = []
    for persona in cast.values():
        for field_name in (
            "full_name",
            "given_name",
            "surname",
            "home_address",
            "postal_code",
            "personal_email",
            "personal_phone",
            "work_email",
            "work_phone",
            "date_of_birth",
            "mcp",
            "sin",
            "file_number",
            "employee_id",
        ):
            value = getattr(persona, field_name, None)
            if value and len(str(value)) >= MIN_LENGTH:
                out.append(str(value))
    return out


def test_no_persona_value_appears_in_any_outbound_request(corpus, detector) -> None:  # type: ignore[no-untyped-def]
    decider = GatewayModelDecider(enabled=True)
    offenders: list[str] = []
    requests_built = 0

    for item in corpus:
        doc = item.rendered.document
        detections = tuple(detector.detect(doc))
        contexts = ContextBuilder(
            config=RequestConfig(request_id=doc.doc_id, requester_name="")
        ).build(doc, detections)
        residual = [c for c in contexts if not apply_rules(c).decided_by_rule]
        if not residual:
            continue
        # The universe, not the residual. Building it from the residual is the bug this
        # test caught the first time it ran.
        policy = GatewayModelDecider.policy_for(residual, contexts)
        secrets = _persona_secrets(item.rendered.cast)

        for ctx in residual:
            message, payload = decider.build_request(ctx, policy)
            requests_built += 1
            body = SYSTEM_PROMPT + "\n" + message + "\n" + json.dumps(payload, sort_keys=True)
            lowered = body.casefold()
            normalised = normalise(body)
            digits = normalise_identifier(body)
            for secret in secrets:
                if secret.casefold() in lowered:
                    offenders.append(f"{doc.doc_id}: {secret!r} in the request body")
                    continue
                n = normalise(secret)
                if n and n in normalised:
                    offenders.append(f"{doc.doc_id}: {secret!r} (normalised) in the request")
                    continue
                if any(c.isdigit() for c in secret):
                    d = normalise_identifier(secret)
                    if len(d) >= 6 and d in digits:
                        offenders.append(f"{doc.doc_id}: {secret!r} (digits only) in the request")

    assert requests_built > 0, (
        "no residual spans in the whole corpus, so this test proved nothing. Either the "
        "rules now decide everything, or the corpus is not being built."
    )
    assert not offenders, (
        f"{len(offenders)} raw values would have left the boundary in "
        f"{requests_built} requests:\n  " + "\n  ".join(sorted(set(offenders))[:10])
    )


def test_the_guard_refuses_rather_than_warning() -> None:
    """The property is enforced in the code path, not only in this file."""
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import Offsets

    policy = PlaceholderPolicy.for_detections(
        [
            Detection(
                page=1,
                offsets=Offsets(0, 14),
                text="Marie Doucette",
                entity_type=EntityType.PERSON,
                score=0.9,
                recogniser="test",
            )
        ]
    )
    with pytest.raises(RawEntityLeak, match="Nothing was sent"):
        policy.guard("A request that still mentions Marie Doucette by name.")


def test_the_guard_catches_a_reformatted_telephone_number() -> None:
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import Offsets

    policy = PlaceholderPolicy.for_detections(
        [
            Detection(
                page=1,
                offsets=Offsets(0, 12),
                text="709-555-0142",
                entity_type=EntityType.PHONE,
                score=0.9,
                recogniser="test",
            )
        ]
    )
    with pytest.raises(RawEntityLeak):
        policy.guard("Contact number 7095550142 on the file.")


def test_placeholders_are_stable_across_a_document() -> None:
    """The same person gets the same placeholder everywhere, or the model cannot reason
    about consistency across the record."""
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import Offsets

    def det(page: int, start: int, text: str) -> Detection:
        return Detection(
            page=page,
            offsets=Offsets(start, start + len(text)),
            text=text,
            entity_type=EntityType.PERSON,
            score=0.9,
            recogniser="test",
        )

    policy = PlaceholderPolicy.for_detections(
        [det(1, 0, "Marie Doucette"), det(3, 40, "Marie Doucette"), det(2, 5, "Aaron Byrne")]
    )
    a = policy.apply("Marie Doucette wrote to Aaron Byrne.")
    b = policy.apply("On page three, Marie Doucette replied.")
    assert "[PERSON_" in a and "[PERSON_" in b
    first = a.split()[0]
    assert first in b, f"the same person got different placeholders: {a!r} and {b!r}"


def test_the_longer_name_is_substituted_first() -> None:
    """Otherwise "Doucette" is replaced inside "Marie Doucette" and the forename survives."""
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import Offsets

    policy = PlaceholderPolicy.for_detections(
        [
            Detection(1, Offsets(0, 8), "Doucette", EntityType.PERSON, 0.9, "t"),
            Detection(1, Offsets(20, 34), "Marie Doucette", EntityType.PERSON, 0.9, "t"),
        ]
    )
    out = policy.apply("Marie Doucette signed it; Doucette also initialled it.")
    assert "Marie" not in out, out
    assert "Doucette" not in out, out


def test_an_off_taxonomy_answer_is_discarded_not_coerced() -> None:
    t = default_taxonomy()
    assert parse_answer('{"code": "X9", "confidence": 0.99}', t) is None
    assert parse_answer("not json at all", t) is None
    good = parse_answer('{"code": "K2", "confidence": 0.9, "evidence": "title"}', t)
    assert good is not None and good.code == "K2"


def test_the_model_layer_is_off_by_default() -> None:
    """A corpus run is thousands of calls. The safe default cannot spend anything."""
    assert GatewayModelDecider().enabled is False
    from sever.context.record import ContextRecord
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import DocumentType, Offsets

    ctx = ContextRecord(
        detection=Detection(1, Offsets(0, 5), "thing", EntityType.PERSON, 0.5, "t"),
        doc_id="d",
        doc_type=DocumentType.OTHER,
        page_number=1,
        pages_in_document=1,
    )
    assert GatewayModelDecider().decide([ctx]) == [None]
