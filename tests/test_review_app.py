"""The reviewer's screen, and the two rules it exists to make true.

The README's second paragraph is a promise: "There is no path from a proposal to a released
document without a reviewer action on every page." Until this application existed that
promise was true in the weak sense that no code released anything at all. Now there is a
button, so the promise needs a test rather than an absence.

Two properties are held here and nothing else matters as much:

  1. **A page is not complete while a span on it is undecided.** The tool proposes; a person
     decides; a person who has not looked at a span has not decided it.
  2. **A record is not releasable while a page is not complete.** The gate raises rather
     than returning false, so a caller that forgets to check it does not release.

Everything else in this file is there to stop those two from being true by accident: that
the unaided arm really has no proposals, that a rejected span does not quietly keep its
category, that an action on a span the tool never proposed is refused unless it is an
addition, and that the page a reviewer sees is rendered from the log rather than from
whatever the browser last posted.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sever.decide.pipeline import DecisionEngine, Proposal
from sever.ingest.document import Block, BlockKind, Document, DocumentType, Offsets, Page
from sever.review.app import create_app
from sever.review.app.main import fragments
from sever.review.audit import Action
from sever.review.session import Item, Mode, NotReviewed, Session, build_session

from .conftest import requester_config

REQUEST = "A-2027-001"

PARAGRAPH_BREAK = "\n\n"

PAGES = (
    (
        "The complainant Odette Tulk wrote to the department in March about her file.",
        "Her address is 14 Bannerman Street, St. John's, and her telephone is 709-555-0134.",
    ),
    (
        "Aaron Penashue, Director of Records, replied on 2 April about a third party.",
        "Marie Chaulk was consulted and her date of birth is 1974-03-02.",
    ),
)


def two_page_record() -> Document:
    """A two-page record, because every rule here is about pages and one page cannot show
    that a document is held back by the page nobody opened."""
    pages = []
    for number, paragraphs in enumerate(PAGES, start=1):
        blocks: list[Block] = []
        pos = 0
        for part in paragraphs:
            blocks.append(
                Block(kind=BlockKind.BODY, offsets=Offsets(pos, pos + len(part)), text=part)
            )
            pos += len(part) + len(PARAGRAPH_BREAK)
        pages.append(
            Page(
                number=number,
                text=PARAGRAPH_BREAK.join(paragraphs),
                blocks=tuple(blocks),
            )
        )
    return Document(doc_id="rev-1", doc_type=DocumentType.CORRESPONDENCE, pages=tuple(pages))


@pytest.fixture
def item(detector) -> Item:  # type: ignore[no-untyped-def]
    """One two-page record with real proposals on it."""
    doc = two_page_record()
    config = requester_config("Odette Tulk")
    proposals = DecisionEngine(config=config, detector=detector).propose(doc)
    return Item(document=doc, proposals=tuple(proposals))


@pytest.fixture
def session(item: Item, tmp_path: Path) -> Iterator[Session]:
    s = build_session(
        request_id=REQUEST,
        items=[item],
        log_path=tmp_path / "audit.duckdb",
        mode=Mode.PROPOSALS,
        timings_path=tmp_path / "timings.jsonl",
        actor="tester",
    )
    yield s
    s.log.close()


@pytest.fixture
def client(session: Session) -> TestClient:
    return TestClient(create_app(session))


def spans_on(session: Session, doc_id: str, page: int) -> tuple[Proposal, ...]:
    return session.item(doc_id).on_page(page)


def act(client: TestClient, doc_id: str, page: int, p: Proposal, action: str, **extra: str) -> int:
    response = client.post(
        f"/doc/{doc_id}/page/{page}/span",
        data={
            "start": str(p.detection.offsets.start),
            "end": str(p.detection.offsets.end),
            "action": action,
            **extra,
        },
    )
    return int(response.status_code)


def decide_page(client: TestClient, session: Session, doc_id: str, page: int) -> None:
    for p in spans_on(session, doc_id, page):
        act(client, doc_id, page, p, "approve")


# --- the two rules --------------------------------------------------------------


def test_a_page_with_an_undecided_span_cannot_be_completed(
    client: TestClient, session: Session, item: Item
) -> None:
    spans = spans_on(session, item.doc_id, 1)
    assert len(spans) > 1, "this test needs a page with more than one span to be meaningful"
    act(client, item.doc_id, 1, spans[0], "approve")

    response = client.post(f"/doc/{item.doc_id}/page/1/complete")

    assert response.status_code == 200
    assert "no decision yet" in response.text
    assert not session.page_complete(item.doc_id, 1)


def test_a_page_where_every_span_has_been_decided_can_be_completed(
    client: TestClient, session: Session, item: Item
) -> None:
    decide_page(client, session, item.doc_id, 1)

    client.post(f"/doc/{item.doc_id}/page/1/complete")

    assert session.page_complete(item.doc_id, 1)


def test_a_record_with_an_unreviewed_page_is_refused_a_release(
    client: TestClient, session: Session, item: Item
) -> None:
    """Page 2 is never opened. The document is not releasable and the endpoint says so."""
    decide_page(client, session, item.doc_id, 1)
    client.post(f"/doc/{item.doc_id}/page/1/complete")

    assert client.post(f"/doc/{item.doc_id}/release").status_code == 409
    # The release screen is a URL, so it can be typed, bookmarked or reloaded. It asks the
    # gate itself rather than trusting that a redirect got it here.
    refused = client.get(f"/doc/{item.doc_id}/released")
    assert refused.status_code == 409
    assert "pages 2" in refused.json()["detail"]


def test_the_gate_raises_rather_than_returning_false(session: Session, item: Item) -> None:
    """A caller that forgets to check a boolean releases the document. A caller that
    forgets to catch an exception does not, which is why this is the shape it is."""
    with pytest.raises(NotReviewed, match="pages 1, 2"):
        session.release_gate(item.doc_id)


def test_a_record_whose_every_page_is_complete_is_released(
    client: TestClient, session: Session, item: Item
) -> None:
    for page in (1, 2):
        decide_page(client, session, item.doc_id, page)
        client.post(f"/doc/{item.doc_id}/page/{page}/complete")

    assert client.post(f"/doc/{item.doc_id}/release", follow_redirects=False).status_code == 303
    assert client.get(f"/doc/{item.doc_id}/released").status_code == 200
    session.release_gate(item.doc_id)


def test_completing_a_page_is_a_row_in_the_log_and_not_a_flag(
    client: TestClient, session: Session, item: Item
) -> None:
    decide_page(client, session, item.doc_id, 1)
    client.post(f"/doc/{item.doc_id}/page/1/complete")

    rows = [r for r in session.log.rows(request_id=REQUEST) if r.action is Action.PAGE_COMPLETE]
    assert [(r.doc_id, r.page) for r in rows] == [(item.doc_id, 1)]
    ok, message = session.log.verify_chain()
    assert ok, message


# --- what a reviewer can and cannot do ------------------------------------------


def test_rejecting_a_span_records_no_final_category(
    client: TestClient, session: Session, item: Item
) -> None:
    """A released span has no category, because nothing was applied to it. Recording the
    proposed code as final would put a severance in the schedule that never happened."""
    span = spans_on(session, item.doc_id, 1)[0]
    act(client, item.doc_id, 1, span, "reject")

    row = session.log.rows(request_id=REQUEST)[-1]
    assert row.action is Action.REJECT
    assert row.proposed_code == span.code
    assert row.final_code is None


def test_changing_the_category_keeps_what_was_proposed_beside_what_was_chosen(
    client: TestClient, session: Session, item: Item
) -> None:
    """The pair is the whole value of the log for anyone measuring the tool later: it is
    the only record of where the tool and the person disagreed."""
    span = spans_on(session, item.doc_id, 1)[0]
    other = next(c.code for c in session.taxonomy.categories if c.code != span.code)

    act(client, item.doc_id, 1, span, "change_category", code=other)

    row = session.log.rows(request_id=REQUEST)[-1]
    assert (row.proposed_code, row.final_code) == (span.code, other)


def test_a_reviewer_can_add_a_severance_the_tool_never_proposed(
    client: TestClient, session: Session, item: Item
) -> None:
    """Detector recall is 98.6 percent, so a reviewer who can only answer the tool's list
    inherits its misses with no way to fix them."""
    status = client.post(
        f"/doc/{item.doc_id}/page/1/span",
        data={"start": "0", "end": "3", "action": "add", "code": "R1"},
    ).status_code

    assert status == 200
    row = session.log.rows(request_id=REQUEST)[-1]
    assert row.action is Action.ADD
    assert row.proposed_code is None
    assert row.final_code == "R1"


def test_approving_a_span_the_tool_did_not_propose_is_refused(
    client: TestClient, item: Item
) -> None:
    """Approval means "the tool was right about this". There is nothing to be right about
    at an offset the tool never looked at, and accepting it would put a row in the log
    claiming a proposal that does not exist."""
    response = client.post(
        f"/doc/{item.doc_id}/page/1/span",
        data={"start": "0", "end": "3", "action": "approve"},
    )
    assert response.status_code == 400
    assert "added, not approved" in response.json()["detail"]


def test_an_addition_without_a_category_is_refused(client: TestClient, item: Item) -> None:
    response = client.post(
        f"/doc/{item.doc_id}/page/1/span",
        data={"start": "0", "end": "3", "action": "add"},
    )
    assert response.status_code == 400


def test_a_category_that_is_not_in_the_taxonomy_is_refused(
    client: TestClient, session: Session, item: Item
) -> None:
    span = spans_on(session, item.doc_id, 1)[0]
    assert act(client, item.doc_id, 1, span, "change_category", code="Z9") == 400


def test_an_action_the_audit_log_has_no_member_for_is_refused(
    client: TestClient, session: Session, item: Item
) -> None:
    span = spans_on(session, item.doc_id, 1)[0]
    assert act(client, item.doc_id, 1, span, "delete") == 400


def test_a_reviewer_who_changes_their_mind_supersedes_rather_than_edits(
    client: TestClient, session: Session, item: Item
) -> None:
    span = spans_on(session, item.doc_id, 1)[0]
    act(client, item.doc_id, 1, span, "approve")
    act(client, item.doc_id, 1, span, "reject")

    actions = [
        r.action
        for r in session.log.rows(request_id=REQUEST)
        if r.span_start == span.detection.offsets.start
    ]
    assert actions == [Action.APPROVE, Action.REJECT], "the first decision must still be there"
    key = (span.detection.offsets.start, span.detection.offsets.end)
    assert session.acted_spans(item.doc_id, 1)[key] is Action.REJECT, "the screen shows the last"


# --- the control arm ------------------------------------------------------------


def test_the_unaided_arm_has_no_proposals_to_hide(item: Item, tmp_path: Path) -> None:
    """The control drops the proposals on the way into the session rather than declining to
    render them. A control arm that holds the answers in memory is one template edit away
    from not being a control, and the time study is worthless if the arms differ by a
    conditional in the HTML."""
    session = build_session(
        request_id=REQUEST,
        items=[item],
        log_path=tmp_path / "unaided.duckdb",
        mode=Mode.UNAIDED,
    )
    try:
        assert item.proposals, "the fixture must have proposals for this to prove anything"
        assert session.item(item.doc_id).proposals == ()
        body = TestClient(create_app(session)).get(f"/doc/{item.doc_id}/page/1").text
        assert "<mark" not in body
        for p in item.proposals:
            assert f'value="{p.detection.offsets.start}"' not in body
    finally:
        session.log.close()


def test_the_unaided_arm_still_records_to_the_same_log(item: Item, tmp_path: Path) -> None:
    """Both arms write the same rows, or the two arms cannot be compared."""
    session = build_session(
        request_id=REQUEST,
        items=[item],
        log_path=tmp_path / "unaided.duckdb",
        mode=Mode.UNAIDED,
    )
    try:
        client = TestClient(create_app(session))
        client.post(
            f"/doc/{item.doc_id}/page/1/span",
            data={"start": "4", "end": "15", "action": "add", "code": "R1"},
        )
        client.post(f"/doc/{item.doc_id}/page/1/complete")
        assert session.page_complete(item.doc_id, 1)
        assert len(session.log.rows(request_id=REQUEST)) == 2
    finally:
        session.log.close()


# --- the clock ------------------------------------------------------------------


def test_a_page_is_timed_from_when_it_was_served(
    client: TestClient, session: Session, item: Item
) -> None:
    """Not from the first action on it. A page that took four minutes of reading and then
    one click is four minutes, and measuring between actions would record it as nothing."""
    client.get(f"/doc/{item.doc_id}/page/1")
    decide_page(client, session, item.doc_id, 1)
    client.post(f"/doc/{item.doc_id}/page/1/complete")

    assert len(session.timings) == 1
    timing = session.timings[0]
    assert timing.seconds >= 0.0
    assert timing.spans_on_page == len(spans_on(session, item.doc_id, 1))
    assert timing.mode is Mode.PROPOSALS
    assert session.timings_path is not None
    assert session.timings_path.read_text(encoding="utf-8").count("\n") == 1


def test_a_page_completed_without_being_served_is_recorded_as_untimed(
    session: Session, item: Item
) -> None:
    """After a restart there is no served-at stamp. The timing is missing rather than
    estimated, because the point of the measurement is that it is a measurement."""
    assert session.complete_page(item.doc_id, 1) is None
    assert session.timings == []
    assert session.page_complete(item.doc_id, 1), "the completion is recorded either way"


# --- rendering ------------------------------------------------------------------


def test_the_page_is_cut_into_fragments_that_reassemble_into_the_page(
    session: Session, item: Item
) -> None:
    """The reviewer must be looking at the text the redaction will be applied to. If the
    fragments did not rejoin into the page exactly, the offsets on screen and the offsets
    in the export would be different coordinate systems."""
    page = item.document.page(1)
    pieces = fragments(page, item.on_page(1), {})
    assert "".join(f.text for f in pieces) == page.text
    assert any(f.is_span for f in pieces)


def test_a_span_that_has_been_decided_says_so_in_its_own_markup(
    session: Session, item: Item
) -> None:
    page = item.document.page(1)
    span = item.on_page(1)[0]
    key = (span.detection.offsets.start, span.detection.offsets.end)
    pieces = fragments(page, item.on_page(1), {key: Action.REJECT})
    decided = [f for f in pieces if f.is_span and f.state == "reject"]
    assert len(decided) == 1
    assert decided[0].text == span.detection.text


def test_the_screen_is_rendered_from_the_log_and_not_from_the_request(
    client: TestClient, session: Session, item: Item
) -> None:
    """The response to an action is re-rendered from the audit log, so what a reviewer sees
    is what was recorded. A screen built from the browser's idea of what it just posted can
    disagree with the log, and the log is the one that goes to the requester."""
    span = spans_on(session, item.doc_id, 1)[0]
    session.record(
        doc_id=item.doc_id,
        page=1,
        action=Action.REJECT,
        span_start=span.detection.offsets.start,
        span_end=span.detection.offsets.end,
    )

    body = client.get(f"/doc/{item.doc_id}/page/1").text

    assert 'class="decided d-release"' in body


def test_the_log_page_reports_the_chain(client: TestClient, session: Session, item: Item) -> None:
    decide_page(client, session, item.doc_id, 1)
    body = client.get("/log").text
    assert "Chain intact" in body


def test_an_unknown_document_or_page_is_a_404(client: TestClient, item: Item) -> None:
    assert client.get("/doc/nothing/page/1").status_code == 404
    assert client.get(f"/doc/{item.doc_id}/page/99").status_code == 404


def test_the_index_lists_what_is_left_to_review(
    client: TestClient, session: Session, item: Item
) -> None:
    body = client.get("/").text
    assert item.doc_id in body
    assert "2 pages" in body
    decide_page(client, session, item.doc_id, 1)
    client.post(f"/doc/{item.doc_id}/page/1/complete")
    assert "1 page" in client.get("/").text


def test_the_script_posts_to_the_form_url_and_not_to_its_action_input() -> None:
    """Every decision form carries an input named "action", and on such a form the DOM's
    `form.action` is that input, not the URL. The script once posted to it, so every click
    was a 405 in a browser while every test here, which posts without one, passed."""
    from sever.review.app.main import TEMPLATES

    script = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "form.getAttribute('action')" in script
    assert "fetch(form.action" not in script


def test_a_proposal_is_described_in_words_not_only_a_code(
    client: TestClient, session: Session, item: Item
) -> None:
    body = client.get(f"/doc/{item.doc_id}/page/1").text
    span = spans_on(session, item.doc_id, 1)[0]
    from markupsafe import escape

    assert str(escape(session.taxonomy[span.code].name)) in body
    assert "The tool proposes:" in body


def test_release_everything_undecided_records_a_release_per_span_and_spares_decided_ones(
    client: TestClient, session: Session, item: Item
) -> None:
    from sever.review.app.main import BULK_RELEASE_REASON

    spans = spans_on(session, item.doc_id, 1)
    act(client, item.doc_id, 1, spans[0], "approve")
    r = client.post(f"/doc/{item.doc_id}/page/1/release-rest")
    assert r.status_code == 200
    assert session.outstanding(item.doc_id, 1) == ()
    acted = session.acted_spans(item.doc_id, 1)
    first = (spans[0].detection.offsets.start, spans[0].detection.offsets.end)
    assert acted[first] is Action.APPROVE
    bulk = [x for x in session.log.rows(request_id=REQUEST) if x.reason == BULK_RELEASE_REASON]
    assert len(bulk) == len(spans) - 1
    assert all(x.action is Action.REJECT for x in bulk)
    # It releases; it does not complete the page. That is still its own action.
    assert not session.page_complete(item.doc_id, 1)


def test_every_highlight_says_what_is_proposed_without_being_opened(
    client: TestClient, session: Session, item: Item
) -> None:
    """Asked for by the first reviewer: the proposal as a letter and a colour on the
    highlight itself. The letter is a data attribute drawn by CSS, never record text, so
    selecting text to add a severance measures the same offsets as before."""
    import re

    body = client.get(f"/doc/{item.doc_id}/page/1").text
    marks = re.findall(r'<mark class="pending p-(\w+)"[^>]*data-badge="(\w)"', body)
    spans = spans_on(session, item.doc_id, 1)
    assert len(marks) == len(spans)
    letters = {"withhold": "W", "release": "R", "escalate": "E"}
    assert all(letters[kind] == letter for kind, letter in marks)
    record = body[body.index('id="record">') : body.index("</div>", body.index('id="record">'))]
    text = re.sub(r"<[^>]+>", "", record.removeprefix('id="record">'))
    from markupsafe import Markup

    assert Markup(text).unescape() == item.document.page(1).text
