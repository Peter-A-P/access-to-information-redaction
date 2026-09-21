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


def test_no_persona_value_leaves_when_the_names_are_this_province_s(detector) -> None:  # type: ignore[no-untyped-def]
    """The same property, on the name shapes the published corpus does not contain.

    This is the test that would have caught the bug `tests/test_scrub_shapes.py` documents.
    The corpus above is plain ASCII, so the second pass could be blind to accented names,
    to Mac and Mc surnames and to half of O'Brien while every assertion in this file
    passed. It was, and the report came from project 04 rather than from here.

    A second consideration this profile is the only way to reach: the personas' email
    addresses are transliterated, as a real directory writes them, so the page says
    "Duhe" with an acute accent and the address says `duhe`. A boundary that substitutes
    only the exact surface form replaces the name and ships the surname inside the
    address. The normalised comparison below is what catches that.
    """
    from sever.corpus.generate import build
    from sever.corpus.personas import NameProfile

    decider = GatewayModelDecider(enabled=True)
    offenders: list[str] = []
    requests_built = 0

    for item in build(documents=12, names=NameProfile.NL):
        doc = item.rendered.document
        detections = tuple(detector.detect(doc))
        contexts = ContextBuilder(
            config=RequestConfig(request_id=doc.doc_id, requester_name="")
        ).build(doc, detections)
        residual = [c for c in contexts if not apply_rules(c).decided_by_rule]
        if not residual:
            continue
        policy = GatewayModelDecider.policy_for(residual, contexts)
        secrets = _persona_secrets(item.rendered.cast)

        for ctx in residual:
            message, payload = decider.build_request(ctx, policy)
            requests_built += 1
            body = "\n".join([SYSTEM_PROMPT, message, json.dumps(payload, sort_keys=True)])
            lowered = body.casefold()
            normalised = normalise(body)
            for secret in secrets:
                if secret.casefold() in lowered:
                    offenders.append(f"{doc.doc_id}: {secret!r} in the request body")
                    continue
                n = normalise(secret)
                if n and n in normalised:
                    offenders.append(f"{doc.doc_id}: {secret!r} (normalised) in the request")

    assert requests_built > 0, "no residual spans, so this test proved nothing"
    assert not offenders, (
        f"{len(offenders)} raw values would have left the boundary in {requests_built} "
        f"requests built from names with apostrophes, accents and Mac or Mc prefixes:\n  "
        + "\n  ".join(sorted(set(offenders))[:10])
    )


def test_the_guard_does_not_fire_on_a_name_part_inside_an_ordinary_word() -> None:
    """A whole-word match, not a substring one.

    Found by the Newfoundland name profile. A document-wide policy licenses the parts of a
    name, so the surname Le Drew puts "drew" on the guarded list, and "drew" is inside
    "withdrew". A meeting minute recording that a delegation withdrew refused to send.

    Fail-closed means that cost a run rather than a person, so it was never a leak. It is
    still worth a test: a guard that refuses ordinary English teaches whoever maintains it
    to route around it, and that is how a real guard gets disabled.
    """
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import Offsets

    policy = PlaceholderPolicy.for_detections(
        [
            Detection(
                page=1,
                offsets=Offsets(0, 18),
                text="Bernadette Le Drew",
                entity_type=EntityType.PERSON,
                score=0.9,
                recogniser="test",
            )
        ]
    )
    # The ordinary word is fine.
    policy.guard("The delegation withdrew and the meeting resumed.")
    # The name itself is still refused, in whole or in part.
    with pytest.raises(RawEntityLeak):
        policy.guard("Bernadette Le Drew attended.")
    with pytest.raises(RawEntityLeak):
        policy.guard("Ms Drew attended.")


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


# --- the backstop, measured with the detector taken away --------------------------


def test_the_second_pass_alone_holds_most_of_the_corpus(corpus) -> None:  # type: ignore[no-untyped-def]
    """Every request in the corpus, built with no detections at all.

    Project 04, 2026-09-20, after their own masking column read 100 percent everywhere:
    "a masking column where a recogniser is doing the work says nothing about the layer
    that exists for when a recogniser is wrong." They now run every case twice, once as
    normal and once with every recogniser removed, and it found two holes immediately.

    The point applies here exactly. Every assertion above passes with the detector on, and
    passed while `scrub_unrecognised` let every email address and every postal code through
    untouched, because the recognisers were covering both. The only way to ask the backstop
    a question is to take the first layer away, so this builds the policy from an empty
    detection set: nothing is substituted, and whatever does not appear in the request was
    masked by the second pass on shape alone.

    The answer is that it holds all of it: every persona value on every page, with no
    detector at all.

    That number needs 04's own warning turned back on it. It reads 100 percent because
    every secret this corpus puts on a page is name-shaped, digit-shaped, address-shaped or
    postcode-shaped, and those are the four shapes the second pass knows. The shape known to
    defeat it, a date written out in words, is one this corpus never generates: persona
    dates of birth are ISO. So this measures the backstop against the shapes somebody
    thought to generate, exactly like every recall figure here, and the companion tests name
    what it cannot reach so the 100 does not read as completeness.
    """
    from sever.decide.placeholders import scrub_unrecognised

    total = 0
    survived: list[str] = []

    for item in corpus:
        doc = item.rendered.document
        secrets = _persona_secrets(item.rendered.cast)
        page_text = "\n\n".join(p.text for p in doc)
        scrubbed = scrub_unrecognised(page_text)
        lowered = scrubbed.casefold()
        digits = normalise_identifier(scrubbed)
        for secret in secrets:
            if secret not in page_text:
                continue
            total += 1
            d = normalise_identifier(secret)
            if secret.casefold() in lowered or (len(d) >= 6 and d in digits):
                survived.append(f"{doc.doc_id}: {secret!r}")

    assert total > 0, "no persona values reached the pages, so this proved nothing"
    assert not survived, (
        f"{len(survived)} of {total} persona values survived the second pass with no "
        f"detector present. This was exact when written, so a survivor is a new hole "
        f"rather than a known limit; the known limits are in the test below.\n  "
        + "\n  ".join(sorted(set(survived))[:12])
    )


def test_the_shapes_the_backstop_cannot_reach_are_named_rather_than_discovered() -> None:
    """A stated limit with a test on it, so a future change to the judgement is visible.

    A date written out in words has no backstop. "14 March 1978" is a date of birth and the
    second pass leaves it alone, because masking every written date would black out the
    dates a decision turns on: whether someone died more than twenty years ago is the whole
    of K4, and the year is what answers it. The recogniser handles this shape by requiring a
    label word in front of it, which is the same judgement made where there is enough
    context to make it.

    Project 04 reached the identical conclusion on the identical shape the same day and left
    it at 66.7 percent rather than masking it. Recording it here means the next person to
    change their mind has to change a test, rather than discovering the gap in a release.
    """
    from sever.decide.placeholders import scrub_unrecognised

    assert scrub_unrecognised("14 March 1978") == "14 March 1978"
    assert scrub_unrecognised("Date of birth: 14 March 1978") == "Date of birth: 14 March 1978"
    # The digit forms are covered, which is what makes the gap specific rather than general.
    assert scrub_unrecognised("1978-03-14") == "[NUMBER?]"
    assert scrub_unrecognised("14/03/1978") == "[NUMBER?]"


def test_the_backstop_holds_the_name_shapes_this_province_actually_uses() -> None:
    """The same question as the corpus-wide one, on shapes the corpus cannot produce.

    The published corpus is plain ASCII, so a backstop measured only against it is measured
    against the easy half of the province. These are the shapes that got past this function
    in 0.5.2, plus the accented address project 04 found getting past theirs and the
    bracketed phone number they found half-masked.
    """
    from sever.decide.placeholders import scrub_unrecognised

    shapes = (
        "Renée Côté",
        "MacDonald",
        "O'Brien",
        "Le Drew",
        "Tuglavina",
        "thérèse.gagné@example.gov.nl.ca",
        "(709) 555-0199",
        "A1B 2C3",
    )
    survived = [
        shape for shape in shapes if shape in scrub_unrecognised(f"The record names {shape}.")
    ]
    assert not survived, f"the backstop let these through with no detector: {survived}"
