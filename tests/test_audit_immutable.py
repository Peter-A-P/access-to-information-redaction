"""The audit log is append-only, and the test tries to break it rather than assuming."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from sever.review.audit import Action, AuditLog


@pytest.fixture
def log(tmp_path: Path) -> Iterator[AuditLog]:
    with AuditLog(tmp_path / "audit.duckdb") as log:
        log.append(
            request_id="A-2027-001",
            doc_id="d1",
            page=1,
            action=Action.APPROVE,
            actor="reviewer.one",
            span_start=10,
            span_end=24,
            span_text="Odette Tulk",
            proposed_code="R1",
            final_code="R1",
            reason="Third party, no capacity signal.",
        )
        log.append(
            request_id="A-2027-001",
            doc_id="d1",
            page=1,
            action=Action.REJECT,
            actor="reviewer.one",
            span_start=40,
            span_end=54,
            span_text="Marie Doucette",
            proposed_code="R1",
            final_code="K2",
            reason="Signed the letter; official capacity.",
        )
        yield log


def test_rows_accumulate(log: AuditLog) -> None:
    assert len(log) == 2
    assert [r.seq for r in log] == [1, 2]


def test_the_module_exposes_no_way_to_change_a_row() -> None:
    """The first line of defence: there is no supported path."""
    forbidden = {"update", "delete", "edit", "remove", "amend", "set"}
    methods = {name for name in dir(AuditLog) if not name.startswith("_")}
    assert not (methods & forbidden), f"AuditLog exposes {sorted(methods & forbidden)}"


def test_a_direct_update_does_not_change_history(log: AuditLog) -> None:
    """The second: the database refuses, or the hash chain catches it. Either is a pass;
    silently succeeding with an intact chain is not."""
    before = log.rows()[0]
    try:
        log.con.execute("UPDATE audit SET final_code = 'K1' WHERE seq = 1")
    except duckdb.Error:
        after = log.rows()[0]
        assert after.final_code == before.final_code
        return
    after = log.rows()[0]
    if after.final_code == before.final_code:
        return  # the rule swallowed it
    ok, message = log.verify_chain()
    assert not ok, (
        "a row was updated, the chain still verified, and nothing objected. The audit log "
        "is not append-only."
    )
    assert "does not hash" in message


def test_a_direct_delete_does_not_change_history(log: AuditLog) -> None:
    before = len(log)
    try:
        log.con.execute("DELETE FROM audit WHERE seq = 1")
    except duckdb.Error:
        assert len(log) == before
        return
    if len(log) == before:
        return
    ok, message = log.verify_chain()
    assert not ok, "a row was deleted and the chain still verified"
    assert "inserted, removed or reordered" in message


def test_the_chain_verifies_when_untouched(log: AuditLog) -> None:
    ok, message = log.verify_chain()
    assert ok, message


def test_a_tampered_row_breaks_the_chain(tmp_path: Path) -> None:
    """The guarantee that survives someone dropping the rules."""
    path = tmp_path / "audit.duckdb"
    with AuditLog(path) as log:
        for i in range(3):
            log.append(
                request_id="r",
                doc_id="d",
                page=1,
                action=Action.APPROVE,
                actor="a",
                span_start=i,
                span_end=i + 5,
                final_code="R1",
            )
        ok, _ = log.verify_chain()
        assert ok

    # Rewrite a row the way someone with the file would, bypassing the module entirely.
    con = duckdb.connect(str(path))
    try:
        con.execute("DELETE FROM audit WHERE seq = 2")
        con.execute(
            "INSERT INTO audit SELECT 2, at, actor, request_id, doc_id, page, action, "
            "span_start, span_end, span_text_sha256, proposed_code, 'K2', reason, "
            "prev_hash, row_hash FROM audit WHERE seq = 3"
        )
    except duckdb.Error:
        pytest.skip("this build refuses direct writes, which is a stronger guarantee")
    finally:
        con.close()

    with AuditLog(path) as log:
        ok, message = log.verify_chain()
        assert not ok, "a hand-edited row passed verification"
        assert message


def test_the_schedule_reflects_the_latest_action_per_span(log: AuditLog) -> None:
    """A reviewer who changes their mind adds a row; the earlier row stays but the
    schedule follows the later one."""
    log.append(
        request_id="A-2027-001",
        doc_id="d1",
        page=1,
        action=Action.REJECT,
        actor="reviewer.two",
        span_start=10,
        span_end=24,
        span_text="Odette Tulk",
        proposed_code="R1",
        final_code="K2",
        reason="On review, this person signed the inspection report.",
    )
    assert len(log) == 3, "the superseded row was removed instead of superseded"
    approvals = log.approvals("A-2027-001")
    assert [(r.span_start, r.final_code) for r in approvals] == []


def test_pages_need_an_explicit_completion_action(log: AuditLog) -> None:
    assert log.pages_reviewed("A-2027-001") == frozenset()
    log.append(
        request_id="A-2027-001",
        doc_id="d1",
        page=1,
        action=Action.PAGE_COMPLETE,
        actor="reviewer.one",
    )
    assert log.pages_reviewed("A-2027-001") == frozenset({("d1", 1)})


def test_span_text_is_hashed_not_stored(log: AuditLog) -> None:
    """The audit log records that a span was severed, not the personal information in it."""
    row = log.rows()[0]
    assert row.span_text_sha256 is not None
    assert len(row.span_text_sha256) == 64
    dumped = " ".join(str(v) for v in row.__dict__.values()) if hasattr(row, "__dict__") else ""
    assert "Odette" not in dumped


def test_timestamps_are_recorded(log: AuditLog) -> None:
    assert all(isinstance(r.at, dt.datetime) for r in log)
