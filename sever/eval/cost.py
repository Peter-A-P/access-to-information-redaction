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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# The plan's budget is in Canadian dollars and the ledger is in US dollars. The rate is
# the portfolio's stated planning rate, not a live quote, and it is named next to every
# figure it produces so that nothing reads as a settled exchange.
CAD_PER_USD = 1.35

DEFAULT_COST_PATH = Path("results/cost.json")

# The runs that between them paid for every answer in `results/model-answers.jsonl`. The
# count check in `from_ledger` is what keeps this list honest: add a paid run against this
# corpus and leave it out here, and the next `sever cost` refuses rather than under-reports.
PUBLISHED_RUNS: tuple[str, ...] = (
    "sever-full-001",
    "sever-full-210",
    "sever-sweep-210",
    "sever-retype-210",
)


class LedgerMismatch(RuntimeError):
    """The named runs do not account for the committed answers, in one direction or other."""


@dataclass(frozen=True, slots=True)
class RunCost:
    """What the published answers cost, as the ledger recorded it."""

    run_ids: tuple[str, ...]
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

    @property
    def usd_per_page(self) -> float:
        return self.cost_usd / self.pages if self.pages else 0.0

    @property
    def usd_per_call(self) -> float:
        return self.cost_usd / self.calls if self.calls else 0.0

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
        return 1.0 - (self.calls / self.asks) if self.asks else 0.0

    @property
    def cad_per_page(self) -> float:
        return self.usd_per_page * CAD_PER_USD

    def to_markdown(self) -> str:
        return (
            f"**Cost:** US${self.usd_per_page:.5f} per page "
            f"(CA${self.cad_per_page:.5f} at {CAD_PER_USD} CAD/USD), from project 04's "
            f"gateway ledger: US${self.cost_usd:.4f} over {self.calls} paid calls and "
            f"{self.pages} pages. The pipeline asked {self.asks} times and paid "
            f"{self.calls} of them, because {self.deduplication:.0%} of its requests were "
            f"byte-identical to one already made. Without that deduplication the same "
            f"pages would cost about US${self.undeduplicated_usd_per_page:.5f} each, which "
            f"is the figure to read if your documents are not generated from templates."
        )


def from_ledger(
    *,
    ledger: Any,
    project: str,
    run_ids: tuple[str, ...] = PUBLISHED_RUNS,
    pages: int,
    documents: int,
    cached_answers: int,
    asks: int,
    model: str = "",
    today: dt.date | None = None,
) -> RunCost:
    """Total the published runs out of the gateway's ledger, and check they are all of them.

    Takes the store rather than a path so the tests can hand it a stand-in: the job here is
    the arithmetic and the honesty of the fields, not the SQL.
    """
    wanted = set(run_ids)
    rows = [r for r in ledger.rows(project=project) if r.get("run_id") in wanted]
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
    per_run: dict[str, float] = {}
    for r in rows:
        rid = str(r.get("run_id"))
        per_run[rid] = per_run.get(rid, 0.0) + float(r.get("cost_usd") or 0.0)
    return RunCost(
        run_ids=tuple(sorted(wanted)),
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
    if missing := fields - set(kept) - {"per_run"}:
        # A stale file from an older schema. Named rather than raised as a TypeError from
        # the constructor, because the reader of that traceback is someone running
        # `sever report` and wondering why the tables will not generate.
        raise LedgerMismatch(
            f"{path} was written by an older version of `sever cost` and is missing "
            f"{sorted(missing)}. Re-run `sever cost`, or delete the file to publish the "
            f"tables without a cost line."
        )
    return RunCost(**kept)
