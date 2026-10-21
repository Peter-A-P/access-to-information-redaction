"""The sample comparison's scoring: what counts as right, accepted, a leak, a kept span withheld.

No model and no cache. The definitions are the claim the published table makes, so each one
is pinned on answers built by hand.
"""

from __future__ import annotations

from pathlib import Path

from sever.eval.decision_sample import (
    DEFAULT_SAMPLE,
    MODELS,
    NOT_PERSONAL,
    SampleAnswer,
    load_sample,
    score_answers,
)

MODEL = MODELS[0]


def _row(answers: list[SampleAnswer], threshold: float) -> tuple[int, int, int, int]:
    s = score_answers(MODEL, answers)
    r = next(r for r in s.rows if r.threshold == threshold)
    return r.accepted, r.right, r.leaks, r.keep_withheld


def test_a_must_withhold_span_answered_keep_is_a_leak_only_when_accepted() -> None:
    answers = [SampleAnswer("d1", "R1", "K2", 0.55)]
    assert _row(answers, 0.5) == (1, 0, 1, 0)
    assert _row(answers, 0.6) == (0, 0, 0, 0)


def test_an_escalate_code_is_never_accepted_whatever_its_probability() -> None:
    # E2 (a mixed span) escalates, as E1 does: the model declining is not an answer.
    answers = [SampleAnswer("d1", "K2", "E2", 0.99), SampleAnswer("d2", "R1", "E1", 0.99)]
    accepted, _right, leaks, kept_withheld = _row(answers, 0.0)
    assert (accepted, leaks) == (0, 0)
    assert kept_withheld == 1


def test_not_personal_is_right_under_any_keep_code_and_wrong_under_withhold() -> None:
    answers = [
        SampleAnswer("d1", NOT_PERSONAL, "K1", 0.9),
        SampleAnswer("d2", NOT_PERSONAL, "K6", 0.9),
        SampleAnswer("d3", NOT_PERSONAL, "R1", 0.9),
    ]
    accepted, right, leaks, kept_withheld = _row(answers, 0.0)
    assert (accepted, right, leaks, kept_withheld) == (3, 2, 0, 1)


def test_a_kept_span_below_the_threshold_is_withheld_even_when_the_answer_was_right() -> None:
    answers = [SampleAnswer("d1", "K2", "K2", 0.7)]
    assert _row(answers, 0.6)[3] == 0
    assert _row(answers, 0.8)[3] == 1


def test_calibration_bins_count_by_stated_probability() -> None:
    answers = [SampleAnswer("d1", "R1", "R1", 0.95), SampleAnswer("d2", "R1", "K2", 0.92)]
    top = score_answers(MODEL, answers).bins[-1]
    assert (top[2], top[3]) == (2, 0.5)


def test_the_committed_sample_is_the_one_the_tables_describe() -> None:
    sample = load_sample(Path(DEFAULT_SAMPLE))
    assert len(sample) == 150
    assert set(sample.values()) <= {"K1", "K2", "K6", "R1", NOT_PERSONAL}
