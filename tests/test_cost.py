"""Cost per page, and the check that stops it being quietly wrong.

There is one way this measurement fails that nobody would notice: a paid run against the
corpus that is not in the list of runs being totalled. The number still prints, still looks
plausible, and is too low. It flatters the project, which is the direction of error that
does not get questioned.

`sever-full-210` alone is exactly that failure. It paid for 466 calls and the committed
cache holds 871 answers, because earlier runs had already paid for the rest. Totalling that
one run reports roughly half the true cost per page and nothing about the output says so.

So the count is the check: one line in the cache is one answer, one row in the ledger is
one paid call, and every cached answer was paid for exactly once. If the two disagree the
figure is not written. That property is what these tests hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sever.eval.cost import (
    CAD_PER_USD,
    PUBLISHED_RUNS,
    LedgerMismatch,
    RunCost,
    from_ledger,
    read,
    write,
)

PROJECT = "sever"


@dataclass
class FakeLedger:
    """A stand-in with `LedgerStore.rows`'s signature and its dict-of-columns rows."""

    _rows: list[dict[str, Any]]

    def rows(self, *, project: str | None = None) -> list[dict[str, Any]]:
        return [r for r in self._rows if project is None or r.get("project") == project]


def a_row(run_id: str, cost: float = 0.001) -> dict[str, Any]:
    return {
        "project": PROJECT,
        "run_id": run_id,
        "cost_usd": cost,
        "costed": True,
        "input_tokens": 700,
        "output_tokens": 60,
        "model_returned": "anthropic/claude-haiku-4-5",
    }


def ledger_of(**counts: int) -> FakeLedger:
    return FakeLedger([a_row(run) for run, n in counts.items() for _ in range(n)])


# --- the check that keeps the number honest -------------------------------------


def test_a_paid_run_left_out_of_the_list_is_refused_rather_than_under_reported() -> None:
    """The failure this whole module is arranged around.

    Two runs paid for the 20 committed answers. Total only one of them and the cost per
    page halves, with nothing in the output to say the figure is partial.
    """
    ledger = ledger_of(**{"sever-full-001": 8, "sever-full-210": 12})
    with pytest.raises(LedgerMismatch, match="12 paid calls"):
        from_ledger(
            ledger=ledger,
            project=PROJECT,
            run_ids=("sever-full-210",),
            pages=10,
            documents=10,
            cached_answers=20,
            asks=60,
        )


def test_a_run_that_served_something_not_in_the_cache_is_refused_too() -> None:
    """The other direction. An excess means the run list is totalling calls that did not
    produce a published answer, so the cost is attributed to pages that did not incur it."""
    ledger = ledger_of(**{"sever-full-210": 25})
    with pytest.raises(LedgerMismatch, match="25 paid calls"):
        from_ledger(
            ledger=ledger,
            project=PROJECT,
            run_ids=("sever-full-210",),
            pages=10,
            documents=10,
            cached_answers=20,
            asks=60,
        )


def test_a_run_the_ledger_has_never_heard_of_is_a_lookup_error() -> None:
    with pytest.raises(LookupError, match="sever-imaginary"):
        from_ledger(
            ledger=ledger_of(**{"sever-full-210": 20}),
            project=PROJECT,
            run_ids=("sever-full-210", "sever-imaginary"),
            pages=10,
            documents=10,
            cached_answers=20,
            asks=60,
        )


def test_another_project_s_spend_is_not_counted() -> None:
    """The ledger is shared across the portfolio. Filtering by project is not optional."""
    ledger = FakeLedger(
        [a_row("sever-full-210") for _ in range(20)]
        + [{**a_row("sever-full-210", 5.0), "project": "someone-else"}]
    )
    cost = from_ledger(
        ledger=ledger,
        project=PROJECT,
        run_ids=("sever-full-210",),
        pages=10,
        documents=10,
        cached_answers=20,
        asks=60,
    )
    assert cost.calls == 20
    assert cost.cost_usd == pytest.approx(0.02)


# --- the arithmetic -------------------------------------------------------------


def a_cost(**over: Any) -> RunCost:
    ledger = ledger_of(**{"sever-full-001": 8, "sever-full-210": 12})
    kwargs: dict[str, Any] = {
        "ledger": ledger,
        "project": PROJECT,
        "run_ids": ("sever-full-001", "sever-full-210"),
        "pipeline_runs": ("sever-full-001", "sever-full-210"),
        "pages": 10,
        "documents": 10,
        "cached_answers": 20,
        "asks": 60,
    }
    return from_ledger(**{**kwargs, **over})


def test_cost_per_page_is_the_paid_total_over_the_pages() -> None:
    cost = a_cost()
    assert cost.cost_usd == pytest.approx(0.02)
    assert cost.usd_per_page == pytest.approx(0.002)
    assert cost.cad_per_page == pytest.approx(0.002 * CAD_PER_USD)


def test_the_undeduplicated_figure_prices_every_ask_and_not_every_call() -> None:
    """The number for a reader whose documents are not generated from templates.

    Twenty paid calls served sixty asks, so pricing all sixty at the mean triples it. This
    is the figure the project would rather not publish, which is the reason to publish it.
    """
    cost = a_cost()
    assert cost.deduplication == pytest.approx(2 / 3)
    assert cost.undeduplicated_usd_per_page == pytest.approx(0.006)
    assert cost.undeduplicated_usd_per_page > cost.usd_per_page


def test_the_line_says_both_figures_and_which_is_which() -> None:
    line = a_cost().to_markdown()
    assert "US$0.00200 per page" in line
    assert "US$0.00600" in line
    assert "not generated from templates" in line


def test_spend_is_attributed_per_run_so_a_reader_can_check_the_total() -> None:
    cost = a_cost()
    assert cost.per_run == {"sever-full-001": 0.008, "sever-full-210": 0.012}
    assert sum(cost.per_run.values()) == pytest.approx(cost.cost_usd)


def test_a_zero_page_run_reports_zero_rather_than_dividing_by_zero() -> None:
    assert a_cost(pages=0).usd_per_page == 0.0
    assert a_cost(pages=0).undeduplicated_usd_per_page == 0.0


# --- the committed file ---------------------------------------------------------


def test_what_is_written_is_what_is_read_back(tmp_path: Path) -> None:
    original = a_cost()
    path = write(original, tmp_path / "cost.json")
    back = read(path)
    assert back == original


def test_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    """CI has no gateway and no ledger, so the report must generate without a cost line
    rather than fail or invent one."""
    assert read(tmp_path / "nothing.json") is None


def test_a_file_from_an_older_schema_says_so_instead_of_raising_a_type_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cost.json"
    path.write_text('{"run_ids": ["sever-full-210"], "pages": 210}', encoding="utf-8")
    with pytest.raises(LedgerMismatch, match="older version"):
        read(path)


def test_the_published_run_list_is_not_empty() -> None:
    """Held here because the default is what `sever cost` uses when nobody passes --runs,
    and an empty default would silently report nothing at all."""
    assert PUBLISHED_RUNS
    assert len(set(PUBLISHED_RUNS)) == len(PUBLISHED_RUNS)


# --- the cost line only belongs on the run it was measured for -------------------


def test_a_cost_recorded_for_another_corpus_size_is_dropped_rather_than_rescaled(
    tmp_path: Path,
) -> None:
    """`sever report --documents 60` is a smaller run than the published one. Splicing a
    figure measured over 210 pages into it would attach a real number to the wrong
    denominator, and rescaling would be worse: the answers behind the recorded cost are not
    the answers that run made.
    """
    from sever.corpus.generate import build
    from sever.eval.report import _cost_for

    recorded = a_cost(pages=210, documents=210)
    path = write(recorded, tmp_path / "cost.json")
    small = build(documents=4, seed=20270802)

    assert _cost_for(path, small, 0) is None
    assert _cost_for(None, small, 0) is None


def test_a_cost_recorded_for_this_corpus_size_is_used(tmp_path: Path) -> None:
    from sever.corpus.generate import build
    from sever.eval.report import _cost_for

    corpus = build(documents=4, seed=20270802)
    recorded = a_cost(pages=corpus.page_count, documents=len(corpus))
    path = write(recorded, tmp_path / "cost.json")

    assert _cost_for(path, corpus, 0) == recorded


# --- the baseline's spend is not the tool's cost ---------------------------------


def test_a_research_baseline_is_named_rather_than_divided_into_the_cost_per_page() -> None:
    """The model-only baseline asks about every span rather than the residual, so it cost
    three times what the pipeline's own rows did. Folding the two together would publish a
    cost per page more than double the tool's, for a configuration nobody would deploy.

    The integrity check still runs over both, because the answer cache does not record
    which run bought which line and a check over a subset would pass while a whole run was
    missing.
    """
    ledger = ledger_of(**{"sever-full-210": 10, "sever-modelonly-210": 30})

    cost = from_ledger(
        ledger=ledger,
        project=PROJECT,
        run_ids=("sever-full-210", "sever-modelonly-210"),
        pipeline_runs=("sever-full-210",),
        pages=10,
        documents=10,
        cached_answers=40,
        asks=25,
    )

    assert cost.calls == 40, "the integrity check covers every run that filled the cache"
    assert cost.pipeline_calls == 10
    assert cost.pipeline_cost_usd == pytest.approx(0.01)
    assert cost.baseline_cost_usd == pytest.approx(0.03)
    assert cost.usd_per_page == pytest.approx(0.001), "the headline is the pipeline's alone"
    assert "bought the model-only baseline" in cost.to_markdown()


def test_deduplication_is_measured_against_the_pipeline_s_own_asks() -> None:
    """The denominator has to be what the tool asked, not what every arm asked between
    them. A denominator that quietly includes a research arm reports the tool as far more
    cacheable than it is."""
    ledger = ledger_of(**{"sever-full-210": 10, "sever-modelonly-210": 30})
    cost = from_ledger(
        ledger=ledger,
        project=PROJECT,
        run_ids=("sever-full-210", "sever-modelonly-210"),
        pipeline_runs=("sever-full-210",),
        pages=10,
        documents=10,
        cached_answers=40,
        asks=25,
    )
    assert cost.deduplication == pytest.approx(1 - 10 / 25)


def test_a_run_list_with_no_baselines_reports_no_baseline_cost() -> None:
    cost = a_cost()
    assert cost.baseline_cost_usd == pytest.approx(0.0)
    assert "bought the model-only baseline" not in cost.to_markdown()


def test_the_stored_ask_count_is_not_what_the_published_line_uses() -> None:
    """The cycle is broken in the shape rather than in a documented ordering.

    An ordering rule was written after the first wrong figure and did not prevent the
    second, because no ordering helps when the file was written before the behaviour it
    describes changed: the residual shrank from 2,606 asks to 2,173 in the same step. The
    module says so now and the report supplies its own count.
    """
    from sever.eval import cost as cost_mod
    from sever.eval.report import run as report_run

    assert cost_mod.__doc__ is not None
    assert "no longer read from a file" in cost_mod.__doc__
    assert hasattr(cost_mod.RunCost, "with_asks")
    # Keyword-only, so the defaults live in __kwdefaults__.
    assert (report_run.__kwdefaults__ or {}).get("cost_path") == cost_mod.DEFAULT_COST_PATH


def test_the_ask_count_comes_from_the_run_and_not_from_the_file() -> None:
    """The cycle, broken rather than documented.

    `asks` describes a run; the ledger facts describe money already spent. Storing both in
    one file and reading both back published two wrong figures in a day: once from running
    the pair in the wrong order, and once from running them in the right order across a
    change that altered the residual, where no ordering helps because the file was written
    before the behaviour changed.
    """
    stored = a_cost(asks=2606)
    fresh = stored.with_asks(2173)

    assert stored.asks == 2606, "the file's value is untouched"
    assert fresh.asks == 2173
    assert fresh.cost_usd == stored.cost_usd, "the ledger half does not move"
    assert fresh.pipeline_calls == stored.pipeline_calls
    assert fresh.deduplication != stored.deduplication, "and the derived figure follows"


def test_the_report_supplies_its_own_ask_count(tmp_path: Path) -> None:
    from sever.corpus.generate import build
    from sever.eval.report import _cost_for

    corpus = build(documents=4, seed=20270802)
    path = write(a_cost(pages=corpus.page_count, documents=len(corpus), asks=999), tmp_path / "c.json")

    assert _cost_for(path, corpus, 40) is not None
    assert _cost_for(path, corpus, 40).asks == 40  # type: ignore[union-attr]
    # Zero means the model layer was off, and then there is nothing to override with.
    assert _cost_for(path, corpus, 0).asks == 999  # type: ignore[union-attr]


def test_a_run_that_paid_for_both_arms_is_split_by_the_answers_it_bought() -> None:
    """One run id, two arms: the n-th row paid for the n-th answer, and replaying the
    pipeline says which answers were its own. An earlier run under the same id is dropped
    by `since`, and a row that ended in an error paid for nothing."""
    early = {**a_row("mixed", cost=9.0), "ts_utc": "2026-10-19T12:00:00Z"}
    failed = {**a_row("mixed", cost=0.0), "ts_utc": "2026-10-20T15:00:00Z", "error_type": "timeout"}
    paid = [
        {**a_row("mixed", cost=c), "ts_utc": f"2026-10-20T15:0{i}:00Z"}
        for i, c in enumerate((0.01, 0.02, 0.04))
    ]
    result = from_ledger(
        ledger=FakeLedger([early, failed, *paid]),
        project=PROJECT,
        run_ids=("mixed",),
        pages=10,
        documents=10,
        cached_answers=3,
        asks=2,
        since="2026-10-20T14:00:00Z",
        answer_keys=("a", "b", "c"),
        pipeline_keys=frozenset({"a", "c"}),
    )
    assert result.pipeline_runs == ("mixed:pipeline",)
    assert result.per_run == {"mixed:baseline": 0.02, "mixed:pipeline": 0.05}
    assert round(result.usd_per_page, 6) == 0.005
