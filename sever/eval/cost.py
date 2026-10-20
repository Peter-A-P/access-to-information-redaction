"""Cost per page, from the gateway's ledger rather than from an estimate.

Section 10 asks for cost per page and names the source: the ledger. That matters, because
there are three numbers a project can call "cost per page" and only one of them is the
ledger's.

  * What the tokens would cost at list price, multiplied out by hand. This is an estimate
    dressed as a measurement, and it was wrong here by two orders of magnitude.
  * What the answers behind the published table charged, divided by pages. This is the
    ledger's number, and it is what a public body pays to run this corpus once.
  * What the same pages would have charged with no answer cache. This is the number that
    matters to anyone whose documents are not template-generated, because the saving here
    is a property of a synthetic corpus and will not transfer.

All three are different, the gap between the last two is this project's entire cost story,
and so the line prints both of the honest ones and says which is which.

## One run is the wrong unit

The obvious implementation totals a single run id. It is wrong here and the error flatters
the project: `sever-full-210` paid for 466 calls, but it answered the corpus using 405
answers earlier runs had already paid for. Reported alone it would halve the true figure.

The right unit is the set of runs that between them paid for every answer in the committed
cache, and there is a check that says whether they do: the cache holds one line per
distinct answer, the ledger holds one row per paid call, and if the runs named here are the
complete set then the two counts are equal. `from_ledger` raises when they are not, because
a cost per page that quietly omits a run is worse than no cost per page at all.

Development spend is deliberately outside that set. The smoke runs are not what a page
costs, they are what building the thing cost, and they are reported in PLAN.md where that
belongs.

## The cycle between this and the report, and why it is broken rather than documented

`sever cost` needs to know how many times the pipeline asked, to say what share of its
requests repeated. That number is a property of a *run*, and the only thing that knows it is
`sever report`. So the first version read it out of `results/results.json` while the report
read the cost line out of `results/cost.json`, which is a cycle, and it produced two wrong
published figures in one day: once by running the pair in the wrong order, and once by
running them in the right order across a change that altered the residual, where one pass is
not enough however it is ordered.

The ordering was documented after the first and that did not prevent the second, which is
the argument for fixing the shape instead. **`asks` is no longer read from a file.** This
module stores only what the ledger knows, which changes when money is spent and at no other
time, and the report supplies the denominator from the run it has just finished, through
`RunCost.with_asks`. The stored value remains for `sever cost`'s own output and is
explicitly not what the published line uses.

The general form: a number that describes a run should be carried by the run, not
round-tripped through a file that something else also writes.

## Why this reads a file instead of the ledger

The ledger lives in project 04's working copy, which nobody cloning this repository has.
So one privileged run records the ledger's answer into `results/cost.json`, that file is
committed, and `sever report` reads it. Exactly the arrangement the answer cache already
uses for the model tables, for the same reason: a number that can only be produced by
someone holding a private dependency is not reproducible, but a number *recorded* by that
someone and checked into the repository can at least be read, dated and argued with.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

# The plan's budget is in Canadian dollars and the ledger is in US dollars. The rate is
# the portfolio's stated planning rate, not a live quote, and it is named next to every
# figure it produces so that nothing reads as a settled exchange.
CAD_PER_USD = 1.35

DEFAULT_COST_PATH = Path("results/cost.json")

# The runs behind the tool's own rows, and the only ones whose spend is a cost of running
# the pipeline over a page.
PIPELINE_RUNS: tuple[str, ...] = ("sever-haiku55-210:pipeline",)

# The model-only baseline. It asks about every span rather than the residual the rules
# could not settle, so it paid for 1,357 answers the pipeline never needs. Its spend is a
# cost of measuring the tool, not a cost of running it, and folding the two together would
# have doubled the published cost per page for a configuration nobody would deploy.
BASELINE_RUNS: tuple[str, ...] = ("sever-haiku55-210:baseline",)

# Everything that paid for a line in the committed answer cache. The integrity check is
# against this, because the cache does not record which run bought which answer, and a
# check over a subset would pass while a whole run was missing.
PUBLISHED_RUNS: tuple[str, ...] = ("sever-haiku55-210",)
# Rows under the published run id before this belong to an exploratory run that reused it
# on 2026-10-19; the published run began at 14:10 UTC on 2026-10-20.
PUBLISHED_SINCE = "2026-10-20T14:00:00Z"


class LedgerMismatch(RuntimeError):
    """The named runs do not account for the committed answers, in one direction or other."""


@dataclass(frozen=True, slots=True)
class RunCost:
    """What the published answers cost, as the ledger recorded it."""

    run_ids: tuple[str, ...]
    # The subset of `run_ids` whose spend is a cost of running the pipeline rather than a
    # cost of measuring it. The headline figure is over these.
    pipeline_runs: tuple[str, ...]
    recorded_on: str
    model: str
    calls: int
    cost_usd: float
    input_tokens: int
    output_tokens: int
    uncosted: int
    pages: int
    documents: int
    # Distinct answers in the committed cache. Equal to `calls` when the run list is
    # complete, which is the invariant `from_ledger` enforces.
    cached_answers: int
    # Times the pipeline asked for an answer, including every time the cache served one
    # without a call. This is the denominator the deduplication is measured against.
    asks: int
    per_run: dict[str, float] = field(default_factory=dict)
    calls_per_run: dict[str, int] = field(default_factory=dict)

    def with_asks(self, asks: int) -> RunCost:
        """The same ledger facts, against a fresh count of what the pipeline asked.

        The report calls this with the run it has just finished, because the stored `asks`
        describes whichever run last wrote `results/cost.json` and goes stale the moment
        the residual changes. The ledger half of this object does not go stale, because it
        only moves when money is spent.
        """
        return replace(self, asks=asks)

    @property
    def pipeline_cost_usd(self) -> float:
        """What the tool's own rows cost, leaving out the baselines built to measure it."""
        return sum(v for k, v in self.per_run.items() if k in self.pipeline_runs)

    @property
    def baseline_cost_usd(self) -> float:
        return self.cost_usd - self.pipeline_cost_usd

    @property
    def usd_per_page(self) -> float:
        return self.pipeline_cost_usd / self.pages if self.pages else 0.0

    @property
    def pipeline_calls(self) -> int:
        return sum(v for k, v in self.calls_per_run.items() if k in self.pipeline_runs)

    @property
    def usd_per_call(self) -> float:
        return self.pipeline_cost_usd / self.pipeline_calls if self.pipeline_calls else 0.0

    @property
    def undeduplicated_usd_per_page(self) -> float:
        """What a page would cost if no two requests were ever identical.

        The mean cost per paid call, multiplied by every answer the pipeline asked for
        rather than by the ones it paid for. It is an estimate and an optimistic one: the
        distinct requests are not a random sample of all requests, so the mean understates
        them somewhat. It is here because the deduplicated figure is a property of a
        template-generated corpus and would mislead anyone reading it as a quote.
        """
        if not self.pages:
            return 0.0
        return self.usd_per_call * self.asks / self.pages

    @property
    def deduplication(self) -> float:
        if not self.asks:
            return 0.0
        return 1.0 - (self.pipeline_calls / self.asks)

    @property
    def cad_per_page(self) -> float:
        return self.usd_per_page * CAD_PER_USD

    def to_markdown(self) -> str:
        line = (
            f"**Cost:** US${self.usd_per_page:.5f} per page "
            f"(CA${self.cad_per_page:.5f} at {CAD_PER_USD} CAD/USD), from project 04's "
            f"gateway ledger: US${self.pipeline_cost_usd:.4f} over "
            f"{self.pipeline_calls} paid calls and {self.pages} pages. The pipeline asked "
            f"{self.asks} times and paid {self.pipeline_calls} of them, because "
            f"{self.deduplication:.0%} of its requests were byte-identical to one already "
            f"made. Without that deduplication the same pages would cost about "
            f"US${self.undeduplicated_usd_per_page:.5f} each, which is the figure to read "
            f"if your documents are not generated from templates."
        )
        # Rounded before the test: summing floats then subtracting leaves a residue of
        # about 1e-18 when the two sets are the same, which is truthy and would append a
        # sentence about a baseline that does not exist.
        if round(self.baseline_cost_usd, 4) > 0:
            line += (
                f" A further US${self.baseline_cost_usd:.4f} bought the model-only "
                f"baseline, which asks about every span rather than the residual. That is "
                f"a cost of measuring the tool and not of running it, so it is named here "
                f"rather than divided into the figure above."
            )
        return line


def from_ledger(
    *,
    ledger: Any,
    project: str,
    run_ids: tuple[str, ...] = PUBLISHED_RUNS,
    pipeline_runs: tuple[str, ...] = PIPELINE_RUNS,
    pages: int,
    documents: int,
    cached_answers: int,
    asks: int,
    model: str = "",
    today: dt.date | None = None,
    since: str | None = None,
    answer_keys: Sequence[str] = (),
    pipeline_keys: frozenset[str] | None = None,
) -> RunCost:
    """Total the published runs out of the gateway's ledger, and check they are all of them.

    Takes the store rather than a path so the tests can hand it a stand-in: the job here is
    the arithmetic and the honesty of the fields, not the SQL.

    **A run that paid for both arms.** `sever report` with the model-only baseline on asks
    for both under one run id, so the id cannot say which arm a call was for. The answer
    cache can: answers are appended in the order they were paid for, so the n-th answer is
    the n-th successful row of the run, and replaying the pipeline arm alone says which
    answers it asked for. With `answer_keys` (the cache's keys, in file order) and
    `pipeline_keys`, each row is filed under `<run>:pipeline` or `<run>:baseline`, and the
    headline is over the first. A key both arms asked for was paid by the pipeline, which
    asks first on every document. `since` drops earlier rows under a reused run id.
    """
    wanted = set(run_ids)
    rows = [
        r
        for r in ledger.rows(project=project)
        if r.get("run_id") in wanted
        and not r.get("error_type")
        and (since is None or str(r.get("ts_utc") or "") >= since)
    ]
    if not rows:
        raise LookupError(
            f"the ledger holds no rows for {sorted(wanted)} under project {project!r}. "
            f"Cost per page is reported from the ledger and nothing else, so there is "
            f"nothing to report."
        )
    seen = {str(r.get("run_id")) for r in rows}
    if missing := wanted - seen:
        raise LookupError(f"the ledger holds no rows for {sorted(missing)}")
    if len(rows) != cached_answers:
        raise LedgerMismatch(
            f"{len(rows)} paid calls across {sorted(wanted)} against {cached_answers} "
            f"answers in the committed cache. These must be equal: every cached answer was "
            f"paid for exactly once. A shortfall means a paid run is missing from the list "
            f"and the cost per page would be under-reported; an excess means a run in the "
            f"list also served something that is not in the cache. Either way the number "
            f"would be wrong, so it is not written."
        )
    labels = [str(r.get("run_id")) for r in rows]
    if pipeline_keys is not None:
        if len(answer_keys) != len(rows):
            raise LedgerMismatch(
                f"{len(rows)} rows against {len(answer_keys)} answer keys: the rows cannot "
                f"be matched to the answers they paid for, so neither arm can be costed."
            )
        labels = [
            f"{label}:{'pipeline' if key in pipeline_keys else 'baseline'}"
            for label, key in zip(labels, answer_keys, strict=True)
        ]
        pipeline_runs = tuple(sorted({lb for lb in labels if lb.endswith(":pipeline")}))
        wanted = set(labels)
    per_run: dict[str, float] = {}
    calls_per_run: dict[str, int] = {}
    for r, rid in zip(rows, labels, strict=True):
        per_run[rid] = per_run.get(rid, 0.0) + float(r.get("cost_usd") or 0.0)
        calls_per_run[rid] = calls_per_run.get(rid, 0) + 1
    return RunCost(
        run_ids=tuple(sorted(wanted)),
        pipeline_runs=tuple(sorted(set(pipeline_runs) & wanted)),
        recorded_on=(today or dt.date.today()).isoformat(),
        model=model or str(rows[0].get("model_returned") or rows[0].get("model_requested") or ""),
        calls=len(rows),
        cost_usd=sum(per_run.values()),
        input_tokens=sum(int(r.get("input_tokens") or 0) for r in rows),
        output_tokens=sum(int(r.get("output_tokens") or 0) for r in rows),
        uncosted=sum(1 for r in rows if not r.get("costed")),
        pages=pages,
        documents=documents,
        cached_answers=cached_answers,
        asks=asks,
        per_run={k: round(v, 6) for k, v in sorted(per_run.items())},
        calls_per_run=dict(sorted(calls_per_run.items())),
    )


def write(cost: RunCost, path: Path = DEFAULT_COST_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": (
            "Written by `sever cost`, which reads project 04's gateway ledger. Committed "
            "because that ledger is not in this repository, so `sever report` reads this "
            "instead. See sever/eval/cost.py."
        ),
        **asdict(cost),
        "usd_per_page": round(cost.usd_per_page, 8),
        "undeduplicated_usd_per_page": round(cost.undeduplicated_usd_per_page, 8),
        "cad_per_page": round(cost.cad_per_page, 8),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read(path: Path = DEFAULT_COST_PATH) -> RunCost | None:
    """The recorded cost, or None when it has not been recorded.

    Missing is a normal state, not an error: the report runs in CI with no gateway and no
    ledger, and a missing cost line is better than a fabricated one.
    """
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = set(RunCost.__dataclass_fields__)
    kept = {k: v for k, v in data.items() if k in fields}
    kept["run_ids"] = tuple(kept.get("run_ids", ()))
    kept["pipeline_runs"] = tuple(kept.get("pipeline_runs", ()))
    if missing := fields - set(kept) - {"per_run", "calls_per_run"}:
        # A stale file from an older schema. Named rather than raised as a TypeError from
        # the constructor, because the reader of that traceback is someone running
        # `sever report` and wondering why the tables will not generate.
        raise LedgerMismatch(
            f"{path} was written by an older version of `sever cost` and is missing "
            f"{sorted(missing)}. Re-run `sever cost`, or delete the file to publish the "
            f"tables without a cost line."
        )
    return RunCost(**kept)
