"""What a Defence record says about the people and strings in it.

The real-record track is Defence records, and on them the tool withheld every span that
could be personal information. Ranks were read as people, units and headquarters were read
as people, OCR fragments were read as people, and an officer named with their rank was a
stranger. These tests hold the fixes, and the guards that keep them from reaching records
the forces did not write.
"""

from __future__ import annotations

import pytest

from sever.context.record import ContextBuilder
from sever.context.requester import RequestConfig
from sever.decide import rules
from sever.detect.engine import SeverDetector
from sever.detect.military import (
    classify_person_span,
    has_name_shaped_token,
    is_military_record,
    rank_beside,
    screen,
)
from sever.detect.recognisers import RANK
from sever.detect.types import Detection, EntityType
from sever.ingest.document import BlockKind, Offsets

from .conftest import make_document

DEFENCE = "National Defence\nJoint Task Force Afghanistan"


def person(text: str, page_text: str, *, nth: int = 0) -> Detection:
    start = -1
    for _ in range(nth + 1):
        start = page_text.index(text, start + 1)
    return Detection(
        page=1,
        offsets=Offsets(start, start + len(text)),
        text=text,
        entity_type=EntityType.PERSON,
        score=0.85,
        recogniser="test",
    )


# --- the rank recogniser -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rank"),
    [
        ("LCol Kromrey", "LCol"),
        ("Goudie Capt", "Capt"),
        ("CAPT THORNE", "CAPT"),
        ("Lieutenant-Colonel Perras", "Lieutenant-Colonel"),
        ("Master Warrant Officer Ray", "Master Warrant Officer"),
    ],
)
def test_a_rank_is_found_in_its_short_long_and_capital_forms(text: str, rank: str) -> None:
    assert [m[2] for m in RANK.finditer(text)] == [rank]


@pytest.mark.parametrize(
    "text",
    [
        "Colm Quirke",  # a forename that starts with a rank
        "Cormier Maj LT@Deployed@KAF",  # "LT" here is initials
        "the col of the hill",  # case matters
        "the Attorney General",  # not a rank list entry
        "a private citizen",
    ],
)
def test_what_is_not_a_rank(text: str) -> None:
    found = [m[2] for m in RANK.finditer(text)]
    assert "LT" not in found and "col" not in found and "General" not in found
    if text.startswith("Colm"):
        assert found == []


# --- the screen ------------------------------------------------------------------


@pytest.mark.parametrize("text", ["wu", "pour lui", "dés 22h00", ".19(1", "OK2"])
def test_a_span_with_no_name_shaped_token_is_not_a_name(text: str) -> None:
    assert not has_name_shaped_token(text)


@pytest.mark.parametrize("text", ["Kromrey", "CARRIERE", "B.F", "J.H.C. Drouin", "Ou"])
def test_a_span_with_a_name_shaped_token_may_be(text: str) -> None:
    assert has_name_shaped_token(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("LCol", EntityType.JOB_TITLE),
        ("TFK Comd", EntityType.JOB_TITLE),
        ("the TFK Comd", EntityType.JOB_TITLE),
        ("KAF", EntityType.ORGANISATION),
        ("CEFCOM J1", EntityType.ORGANISATION),
        ("JTF-Afg", EntityType.ORGANISATION),
        ("DGIC@Ottawa-Hull", EntityType.ORGANISATION),
        ("LCol Kromrey", None),
        ("Goudie Capt", None),
        ("Hetherington Col SC@Deployed@KAF", None),
    ],
)
def test_vocabulary_spans_are_retyped_and_people_with_ranks_are_not(
    text: str, expected: EntityType | None
) -> None:
    assert classify_person_span(text) is expected


def test_the_screen_retypes_units_only_in_a_military_record() -> None:
    """"Wing" and "Unit" are ordinary words and "Capt" is a ship's master in a fisheries
    record; the vocabulary means something only where the forces wrote it."""
    text = "KAF reported. Kromrey attended."
    civilian = make_document([(BlockKind.BODY, text)])
    military = make_document([(BlockKind.BODY, DEFENCE), (BlockKind.BODY, text)])

    assert not is_military_record(civilian)
    assert is_military_record(military)

    on_civilian = screen(civilian, [person("KAF", civilian.page(1).text)])
    on_military = screen(military, [person("KAF", military.page(1).text)])

    assert on_civilian[0].entity_type is EntityType.PERSON
    assert on_military[0].entity_type is EntityType.ORGANISATION
    assert on_military[0].recogniser.startswith("military:")


def test_the_screen_drops_noise_in_any_record() -> None:
    doc = make_document([(BlockKind.BODY, "wu za Kromrey")])
    text = doc.page(1).text

    kept = screen(doc, [person("wu", text), person("Kromrey", text)])

    assert [d.text for d in kept] == ["Kromrey"]


def test_a_rank_is_never_swept_as_a_name_part(pattern_detector: SeverDetector) -> None:
    """Without this, "LCol Kromrey" licensed every "LCol" in the record as a person and
    re-typed the rank recogniser's own spans back to PERSON."""
    from sever.detect.military import is_rank
    from sever.detect.sweep import with_sweep

    doc = make_document([(BlockKind.BODY, "LCol Kromrey wrote. LCol Gifford replied.")])
    text = doc.page(1).text
    ranks = [
        Detection(
            page=1,
            offsets=Offsets(s, e),
            text=m,
            entity_type=EntityType.JOB_TITLE,
            score=0.9,
            recogniser="rank",
        )
        for s, e, m in RANK.finditer(text)
    ]
    found = with_sweep(doc, [person("LCol Kromrey", text), *ranks[1:]], not_names=is_rank)

    second = [d for d in found if d.offsets.start == ranks[1].offsets.start]
    assert [d.entity_type for d in second] == [EntityType.JOB_TITLE]


# --- what a rank says about the person ------------------------------------------


@pytest.mark.parametrize(
    ("page_text", "name", "rank"),
    [
        ("concern about LCol\nKromrey and follow on", "Kromrey", "LCol"),
        ("To: Gifford LCol SW@Deployed@KAF", "Gifford", "LCol"),
        ("signed by Capt S.C. Goudie today", "Capt S.C. Goudie", "Capt"),
        ("Kromrey said the plan was sound", "Kromrey", None),
    ],
)
def test_rank_beside(page_text: str, name: str, rank: str | None) -> None:
    start = page_text.index(name)
    assert rank_beside(page_text, Offsets(start, start + len(name))) == rank


def contexts(body: str, *, military: bool = True):  # type: ignore[no-untyped-def]
    blocks = [(BlockKind.BODY, DEFENCE)] if military else []
    doc = make_document([*blocks, (BlockKind.BODY, body)])
    text = doc.page(1).text
    detections = [person("Kromrey", text, nth=n) for n in range(text.count("Kromrey"))]
    return ContextBuilder(config=RequestConfig(request_id="t")).build(doc, detections)


def test_a_rank_reaches_every_mention_of_the_person() -> None:
    ctx = contexts("LCol Kromrey chaired the board. The board accepted what Kromrey proposed.")

    assert [c.rank for c in ctx] == ["LCol", "LCol"]


def test_a_rank_outside_a_military_record_says_nothing() -> None:
    ctx = contexts("Capt Kromrey of the trawler reported the catch.", military=False)

    assert ctx[0].rank is None
    assert rules.apply(ctx[0]).outcome.code == "E1"


def test_a_ranked_member_doing_their_work_is_released_as_an_official() -> None:
    ctx = contexts("LCol Kromrey chaired the board and signed the minutes.")

    result = rules.apply(ctx[0])

    assert result.outcome.code == "K2"
    assert result.outcome.rule == "military_rank"
    assert result.outcome.confidence < 0.8, "weaker than a title in a signature block"


@pytest.mark.parametrize(
    "sentence",
    [
        "LCol Kromrey was granted compassionate leave.",
        "LCol Kromrey was injured on the range.",
        "The harassment complaint against LCol Kromrey was received.",
        "LCol Kromrey's medical file was forwarded.",
    ],
)
def test_a_rank_does_not_make_a_member_s_own_life_official_business(sentence: str) -> None:
    """The guard on the rule: a sentence about the member rather than the work escalates,
    and escalation withholds."""
    ctx = contexts(sentence)

    result = rules.apply(ctx[0])

    assert result.outcome.code != "K2"
    assert result.outcome.code.startswith(("E", "R"))
