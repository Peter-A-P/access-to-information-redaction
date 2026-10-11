"""The reviewer time study, end to end, with a scripted reviewer.

The study is the one measurement nobody can rerun cheaply: it costs a colleague an hour. So
what is tested here is everything that would make that hour worthless if it were wrong:
that nobody sees a record twice, that the arms and their order really are balanced, that
the practice page is left out, that the unaided arm really has no proposals, that a
reviewer's own severances are visible and undoable, that no name is written anywhere, and
that the scoring counts a leak as a leak.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sever.corpus.generate import CorpusItem, build
from sever.decide.pipeline import Proposal
from sever.eval import reviewer as rv
from sever.review import study as st
from sever.review.app import create_app
from sever.review.audit import Action, AuditLog
from sever.review.decisions import Origin, final_spans
from sever.review.session import Mode
from sever.taxonomy.loader import default_taxonomy

TAXONOMY = default_taxonomy()


@pytest.fixture(scope="module")
def pool() -> st.Pool:
    return st.study_pool()


@pytest.fixture(scope="module")
def corpus() -> dict[str, CorpusItem]:
    return {i.doc_id: i for i in build(documents=st.CORPUS_DOCUMENTS)}


# --- the design ------------------------------------------------------------------------


def test_nobody_reviews_the_same_record_twice(pool: st.Pool) -> None:
    for reviewer in range(1, 9):
        ids = [t.doc_id for t in st.plan_for(reviewer, pool)]
        assert len(ids) == len(set(ids)) == st.STUDY_RECORDS + st.PRACTICE_RECORDS


def test_two_consecutive_reviewers_cover_every_record_in_both_arms(pool: st.Pool) -> None:
    arms: dict[str, set[Mode]] = {}
    for reviewer in (1, 2):
        for t in st.plan_for(reviewer, pool):
            if not t.practice:
                arms.setdefault(t.doc_id, set()).add(t.arm)
    assert len(arms) == st.STUDY_RECORDS
    assert all(a == {Mode.PROPOSALS, Mode.UNAIDED} for a in arms.values())


def test_every_reviewer_starts_unaided_and_then_has_proposals(pool: st.Pool) -> None:
    """The baseline is a reviewer's ordinary work, so it comes first for everyone."""
    for r in (1, 2, 3, 4):
        tasks = st.plan_for(r, pool)
        assert [t.arm for t in tasks if t.block == 1] == [Mode.UNAIDED] * len(tasks[: len(tasks) // 2])
        assert all(t.arm is Mode.PROPOSALS for t in tasks if t.block == 2)


def test_each_arm_opens_with_one_practice_page_and_has_ten_counted(pool: st.Pool) -> None:
    tasks = st.plan_for(1, pool)
    for block in (1, 2):
        mine = [t for t in tasks if t.block == block]
        assert mine[0].practice and not any(t.practice for t in mine[1:])
        assert len(mine) == 1 + st.STUDY_RECORDS // 2
        assert len({t.arm for t in mine}) == 1
    assert not set(pool.practice) & set(pool.half_a + pool.half_b)


def test_the_halves_are_balanced_by_template(pool: st.Pool, corpus: dict[str, CorpusItem]) -> None:
    def templates(ids: tuple[str, ...]) -> Counter[str]:
        return Counter(corpus[d].template for d in ids)

    a, b = templates(pool.half_a), templates(pool.half_b)
    assert len(pool.half_a) == len(pool.half_b)
    for t in set(a) | set(b):
        assert abs(a[t] - b[t]) <= 1


def test_the_pool_is_the_same_every_time(pool: st.Pool) -> None:
    assert st.study_pool() == pool


def test_the_study_draws_on_the_test_split_and_not_validation() -> None:
    """The threshold was set on validation; the study should not watch the tool on pages
    it was tuned on."""
    corpus = build(documents=st.CORPUS_DOCUMENTS)
    assert all(corpus.split[d] == "test" for d in st.study_pool().all)


# --- a scripted reviewer ----------------------------------------------------------------


def _must_redact(corpus: dict[str, CorpusItem], doc_id: str) -> list[tuple[int, int]]:
    labels = corpus[doc_id].rendered.labels
    return [
        (lab.offsets.start, lab.offsets.end)
        for lab in labels
        if TAXONOMY.decision(lab.code).withholds
    ]


def _review_everything(
    client: TestClient, run: st.StudyRun, corpus: dict[str, CorpusItem]
) -> list[str]:
    """Go through the whole queue the way a careful reviewer would: agree with the tool
    where it is right, and in the unaided arm sever exactly the labelled third-party
    spans, adding whatever the tool did not propose. Returns the screens seen, in order."""
    seen: list[str] = []
    while True:
        r = client.get("/next", follow_redirects=False)
        if r.status_code == 200:
            if "Halfway" in r.text:
                seen.append("break")
                m = re.search(r'action="(/doc/[^"]+)"', r.text)
                assert m is not None
                url = m.group(1)
            else:
                assert "That is everything" in r.text
                seen.append("done")
                return seen
        else:
            url = r.headers["location"]
        doc = url.split("/")[2]
        seen.append(doc)
        assert client.get(url).status_code == 200
        item = run.session.item(doc)
        truth = set(_must_redact(corpus, doc))
        for p in item.on_page(1):
            key = (p.detection.offsets.start, p.detection.offsets.end)
            action = "approve" if key in truth else "reject"
            post(client, doc, key, action)
        # Whatever the tool missed, or proposed with different edges, the reviewer
        # selects and severs, in either arm.
        for key in truth:
            post(client, doc, key, "add", code="R1")
        r = client.post(f"/doc/{doc}/page/1/complete")
        assert "Next record" in r.text


def post(
    client: TestClient, doc: str, key: tuple[int, int], action: str, code: str = ""
) -> int:
    data = {"start": str(key[0]), "end": str(key[1]), "action": action}
    if code:
        data["code"] = code
    return int(client.post(f"/doc/{doc}/page/1/span", data=data).status_code)


@pytest.fixture(scope="module")
def studied(
    tmp_path_factory: pytest.TempPathFactory, corpus: dict[str, CorpusItem]
) -> Iterator[tuple[Path, dict[int, list[str]]]]:
    root = tmp_path_factory.mktemp("study")
    screens: dict[int, list[str]] = {}
    for reviewer in (1, 2):
        run = st.open_run(reviewer, root=root)
        client = TestClient(create_app(run.session, study=run))
        assert "Thank you for taking part" in client.get("/").text
        screens[reviewer] = _review_everything(client, run, corpus)
        run.session.log.close()
    yield root, screens


def test_the_queue_pauses_once_where_the_arm_changes_and_then_ends(
    studied: tuple[Path, dict[int, list[str]]],
) -> None:
    _, screens = studied
    for seen in screens.values():
        assert seen.count("break") == 1
        assert seen.index("break") == 1 + st.STUDY_RECORDS // 2
        assert seen[-1] == "done"


def test_timings_carry_a_reviewer_number_and_never_a_name(
    studied: tuple[Path, dict[int, list[str]]], corpus: dict[str, CorpusItem]
) -> None:
    root, _ = studied
    rows = [
        json.loads(line)
        for line in (st.reviewer_dir(1, root) / "timings.jsonl").read_text().splitlines()
    ]
    assert len(rows) == st.STUDY_RECORDS + st.PRACTICE_RECORDS
    assert {r["reviewer"] for r in rows} == {"reviewer-1"}
    assert sum(1 for r in rows if r["practice"]) == st.PRACTICE_RECORDS
    with AuditLog(st.reviewer_dir(1, root) / "audit.duckdb") as log:
        assert {r.actor for r in log.rows()} == {"reviewer-1"}


def test_a_finished_reviewer_is_not_resumed(
    studied: tuple[Path, dict[int, list[str]]],
) -> None:
    root, _ = studied
    assert st.pick_reviewer(root) == 3
    assert st.pick_reviewer(root, new=True) == 3


def test_a_careful_reviewer_scores_no_leaks_and_the_practice_page_is_left_out(
    studied: tuple[Path, dict[int, list[str]]], tmp_path: Path
) -> None:
    root, _ = studied
    results = st.collect(root)
    assert len(results) == 2 * (st.STUDY_RECORDS + st.PRACTICE_RECORDS)
    assert all(r.leaked == 0 for r in results)
    data = st.write_results(results, tmp_path / "study.jsonl")
    text = data.read_text()
    assert "reviewer-1" in text and "Delphine" not in text
    out = rv.write_study(rv.read_study(data), tmp_path / "reviewer.md").read_text()
    assert "Do not hand-edit" in out
    assert "On the 20 records reviewed in both arms" in out
    assert "the tool's proposals, nobody reviewing" in out


# --- the screens ------------------------------------------------------------------------


@pytest.fixture()
def fresh(tmp_path: Path) -> Iterator[tuple[st.StudyRun, TestClient]]:
    run = st.open_run(3, root=tmp_path)
    yield run, TestClient(create_app(run.session, study=run))
    run.session.log.close()


def test_the_unaided_arm_shows_the_requester_and_no_proposals(
    fresh: tuple[st.StudyRun, TestClient],
) -> None:
    run, client = fresh
    task = run.tasks[0]
    assert task.arm is Mode.UNAIDED
    item = run.session.item(task.doc_id)
    assert item.proposals == ()
    body = client.get(f"/doc/{task.doc_id}/page/1").text
    assert item.requester is not None and item.requester in body
    assert "proposes:" not in body


def test_a_reviewer_sees_and_can_undo_their_own_severance(
    fresh: tuple[st.StudyRun, TestClient],
) -> None:
    run, client = fresh
    doc = run.tasks[0].doc_id
    assert post(client, doc, (0, 6), "add", code="R1") == 200
    body = client.get(f"/doc/{doc}/page/1").text
    assert "Withheld by you" in body and 'mark class="decided d-withhold"' in body
    assert post(client, doc, (0, 6), "reject") == 200
    assert run.session.added_spans(doc, 1) == ()
    assert "Withheld by you" not in client.get(f"/doc/{doc}/page/1").text


def test_releasing_text_nobody_severed_is_still_refused(
    fresh: tuple[st.StudyRun, TestClient],
) -> None:
    run, client = fresh
    assert post(client, run.tasks[0].doc_id, (10, 20), "reject") == 400


def test_a_keep_code_is_not_offered_for_a_severance(
    fresh: tuple[st.StudyRun, TestClient],
) -> None:
    run, client = fresh
    body = client.get(f"/doc/{run.tasks[0].doc_id}/page/1").text
    addbar = body[body.index('id="addbar"') : body.index("</form>", body.index('id="addbar"'))]
    assert 'value="R1"' in addbar
    assert 'value="K2"' not in addbar


# --- what a reviewer decided ------------------------------------------------------------


def _proposal(run: st.StudyRun) -> tuple[str, Proposal]:
    for t in run.tasks:
        item = run.session.item(t.doc_id)
        if item.proposals:
            return t.doc_id, item.proposals[0]
    raise AssertionError("no aided record")


@pytest.mark.parametrize(
    ("action", "code", "withholds"),
    [
        (Action.APPROVE, None, True),
        (Action.REJECT, None, False),
        (Action.ESCALATE, None, True),
        (Action.CHANGE_CATEGORY, "R2", True),
        (Action.CHANGE_CATEGORY, "K2", False),
    ],
)
def test_the_latest_action_decides_whether_a_span_leaves_the_record(
    fresh: tuple[st.StudyRun, TestClient], action: Action, code: str | None, withholds: bool
) -> None:
    """CHANGE_CATEGORY is the one that needs the taxonomy: moving a span to K2 releases it,
    and an export that read the action alone would withhold it, or the reverse."""
    run, _ = fresh
    doc, p = _proposal(run)
    s = run.session
    s.record(
        doc_id=doc,
        page=p.page,
        action=action,
        span_start=p.detection.offsets.start,
        span_end=p.detection.offsets.end,
        proposed_code=p.code,
        final_code=code if code is not None else p.code,
    )
    final = {f.key: f for f in s.final_spans(doc)}
    assert final[p.key].withholds is withholds
    assert final[p.key].origin is Origin.PROPOSAL


def test_an_untouched_proposal_keeps_the_tool_decision(
    fresh: tuple[st.StudyRun, TestClient],
) -> None:
    run, _ = fresh
    doc, _ = _proposal(run)
    item = run.session.item(doc)
    final = final_spans((), item.proposals, doc_id=doc, taxonomy=TAXONOMY)
    assert [f.withholds for f in final] == [p.withholds for p in sorted(item.proposals, key=lambda p: p.key)]


def test_a_busy_port_is_skipped_rather_than_failing_after_printing_its_address() -> None:
    import socket

    from sever.cli import _free_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        assert _free_port(taken) != taken


def test_withholding_unlabelled_text_is_counted_in_its_own_column_and_nowhere_else() -> None:
    """The word "sibling" beside a severed name is no label's business, so withholding it
    is neither a leak nor an over-redaction. It still costs time and text, so it is
    counted, and it must not leak into the two rates."""
    from sever.corpus.labels import LabelledSpan
    from sever.ingest.document import Offsets

    text = "Client's sibling, Siobhan Whelan, telephoned."
    start = text.index("Siobhan Whelan")
    label = LabelledSpan(
        page=1, offsets=Offsets(start, start + 14), text="Siobhan Whelan", code="R1"
    )
    sibling = text.index("sibling")
    name_only = [(start, start + 14)]
    with_role = [*name_only, (sibling, sibling + 7)]

    assert st._unlabelled(text, [label], name_only) == (0, 0)
    assert st._unlabelled(text, [label], with_role) == (7, 1)
    assert st._count(text, [label], with_role, TAXONOMY) == st._count(
        text, [label], name_only, TAXONOMY
    )


def test_the_trial_is_two_records_outside_the_study_unaided_first_and_never_scored(
    tmp_path: Path, pool: st.Pool
) -> None:
    trial = st.open_trial(root=tmp_path / "trial")
    try:
        assert [t.arm for t in trial.tasks] == [Mode.UNAIDED, Mode.PROPOSALS]
        assert all(t.practice for t in trial.tasks)
        assert not {t.doc_id for t in trial.tasks} & set(pool.all)
        client = TestClient(create_app(trial.session, study=trial))
        assert "This is the trial" in client.get("/").text
        body = client.get(f"/doc/{trial.tasks[1].doc_id}/page/1").text
        assert "<kbd>W</kbd> withhold" in body
    finally:
        trial.session.log.close()
    # The trial's folder is not one the study's scoring reads.
    assert st.enrolled(tmp_path / "trial") == ()


def test_a_family_relationship_is_labelled_and_proposed_for_withholding(
    corpus: dict[str, CorpusItem],
) -> None:
    """The first reviewer's ruling: "the client's sibling" identifies the sibling to a
    requester who knows their family, so it is a must-redact label and the tool withholds it."""
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.eval.report import config_for

    item = next(i for i in corpus.values() if i.template == "case_note.tmpl")
    kin = [lab for lab in item.rendered.labels if lab.field_name == "sibling.relationship"]
    assert kin and all(lab.code == "R1" and lab.text == "sibling" for lab in kin)
    proposals = DecisionEngine(config=config_for(item), detector=SeverDetector()).propose(
        item.rendered.document
    )
    kin_keys = {lab.key for lab in kin}
    assert all(p.code == "R1" for p in proposals if p.key in kin_keys)
    assert kin_keys <= {p.key for p in proposals}


def test_the_frozen_proposals_cover_every_study_record_and_round_trip() -> None:
    """The screen and the scoring both read data/study/proposals.jsonl, so a detector fix
    cannot rescore a reviewer against proposals they never saw."""
    from sever.review.study import _proposal_from, _proposal_json, shown_proposals

    shown = shown_proposals()
    assert set(shown) == set(st.study_pool().all)
    first = next(iter(shown.values()))[0]
    assert _proposal_from(_proposal_json("x", first)) == first


def test_reviewer_one_was_shown_the_mcp_defect() -> None:
    """The frozen file is the tool as it was, defect included: nine digits of the MCP
    number in incident_report-154 proposed as a SIN."""
    from sever.detect.types import EntityType
    from sever.review.study import shown_proposals

    texts = {
        (p.detection.text, p.detection.entity_type)
        for p in shown_proposals()["incident_report-154"]
    }
    assert ("404 474 556", EntityType.SIN) in texts
