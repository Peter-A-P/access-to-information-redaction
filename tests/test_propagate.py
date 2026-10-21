"""Withhold a value once, and every exact occurrence of it in the record is withheld.

The direction is the whole point. Withholding spreads and releasing never does; a spread
never overrules something the reviewer decided; a spread to a span the tool proposed to
release withholds it under a withholding code, never the tool's keep code; and the study is
untouched, because three reviewers were timed without this.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sever.decide.pipeline import Proposal, Source
from sever.detect.types import Detection, EntityType
from sever.ingest.document import Document, DocumentType, Offsets, Page
from sever.review.app import create_app
from sever.review.audit import Action
from sever.review.propagate import PROPAGATED_REASON, occurrences, value_pattern
from sever.review.session import Item, Mode, Session, build_session
from sever.taxonomy.loader import default_taxonomy

PAGE_1 = "Odette Tulk wrote on 3 May. Her number is 709-555-0134. Aaron Penashue replied."
PAGE_2 = (
    "A second letter from ODETTE TULK, telephone 709 555 0134.\n"
    "Tulk alone is not enough. Aaron Penashue, Director, signed."
)
PAGE_3 = "Odette\nTulk called again. Odette Tulk-Byrne is her cousin."


def record() -> Document:
    return Document(
        doc_id="rec-1",
        doc_type=DocumentType.CORRESPONDENCE,
        pages=tuple(
            Page(number=n, text=t) for n, t in enumerate((PAGE_1, PAGE_2, PAGE_3), start=1)
        ),
    )


def proposal(doc: Document, page: int, text: str, code: str, *, nth: int = 0) -> Proposal:
    body = doc.page(page).text
    start = -1
    for _ in range(nth + 1):
        start = body.index(text, start + 1)
    taxonomy = default_taxonomy()
    return Proposal(
        detection=Detection(
            page=page,
            offsets=Offsets(start, start + len(text)),
            text=text,
            entity_type=EntityType.PERSON,
            score=0.9,
            recogniser="test",
        ),
        code=code,
        decision=taxonomy.decision(code),
        confidence=0.9,
        reason="test",
        source=Source.RULE,
    )


@pytest.fixture
def doc() -> Document:
    return record()


@pytest.fixture
def proposals(doc: Document) -> tuple[Proposal, ...]:
    return (
        proposal(doc, 1, "Odette Tulk", "R1"),
        proposal(doc, 1, "Aaron Penashue", "E1"),
        proposal(doc, 2, "ODETTE TULK", "R1"),  # exact, withholding
        proposal(doc, 2, "Aaron Penashue", "K2"),  # the tool proposed to release it
    )


@pytest.fixture
def session(doc: Document, proposals: tuple[Proposal, ...], tmp_path: Path) -> Iterator[Session]:
    s = build_session(
        request_id="R-1",
        items=[Item(document=doc, proposals=proposals)],
        log_path=tmp_path / "audit.duckdb",
        mode=Mode.PROPOSALS,
        actor="tester",
    )
    yield s
    s.log.close()


def withhold(session: Session, p: Proposal) -> int:
    o = p.detection.offsets
    session.record(
        doc_id="rec-1",
        page=p.page,
        action=Action.APPROVE,
        span_start=o.start,
        span_end=o.end,
        span_text=p.detection.text,
        proposed_code=p.code,
        final_code=p.code,
    )
    return len(
        session.spread_withholding(doc_id="rec-1", page=p.page, start=o.start, end=o.end, code=p.code)
    )


def final(session: Session) -> dict[tuple[int, str], bool]:
    doc = session.item("rec-1").document
    return {
        (f.page, doc.page(f.page).text[f.start : f.end]): f.withholds
        for f in session.final_spans("rec-1")
    }


# --- what counts as the same value ----------------------------------------------------


def test_a_full_name_is_found_whatever_its_case_accents_or_line_break(doc: Document) -> None:
    found = [(o.page, doc.page(o.page).text[o.offsets.start : o.offsets.end]) for o in occurrences(doc, "Odette Tulk")]

    assert found == [(1, "Odette Tulk"), (2, "ODETTE TULK"), (3, "Odette\nTulk")]
    assert value_pattern("Odétte Tulk") is not None
    assert occurrences(doc, "Odétte Tulk") == occurrences(doc, "Odette Tulk")


def test_a_name_inside_a_longer_name_is_not_the_same_value(doc: Document) -> None:
    """ "Odette Tulk-Byrne" is somebody else."""
    texts = [doc.page(o.page).text[o.offsets.start : o.offsets.end] for o in occurrences(doc, "Odette Tulk")]
    assert "Odette Tulk-Byrne" not in " ".join(texts)
    assert len(texts) == 3


def test_an_identifier_matches_on_its_digits(doc: Document) -> None:
    pages = [o.page for o in occurrences(doc, "709-555-0134")]
    assert pages == [1, 2]


@pytest.mark.parametrize("value", ["Tulk", "page 12", "s. 19(1)", "Director"])
def test_a_single_word_or_a_short_number_does_not_spread(value: str) -> None:
    """"Tulk" alone could be another Tulk."""
    assert value_pattern(value) is None


def test_an_email_is_matched_whole() -> None:
    doc = Document(
        doc_id="e",
        doc_type=DocumentType.EMAIL_CHAIN,
        pages=(Page(number=1, text="a.tulk@gov.nl.ca.example wrote; copy a.tulk@gov.nl.ca.example.org too"),),
    )
    found = occurrences(doc, "a.tulk@gov.nl.ca.example")
    assert len(found) == 1, "a longer address is a different address"


# --- the session -------------------------------------------------------------------------


def test_withholding_reaches_every_other_occurrence(session: Session, proposals: tuple[Proposal, ...]) -> None:
    spread = withhold(session, proposals[0])

    assert spread == 2  # page 2's proposal, and page 3's occurrence the tool never drew
    decided = final(session)
    assert decided[(2, "ODETTE TULK")] is True
    assert decided[(3, "Odette\nTulk")] is True


def test_a_spread_to_a_span_the_tool_would_release_withholds_it(
    session: Session, proposals: tuple[Proposal, ...]
) -> None:
    """The reviewer withholds an E1 on page 1; page 2's K2 proposal for the same name is
    withheld too, under R1 rather than the keep code."""
    withhold(session, proposals[1])

    assert final(session)[(2, "Aaron Penashue")] is True
    rows = [r for r in session.log.rows(request_id="R-1") if r.page == 2]
    assert rows[-1].final_code is not None
    assert default_taxonomy().decision(rows[-1].final_code).withholds


def test_withholding_a_keep_proposal_never_spreads_a_keep_code(
    session: Session, proposals: tuple[Proposal, ...]
) -> None:
    """Pressing Withhold on page 2's K2 proposal records K2 as the code. Spreading that
    code to page 1's undecided E1 would release it."""
    withhold(session, proposals[3])

    assert final(session)[(1, "Aaron Penashue")] is True


def test_a_spread_never_overrules_the_reviewer(session: Session, proposals: tuple[Proposal, ...]) -> None:
    released = proposals[2]
    o = released.detection.offsets
    session.record(
        doc_id="rec-1",
        page=2,
        action=Action.REJECT,
        span_start=o.start,
        span_end=o.end,
        span_text=released.detection.text,
        proposed_code="R1",
    )

    withhold(session, proposals[0])

    assert final(session)[(2, "ODETTE TULK")] is False, "the reviewer released it; it stays released"


def test_every_spread_is_its_own_logged_row_naming_where_it_came_from(
    session: Session, proposals: tuple[Proposal, ...]
) -> None:
    before = len(session.log.rows(request_id="R-1"))
    withhold(session, proposals[0])
    # The reviewer's own row first, then one per spread.
    rows = session.log.rows(request_id="R-1")[before + 1 :]

    assert len(rows) == 2
    assert all(r.reason == f"{PROPAGATED_REASON} on page 1." for r in rows)
    ok, message = session.log.verify_chain()
    assert ok, message


def test_doing_it_twice_adds_nothing(session: Session, proposals: tuple[Proposal, ...]) -> None:
    withhold(session, proposals[0])
    assert withhold(session, proposals[0]) == 0


def test_off_means_off(session: Session, proposals: tuple[Proposal, ...]) -> None:
    session.propagate_withholding = False
    assert withhold(session, proposals[0]) == 0


def test_the_study_runs_without_it(tmp_path: Path) -> None:
    from sever.review.study import open_trial

    run = open_trial(root=tmp_path / "trial")
    assert run.session.propagate_withholding is False
    run.session.log.close()


# --- the screen ----------------------------------------------------------------------------


@pytest.fixture
def client(session: Session) -> TestClient:
    return TestClient(create_app(session))


def post(client: TestClient, p: Proposal, action: str) -> str:
    o = p.detection.offsets
    response = client.post(
        f"/doc/rec-1/page/{p.page}/span",
        data={"start": str(o.start), "end": str(o.end), "action": action},
    )
    assert response.status_code == 200
    return str(response.text)


def test_the_screen_says_where_else_it_was_withheld(
    client: TestClient, session: Session, proposals: tuple[Proposal, ...]
) -> None:
    body = post(client, proposals[0], "approve")

    assert "also withheld in 2 other places" in body
    assert "pages 2, 3" in body


def test_release_on_the_screen_spreads_nothing(
    client: TestClient, session: Session, proposals: tuple[Proposal, ...]
) -> None:
    body = post(client, proposals[0], "reject")

    assert "also withheld" not in body
    assert session.acted_spans("rec-1", 2) == {}


def test_escalate_spreads_nothing(client: TestClient, session: Session, proposals: tuple[Proposal, ...]) -> None:
    post(client, proposals[0], "escalate")
    assert session.acted_spans("rec-1", 2) == {}
