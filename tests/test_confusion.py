"""The scorer, and the cross-check against project 03's independent implementation.

Two things are tested here that are easy to get wrong and invisible when you do.

The first is the estimator itself. This project's units are labelled spans, and spans
within a document are not independent: one persona generates forty of them, and that is
one fact voting forty times. Resampling spans rather than documents produces intervals far
too narrow, which makes every published number look more certain than it is. The test
below shows the size of the error: on a fixture where each document is internally
unanimous, the item bootstrap's interval is about a sixth the width of the correct one
around the same point.

The second is agreement. Project 03 was asked for a cluster bootstrap and wrote
`drift.analysis.stats.bootstrap_mean_by_cluster` from the same description, not from this
code. The recorded values below come from running 03's implementation on the fixture, and
this project's own implementation has to match them. Two implementations written
independently that agree is a stronger claim than one shared implementation, and it is why
`drift` is not a dependency here: it pulls `boundary`, and shortly `mselect` with numpy,
scipy, polars, pyarrow and matplotlib, which is a lot of machinery to import for forty
lines of arithmetic.
"""

from __future__ import annotations

import math

from sever.corpus.labels import LabelledSpan, LabelSource
from sever.eval.confusion import UNDEFINED, Interval, SpanOutcome, _rate
from sever.ingest.document import Offsets
from sever.taxonomy.loader import Decision

# --- the fixture 03 and 07 were both run against ------------------------------
#
# Ten documents, forty spans each, each document internally unanimous, five of the ten
# positive. The point is 50 percent however it is resampled; only the interval moves.
# Values recorded from drift.analysis.stats on 2026-09-19, stable across seeds 0 and
# 20270816 because with ten unanimous clusters the resampled mean can only land on a
# multiple of a tenth.
CLUSTER_LOW = 0.2
CLUSTER_HIGH = 0.8
# The same data through 03's item-level bootstrap_mean, for the comparison.
ITEM_LOW = 0.4525
ITEM_HIGH = 0.5500
# Monte Carlo noise between two different random number generators at 2,000 resamples.
TOLERANCE = 0.02


def _fixture() -> list[SpanOutcome]:
    out: list[SpanOutcome] = []
    for d in range(10):
        for i in range(40):
            positive = d < 5
            out.append(
                SpanOutcome(
                    doc_id=f"doc-{d:02d}",
                    label=LabelledSpan(
                        page=1,
                        offsets=Offsets(i, i + 1),
                        text="x",
                        code="R1" if positive else "K2",
                        source=LabelSource.CONSTRUCTED,
                    ),
                    proposal=None,
                    true_decision=Decision.REDACT if positive else Decision.KEEP,
                    proposed_decision=None,
                )
            )
    return out


def _positive(o: SpanOutcome) -> bool:
    return o.true_decision is Decision.REDACT


def test_the_point_estimate_is_the_plain_mean() -> None:
    result = _rate(_fixture(), _positive, seed=20270816)
    assert result.point == 0.5
    assert result.n == 400
    assert result.clusters == 10


def test_the_interval_matches_project_03s_independent_implementation() -> None:
    """The cross-check. If this drifts, one of the two is wrong."""
    result = _rate(_fixture(), _positive, seed=20270816)
    assert abs(result.low - CLUSTER_LOW) < TOLERANCE, (
        f"low bound {result.low:.4f} against 03's {CLUSTER_LOW}"
    )
    assert abs(result.high - CLUSTER_HIGH) < TOLERANCE, (
        f"high bound {result.high:.4f} against 03's {CLUSTER_HIGH}"
    )


def test_resampling_spans_instead_of_documents_would_understate_the_width() -> None:
    """Why the estimator is what it is, in one number."""
    result = _rate(_fixture(), _positive, seed=20270816)
    cluster_width = result.high - result.low
    item_width = ITEM_HIGH - ITEM_LOW
    assert cluster_width > item_width * 4, (
        f"the cluster interval is {cluster_width:.3f} wide and the item interval "
        f"{item_width:.3f}; if these are close, the resampling unit is wrong"
    )


def test_one_document_reports_an_undefined_interval_rather_than_nan() -> None:
    """A single cluster has nothing to resample. Saying so is not the same as printing
    NaN bounds, which read as a broken interval rather than an absent one."""
    pool = [o for o in _fixture() if o.doc_id == "doc-00"]
    result = _rate(pool, _positive, seed=1)
    assert result.point == 1.0
    assert result.clusters == 1
    assert result.interval_undefined
    assert math.isnan(result.low) and math.isnan(result.high)
    printed = str(result)
    assert "interval undefined" in printed
    assert "nan" not in printed.casefold(), printed


def test_an_empty_pool_is_not_a_zero() -> None:
    result = _rate([], _positive, seed=1)
    assert result is UNDEFINED
    assert not result.is_defined
    assert str(result) == "n/a (0)"


def test_a_defined_interval_prints_its_bounds_and_n() -> None:
    printed = str(Interval(point=0.273, low=0.262, high=0.284, n=3955, clusters=210))
    assert printed == "27.3% (26.2% to 28.4%), n=3955"


def test_clusters_are_counted_from_the_documents_present() -> None:
    pool = [o for o in _fixture() if o.doc_id in ("doc-00", "doc-01", "doc-09")]
    result = _rate(pool, _positive, seed=1)
    assert result.clusters == 3
    assert result.n == 120
