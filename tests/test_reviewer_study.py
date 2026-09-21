"""The reviewer time study, and the ways it is allowed to say "not yet".

This is the one measurement in the definition of done that no program can produce, so the
risk here is not a wrong calculation. It is a table that looks like a result before it is
one: two sessions on one document, a ratio computed from them, and a number in the README
that a reader will reasonably take as measured.

So most of this file is about refusal. An arm from a single document reports its point
estimate and says the interval is undefined. An arm below the floor is reported as collected
rather than compared. A study with one arm says there is nothing to compare. And a study
that does not know how many completed pages went untimed says that too, rather than letting
a reader assume the answer is none.
"""

from __future__ import annotations

import json
from pathlib import Path

from sever.eval.reviewer import (
    MINIMUM_DOCUMENTS,
    Study,
    Timed,
    completed_from_audit,
    estimate,
    read,
    run,
    write,
)
from sever.review.audit import Action, AuditLog


def timings_file(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def row(doc: str, page: int, mode: str, seconds: float) -> dict[str, object]:
    return {
        "request_id": "A-1",
        "doc_id": doc,
        "page": page,
        "mode": mode,
        "served_at": "2026-09-20T10:00:00",
        "completed_at": "2026-09-20T10:01:00",
        "seconds": seconds,
        "spans_on_page": 9,
        "actions": 9,
    }


def timed(doc: str, mode: str, seconds: float, page: int = 1) -> Timed:
    return Timed(doc_id=doc, page=page, mode=mode, seconds=seconds, spans_on_page=9, actions=9)


# --- refusing to report ---------------------------------------------------------


def test_nothing_collected_says_so_and_says_what_would_collect_it(tmp_path: Path) -> None:
    study = run([tmp_path / "absent.jsonl"])
    body = study.to_markdown()
    assert "No review sessions have been timed yet" in body
    assert "sever review --mode unaided" in body
    assert not study.has_both_arms


def test_one_arm_is_not_a_comparison(tmp_path: Path) -> None:
    path = timings_file(
        tmp_path / "t.jsonl", [row(f"d{i}", 1, "proposals", 60.0) for i in range(4)]
    )
    study = run([path])
    assert not study.has_both_arms
    assert not study.comparable
    assert "Only one arm" in study.to_markdown()


def test_both_arms_but_too_few_documents_is_collected_and_not_compared(tmp_path: Path) -> None:
    """The dangerous case: there is a ratio, it is computable, and it means nothing."""
    assert MINIMUM_DOCUMENTS > 2
    path = timings_file(
        tmp_path / "t.jsonl",
        [
            row("d1", 1, "proposals", 60.0),
            row("d2", 1, "proposals", 60.0),
            row("d1", 1, "unaided", 180.0),
            row("d2", 1, "unaided", 180.0),
        ],
    )
    study = run([path])
    assert study.has_both_arms
    assert not study.comparable
    body = study.to_markdown()
    assert "neither has reached" in body
    assert "times** the speed" not in body


def test_a_single_document_reports_its_point_with_the_interval_marked_undefined() -> None:
    e = estimate([timed("d1", "proposals", 60.0, page=p) for p in (1, 2, 3)])
    assert e.point == 60.0
    assert e.undefined
    assert "interval undefined" in str(e)


def test_an_arm_with_no_pages_says_so_rather_than_printing_a_zero() -> None:
    e = estimate([])
    assert e.pages == 0
    assert str(e) == "no pages timed"


# --- reporting when there is something to report --------------------------------


def test_a_study_with_both_arms_over_enough_documents_reports_the_ratio(
    tmp_path: Path,
) -> None:
    docs = [f"d{i}" for i in range(MINIMUM_DOCUMENTS + 1)]
    path = timings_file(
        tmp_path / "t.jsonl",
        [*(row(d, 1, "proposals", 60.0) for d in docs), *(row(d, 1, "unaided", 180.0) for d in docs)],
    )
    study = run([path])
    assert study.comparable
    assert study.speedup == 3.0
    body = study.to_markdown()
    assert "3.0 times" in body
    assert "resampled over" in body


def test_the_interval_rests_on_documents_and_not_on_pages() -> None:
    """Twenty pages of one record is one fact, not twenty. The estimator has to agree."""
    many_pages_one_doc = [timed("d1", "proposals", 60.0, page=p) for p in range(1, 21)]
    assert estimate(many_pages_one_doc).documents == 1
    assert estimate(many_pages_one_doc).undefined

    spread = [timed(f"d{i}", "proposals", 60.0) for i in range(20)]
    assert estimate(spread).documents == 20
    assert not estimate(spread).undefined


def test_minutes_and_pages_per_hour_are_the_same_number_read_two_ways() -> None:
    e = estimate([timed(f"d{i}", "proposals", 120.0) for i in range(4)])
    assert e.minutes == 2.0
    assert e.pages_per_hour == 30.0


def test_reading_several_files_pools_them(tmp_path: Path) -> None:
    """The two arms are separate sessions, so they are separate runs and often separate
    files. Pooling them is how the comparison happens at all."""
    a = timings_file(tmp_path / "a.jsonl", [row("d1", 1, "proposals", 60.0)])
    b = timings_file(tmp_path / "b.jsonl", [row("d1", 1, "unaided", 180.0)])
    assert len(read([a, b])) == 2
    assert run([a, b]).has_both_arms


# --- what the study could not see -----------------------------------------------


def test_completed_pages_with_no_timing_are_counted_and_named(tmp_path: Path) -> None:
    """The difference between the log and the clock is what the study missed. A study that
    cannot say how much it missed is not reporting, it is selecting."""
    log_path = tmp_path / "audit.duckdb"
    with AuditLog(log_path) as log:
        for page in (1, 2, 3):
            log.append(request_id="A-1", doc_id="d1", page=page, action=Action.PAGE_COMPLETE)
    timings = timings_file(tmp_path / "t.jsonl", [row("d1", 1, "proposals", 60.0)])

    study = run([timings], audit=log_path, request_id="A-1")

    assert study.completed_pages == 3
    assert study.untimed == 2
    assert "2 completed page(s) carry no timing" in study.to_markdown()


def test_without_an_audit_log_the_untimed_count_is_unknown_rather_than_zero(
    tmp_path: Path,
) -> None:
    timings = timings_file(tmp_path / "t.jsonl", [row("d1", 1, "proposals", 60.0)])
    study = run([timings])
    assert study.untimed is None
    assert "is not known here" in study.to_markdown()


def test_only_completion_rows_are_counted_as_completed_pages(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.duckdb"
    with AuditLog(log_path) as log:
        log.append(request_id="A-1", doc_id="d1", page=1, action=Action.APPROVE)
        log.append(request_id="A-1", doc_id="d1", page=1, action=Action.REJECT)
        log.append(request_id="A-1", doc_id="d1", page=1, action=Action.PAGE_COMPLETE)
    assert completed_from_audit(log_path, "A-1") == 1


def test_a_study_never_reports_more_timings_than_completions(tmp_path: Path) -> None:
    """A negative shortfall would be a bug somewhere else, and printing it as a negative
    number would make it look like a finding."""
    study = Study(arms={}, rows=(timed("d1", "proposals", 60.0),), completed_pages=0)
    assert study.untimed == 0


# --- the written file -----------------------------------------------------------


def test_the_generated_file_says_it_is_generated(tmp_path: Path) -> None:
    out = write(run([tmp_path / "absent.jsonl"]), tmp_path / "reviewer.md")
    assert "Do not hand-edit" in out.read_text(encoding="utf-8")
