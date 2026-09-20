"""Where an unusual name is found and where it is lost.

`results/names.md` reports that person recall falls on the name shapes of this province.
These tests say *why*, because the number on its own points at the wrong fix.

The finding, in one line: **an unusual token standing alone is missed, and an unusual token
with a neighbour is found.** A forename, an honorific or ordinary prose around it rescues
every shape tested here. A bare surname in a distribution list or a signature block, or a
bare forename in prose, is where the recall goes.

That makes this a lexical coverage problem rather than a character-class one. Project 04's
second pass was blind to accented and Mac-prefixed names as a matter of character classes,
and fixing that was right, but it cannot reach these misses: they happen in the first-pass
model, in positions where there is no context for any model to reason from. The fix is a
gazetteer or a document-wide sweep of the name parts already detected elsewhere in the same
record, which is the trick `sever.decide.placeholders` already uses for the outbound
boundary and the detector does not yet use for detection.

The positive half is asserted here. The negative half is deliberately not: a test that
asserts a miss would have to be rewritten the day the miss is fixed, and it is recorded in
`results/names.md` and PLAN.md section 12.10 instead.
"""

from __future__ import annotations

import pytest

from sever.ingest.document import BlockKind

from .conftest import make_document

# Escapes rather than literals, so a re-encoding cannot turn these back into ASCII.
# Labrador surnames, which are the point rather than a sixth shape. No accent, no
# apostrophe, no internal capital: orthographically they are indistinguishable from
# Doucette. What they are is outside a model trained on English news, which is the actual
# mechanism behind every number in results/names.md.
LABRADOR = [
    pytest.param("Igloliorte", id="igloliorte"),
    pytest.param("Onalik", id="onalik"),
    pytest.param("Tuglavina", id="tuglavina"),
    pytest.param("Merkuratsuk", id="merkuratsuk"),
    pytest.param("Penashue", id="penashue"),
    pytest.param("Nuna", id="nuna"),
]

SHAPES = [
    pytest.param("Doucette", id="plain"),
    pytest.param("O'Brien", id="apostrophe"),
    pytest.param("MacDonald", id="mac"),
    pytest.param("Duhé", id="accent"),
    pytest.param("Coady-Vokey", id="hyphen"),
    pytest.param("St. Croix", id="particle"),
    pytest.param("Le Drew", id="particle-two"),
]

FORENAMES = [
    pytest.param("Bernadette", id="plain"),
    pytest.param("Seán", id="sean"),
    pytest.param("Renée", id="renee"),
    pytest.param("Zoé", id="zoe"),
    pytest.param("Sinéad", id="sinead"),
]


def found_people(detector, text: str, kind: BlockKind = BlockKind.BODY) -> list[str]:  # type: ignore[no-untyped-def]
    doc = make_document([(kind, text)])
    return [d.text for d in detector.detect(doc) if d.entity_type.value == "person"]


@pytest.mark.parametrize("surname", SHAPES)
@pytest.mark.parametrize(
    ("label", "kind", "template"),
    [
        ("prose", BlockKind.BODY, "The complainant Bernadette {s} wrote to the department."),
        ("signature", BlockKind.SIGNATURE, "Sincerely,\nBernadette {s}\nRegional Director"),
        ("list", BlockKind.BODY, "Present: Bernadette {s}, Hugh Mercer, Fiona Tobin."),
    ],
)
def test_a_forename_rescues_every_surname_shape(detector, surname, label, kind, template) -> None:  # type: ignore[no-untyped-def]
    """The load-bearing half. Whatever the surname looks like, a forename beside it is
    enough in prose, in a signature block and in a distribution list.

    This is why the remedy is lexical rather than orthographic: the detector is not
    confused by the apostrophe or the accent, it is short of evidence when the token is
    alone.
    """
    found = found_people(detector, template.format(s=surname), kind)
    assert any(surname in f for f in found), f"{surname!r} in a {label}: {found}"


@pytest.mark.parametrize("forename", FORENAMES)
def test_an_honorific_rescues_every_forename_shape(detector, forename) -> None:  # type: ignore[no-untyped-def]
    """The same property from the other side. A bare accented forename is the single
    costliest shape measured (7.4 points of person recall), and one preceding word fixes
    it."""
    found = found_people(detector, f"Ms {forename} confirmed the appointment.")
    assert any(forename in f for f in found), f"{forename!r} after an honorific: {found}"


@pytest.mark.parametrize("surname", SHAPES)
def test_an_honorific_rescues_a_bare_surname(detector, surname) -> None:  # type: ignore[no-untyped-def]
    found = found_people(detector, f"Ms {surname} attended the meeting.")
    assert any(surname in f for f in found), f"{surname!r} after an honorific: {found}"


@pytest.mark.parametrize("surname", LABRADOR)
def test_a_forename_rescues_a_labrador_surname_too(detector, surname) -> None:  # type: ignore[no-untyped-def]
    """The same property on names with no orthographic peculiarity at all.

    This is what says the mechanism is vocabulary rather than spelling. Igloliorte and
    Doucette are the same shape to a tokeniser; one is in the model's vocabulary and the
    other is not, and only the second is lost when it stands alone.

    It is also the answer to a question project 04 asked twice about caseless scripts.
    Labrador Inuttitut in government records is written in Latin script, so the gap in
    this jurisdiction is not the alphabet. It is that a detector trained on English news
    has never seen these names, and a person whose name a tool cannot read is a person
    whose privacy it cannot protect.
    """
    found = found_people(detector, f"The complainant Bernadette {surname} wrote in March.")
    assert any(surname in f for f in found), f"{surname!r} beside a forename: {found}"


@pytest.mark.parametrize("surname", LABRADOR)
def test_the_sweep_recovers_a_bare_labrador_surname(detector, surname) -> None:  # type: ignore[no-untyped-def]
    """And the document-wide sweep is what closes it, on the names that most need it.

    The record names the person once in a position the model can read; the sweep carries
    that to the distribution list where it cannot.
    """
    doc = make_document(
        [
            (BlockKind.BODY, f"The complainant Bernadette {surname} wrote in March."),
            (BlockKind.BODY, f"Present: {surname}, Hugh Mercer, Fiona Tobin."),
        ]
    )
    people = [d for d in detector.detect(doc) if d.entity_type.value == "person"]
    on_the_list = [d for d in people if d.page == 1 and d.text == surname]
    assert on_the_list, (
        f"{surname!r} standing alone was not recovered even though the record names them "
        f"in the sentence above: {[d.text for d in people]}"
    )


def test_the_name_parts_needed_for_the_fix_are_already_known_to_the_policy() -> None:
    """The remedy is not speculative: the document-wide policy already derives exactly the
    aliases a detection sweep would need.

    `PlaceholderPolicy.for_detections` takes a detected "Bernadette Le Drew" and registers
    "bernadette" and "drew" as aliases, because the outbound boundary had the same problem
    and solved it. Detection does not yet use the same information, which is the gap
    PLAN.md section 12.10 records.
    """
    from sever.decide.placeholders import PlaceholderPolicy
    from sever.detect.types import Detection, EntityType
    from sever.ingest.document import Offsets

    name = "Bernadette Le Drew"
    policy = PlaceholderPolicy.for_detections(
        [
            Detection(
                page=1,
                offsets=Offsets(0, len(name)),
                text=name,
                entity_type=EntityType.PERSON,
                score=0.9,
                recogniser="test",
            )
        ]
    )
    substituted = policy.apply("Bernadette signed it and Drew countersigned it.")
    assert "Bernadette" not in substituted, substituted
    assert "Drew" not in substituted, substituted
