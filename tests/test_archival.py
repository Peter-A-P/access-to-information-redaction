"""The archival 110-year rule (K7) and the release-stamp screen.

Federally, Library and Archives Canada may disclose personal information once 110 years
have elapsed since the individual's birth. The tool applies that only when the request says
the records are archival, and only on a birth the record itself shows. These tests hold
both halves, and the careful direction of every guess: the latest year on a page, the
latest birth a stated age allows, and no year read out of an identifier.
"""

from __future__ import annotations

import pytest

from sever.context.age import birth_year_beside, page_year
from sever.context.record import ContextBuilder, ContextRecord
from sever.context.requester import RequestConfig
from sever.decide import rules
from sever.detect.stamps import drop_stamp_spans, stamp_lines
from sever.detect.types import Detection, EntityType
from sever.ingest.document import BlockKind, Offsets
from sever.taxonomy.loader import Decision, default_taxonomy

from .conftest import make_document


def span(text: str, page_text: str, kind: EntityType = EntityType.PERSON) -> Detection:
    start = page_text.index(text)
    return Detection(
        page=1,
        offsets=Offsets(start, start + len(text)),
        text=text,
        entity_type=kind,
        score=0.85,
        recogniser="test",
    )


# --- reading the years --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "year"),
    [
        ("Landed at Victoria, 3 May 1913.", 1913),
        ("Recalled in 1951 that he landed in 1913.", 1951),  # the latest, not the first
        ("File dates 1913-1962.", 1962),  # the end of a range counts
        ("Request A-2026-01845, landed 1913.", 1913),  # a request number is not a year
        ("File CH-1-1910, landed 1905.", 1905),  # nor is a file number
        ("No year on this page at all.", None),
    ],
)
def test_page_year_is_the_latest_year_and_never_an_identifier(text: str, year: int | None) -> None:
    assert page_year(text, as_of=2026) == year


def test_a_birth_is_read_only_straight_after_the_name() -> None:
    text = "Wong Ding Yip, aged 54, and his son Wong Ping. Yee Wing (born 1897) came too."
    father = Offsets(0, len("Wong Ding Yip"))
    son = Offsets(text.index("Wong Ping"), text.index("Wong Ping") + len("Wong Ping"))
    yee = Offsets(text.index("Yee Wing"), text.index("Yee Wing") + len("Yee Wing"))

    assert birth_year_beside(text, father, page_year=1951) == 1951 - 54
    assert birth_year_beside(text, son, page_year=1951) is None, "the father's age is not his"
    assert birth_year_beside(text, yee, page_year=1951) == 1897


def test_an_age_without_a_dated_page_gives_no_birth() -> None:
    text = "Gin Wah, age 12, lives with his grandfather."
    assert birth_year_beside(text, Offsets(0, 7), page_year=None) is None


# --- the rule ---------------------------------------------------------------------------


def contexts(body: str, names: list[str], *, archival: bool = True) -> tuple[ContextRecord, ...]:
    doc = make_document([(BlockKind.BODY, body)])
    text = doc.page(1).text
    detections = [
        span(n, text, EntityType.KINSHIP if n.islower() else EntityType.PERSON) for n in names
    ]
    config = RequestConfig(request_id="t", archival=archival, as_of_year=2026)
    return ContextBuilder(config=config).build(doc, detections)


def test_everyone_on_a_page_old_enough_is_k7_including_their_family() -> None:
    ctx = contexts(
        "Certificate issued 3 May 1913 to Yee Wing Thue, whose son remains in China.",
        ["Yee Wing Thue", "son"],
    )

    outcomes = [rules.apply(c).outcome for c in ctx]

    assert [o.code for o in outcomes] == ["K7", "K7"]
    assert all(o.rule == "archival_age" for o in outcomes)


def test_a_stated_age_on_a_dated_page_reaches_every_mention_of_the_person() -> None:
    doc_text = (
        "Interview, 12 June 1951. Wong Ding Yip, aged 85, was asked about his village. "
        "Wong Ding Yip said he left in 1913."
    )
    second = doc_text.index("Wong Ding Yip", 30)
    doc = make_document([(BlockKind.BODY, doc_text)])
    both = [
        span("Wong Ding Yip", doc_text),
        Detection(
            page=1,
            offsets=Offsets(second, second + 13),
            text="Wong Ding Yip",
            entity_type=EntityType.PERSON,
            score=0.85,
            recogniser="test",
        ),
    ]
    ctx = ContextBuilder(
        config=RequestConfig(request_id="t", archival=True, as_of_year=2026)
    ).build(doc, both)

    assert [c.birth_year for c in ctx] == [1866, 1866]
    assert [rules.apply(c).outcome.code for c in ctx] == ["K7", "K7"]


def test_a_person_too_young_for_the_rule_is_not_released_by_it() -> None:
    ctx = contexts(
        "Interview, 12 June 1951. Gin Wah, aged 12, lives with his grandfather.",
        ["Gin Wah"],
    )

    assert rules.apply(ctx[0]).outcome.code != "K7"


def test_the_rule_is_off_unless_the_records_are_archival() -> None:
    """How old a page looks is not evidence that an archives holds it. The same 1913
    certificate in a department's active file is not archival."""
    ctx = contexts(
        "Certificate issued 3 May 1913 to Yee Wing Thue.", ["Yee Wing Thue"], archival=False
    )

    assert ctx[0].archival_cutoff is None
    assert rules.apply(ctx[0]).outcome.code != "K7"


def test_the_requester_still_comes_first() -> None:
    doc_text = "Certificate issued 3 May 1913 to Yee Wing Thue."
    doc = make_document([(BlockKind.BODY, doc_text)])
    config = RequestConfig(
        request_id="t", requester_name="Yee Wing Thue", archival=True, as_of_year=2026
    )
    ctx = ContextBuilder(config=config).build(doc, [span("Yee Wing Thue", doc_text)])

    assert rules.apply(ctx[0]).outcome.code == "K1"


def test_k7_is_federal_and_escalates_under_atippa() -> None:
    t = default_taxonomy()
    assert t.decision("K7", "federal") is Decision.KEEP
    assert t.decision("K7", "nl") is Decision.ESCALATE
    sections = {p.section for p in t.provisions("K7", "federal")}
    assert sections == {"19(2)(c)", "8(3)", "6(c)"}


# --- the release stamp -------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Document disclosed under the Access to Information Act",
        "Document divulgué en vertu de Ia Loi sur l\u2019accés a l'information",
        "say Bocument divulgué en vertu de [a Loi sur l\u2019accés a l'information",
        "Document disclosed by the ATIP Branch of Library",
    ],
)
def test_the_stamp_is_found_however_ocr_read_it(line: str) -> None:
    assert stamp_lines(line)


@pytest.mark.parametrize(
    "line",
    [
        "Your request under the Access to Information Act was received on 3 May.",
        "Loi sur la protection des renseignements personnels",
    ],
)
def test_a_line_that_mentions_the_act_is_not_a_stamp(line: str) -> None:
    assert not stamp_lines(line)


def test_a_span_on_the_stamp_is_dropped_and_one_below_it_is_not() -> None:
    body = "Document divulgué en vertu de Ia Loi sur l'accès à l'information\nOdette Tulk wrote."
    doc = make_document([(BlockKind.BODY, body)])
    text = doc.page(1).text

    kept = drop_stamp_spans(doc, [span("Loi sur", text), span("Odette Tulk", text)])

    assert [d.text for d in kept] == ["Odette Tulk"]
