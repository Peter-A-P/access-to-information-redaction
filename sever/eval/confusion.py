"""Scoring: leak rate, over-redaction rate, category accuracy, and intervals on all of it.

Definitions, stated once and used everywhere, because these are the published numbers and
a reader is entitled to know exactly what was counted.

  * A **must-redact** span is a labelled span whose true code carries the redact decision
    (R1, R2). A **must-keep** span is one whose true code carries keep (K1 to K6).
  * **Leak rate** = must-redact spans the tool proposed to release, over all must-redact
    spans. A span the detector never found counts as a leak. That is the strict reading
    and it is the right one: from the requester's point of view a name in the released
    record is in the released record, and it makes no difference which component failed.
    The error decomposition then says which did.
  * **Over-redaction rate** = must-keep spans the tool proposed to withhold, over all
    must-keep spans. Escalations withhold, so they count here. That is deliberate and it
    is the honest accounting: an escalated span is not in the released record when it
    reaches the requester unless a reviewer clears it, and a tool that escalates
    everything must not be able to score a perfect over-redaction rate.
  * **Category accuracy** = of correctly withheld must-redact spans, the share given the
    right code, because the schedule cites the code.

Escalations are additionally reported on their own, so a reader can see the trade the tool
is making rather than only its net effect.

Intervals are bootstrap percentile intervals resampled over **documents**, not over spans.
Spans within a document are not independent (one persona generates many of them), so
resampling spans would produce intervals that are far too narrow. This is the kind of
detail that quietly makes a results table wrong, so it is a parameter with one legal value
and a comment rather than an implementation detail.

Project 03 implemented the same estimator independently, as
`drift.analysis.stats.bootstrap_mean_by_cluster`, after this project asked for it. The two
were written from the same description and not from each other, and on this project's own
scored corpus they agree: identical point estimates and interval bounds within 0.13
percentage points, which is Monte Carlo noise between two different random number
generators at 2,000 resamples. `tests/test_confusion.py` pins that agreement against
recorded values from 03's implementation. `drift` is not a dependency here: it pulls
`boundary`, and shortly `mselect` with numpy, scipy, polars, pyarrow and matplotlib, which
is a great deal of machinery to import for forty lines of arithmetic. Two independent
implementations that agree are worth more than one shared one anyway.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from sever.corpus.labels import LabelledSpan, LabelSet, LabelSource
from sever.decide.pipeline import DocumentProposals, Proposal
from sever.taxonomy.loader import Decision, Taxonomy, default_taxonomy

BOOTSTRAP_RESAMPLES = 2000
DEFAULT_SEED = 20270816


@dataclass(frozen=True, slots=True)
class Interval:
    """A point estimate with a 95 percent bootstrap percentile interval.

    `clusters` is how many documents the interval rests on, which is the number that
    actually governs its width. It is carried because an interval over 5,000 spans from
    three documents is a much weaker claim than the same interval over 5,000 spans from
    two hundred, and a cell that prints only `n` hides the difference.
    """

    point: float
    low: float
    high: float
    n: int
    clusters: int = 0

    @property
    def is_defined(self) -> bool:
        return self.n > 0

    @property
    def interval_undefined(self) -> bool:
        """True when there was nothing to resample: fewer than two documents.

        Reported rather than papered over. An earlier version returned NaN bounds here and
        printed them, so a single-document result read as `75.0% (nan% to nan%)`, which
        looks like a broken interval rather than an absent one. Project 03 got this right
        first in `drift.analysis.stats` and this follows it.
        """
        return self.n > 0 and self.clusters < 2

    def __str__(self) -> str:
        if self.n == 0:
            return "n/a (0)"
        if self.interval_undefined:
            return (
                f"{self.point:.1%} (interval undefined: {self.clusters} document, "
                f"n={self.n})"
            )
        return f"{self.point:.1%} ({self.low:.1%} to {self.high:.1%}), n={self.n}"


UNDEFINED = Interval(point=float("nan"), low=float("nan"), high=float("nan"), n=0, clusters=0)


@dataclass(frozen=True, slots=True)
class SpanOutcome:
    """One labelled span, matched against what the tool proposed for it."""

    doc_id: str
    label: LabelledSpan
    proposal: Proposal | None
    true_decision: Decision
    proposed_decision: Decision | None

    @property
    def detected(self) -> bool:
        return self.proposal is not None

    @property
    def true_code(self) -> str:
        return self.label.code

    @property
    def proposed_code(self) -> str | None:
        return self.proposal.code if self.proposal else None

    @property
    def must_redact(self) -> bool:
        return self.true_decision is Decision.REDACT

    @property
    def must_keep(self) -> bool:
        return self.true_decision is Decision.KEEP

    @property
    def must_be_weighed(self) -> bool:
        """The statute reserves this span for a person, so the machine may not settle it.

        Empty under the federal configuration, which is why this went unnoticed: no
        federal code's true decision is `escalate`. Under ATIPPA two are, because
        40(5)(j) makes the time since a death a circumstance the head of a public body
        weighs and 40(2)(m) is too narrow to release a name that is public for some other
        reason. See `sever/taxonomy/nl.yaml`.
        """
        return self.true_decision is Decision.ESCALATE

    @property
    def is_unweighed_release(self) -> bool:
        """Released without the weighing the statute requires.

        This is not a leak: the information might well have been releasable, and might not
        have been. Nobody looked. For a tool whose first claim is that it proposes and a
        person decides, deciding a question the Act assigns to a person is a failure of a
        different kind from getting the answer wrong, and it needs its own number rather
        than being folded into one of the others.
        """
        return self.must_be_weighed and not self.was_withheld

    @property
    def was_withheld(self) -> bool:
        """An undetected span is released: nothing proposed a box over it."""
        return self.proposal is not None and self.proposal.withholds

    @property
    def is_leak(self) -> bool:
        return self.must_redact and not self.was_withheld

    @property
    def is_over_redaction(self) -> bool:
        return self.must_keep and self.was_withheld

    @property
    def is_escalation(self) -> bool:
        return self.proposal is not None and self.proposal.is_escalation

    @property
    def category_correct(self) -> bool:
        return self.proposed_code == self.true_code

    @property
    def failed_because_undetected(self) -> bool:
        """A leak the detector caused by not finding the span at all."""
        return self.is_leak and not self.detected

    @property
    def failed_because_mislabelled(self) -> bool:
        """A leak the detector caused by naming the span, having found it.

        This is the third bucket and it exists because a two-bucket decomposition put it in
        the wrong one. A span typed LOCATION or ORGANISATION is not information about an
        identifiable individual, so `not_personal_information` returns K6 and K6 releases.
        The span was found, so recall counts it; the rule then behaved correctly on a false
        premise, so it reads as a decision error. It is neither. It is a wrong label, and
        blaming the decision layer for it sends the next fix to the wrong module.

        Found the hard way. A bare Labrador surname is typed as a LOCATION and released with
        "not information about an identifiable individual" printed beside it in the
        schedule, and every recall figure in the repository stayed healthy while it
        happened. Project 04 observed that neither project had a measurement that would
        catch a wrong label without someone going looking. This is that measurement.
        """
        if not (self.is_leak and self.detected) or self.proposal is None:
            return False
        return not self.proposal.detection.entity_type.is_about_a_person


@dataclass(frozen=True, slots=True)
class Scored:
    outcomes: tuple[SpanOutcome, ...]
    # Spans the tool proposed that no label covers: detector false positives.
    unlabelled_proposals: tuple[Proposal, ...] = ()
    label_source: LabelSource = LabelSource.CONSTRUCTED
    taxonomy: Taxonomy = field(default_factory=default_taxonomy)

    @property
    def doc_ids(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for o in self.outcomes:
            seen.setdefault(o.doc_id, None)
        return tuple(seen)

    def filtered(self, code: str | None = None) -> tuple[SpanOutcome, ...]:
        if code is None:
            return self.outcomes
        return tuple(o for o in self.outcomes if o.true_code == code)

    # --- the published numbers -------------------------------------------------

    def leak_rate(self, code: str | None = None, *, seed: int = DEFAULT_SEED) -> Interval:
        if not self.label_source.is_complete:
            raise ValueError(
                "leak rate is not computable on an observed-label track: what sits under "
                "an existing redaction was never recoverable, so the denominator does not "
                "exist. Use over_redaction_rate, which is what that track measures."
            )
        pool = [o for o in self.filtered(code) if o.must_redact]
        return _rate(pool, lambda o: o.is_leak, seed=seed)

    def over_redaction_rate(
        self, code: str | None = None, *, seed: int = DEFAULT_SEED
    ) -> Interval:
        pool = [o for o in self.filtered(code) if o.must_keep]
        return _rate(pool, lambda o: o.is_over_redaction, seed=seed)

    def unweighed_release_rate(
        self, code: str | None = None, *, seed: int = DEFAULT_SEED
    ) -> Interval:
        """Of the spans the statute reserves for a person, how many the machine released.

        The denominator is empty under the federal configuration and the cell reads n/a,
        which is the honest rendering: there is nothing to report, not a perfect score.
        """
        pool = [o for o in self.filtered(code) if o.must_be_weighed]
        return _rate(pool, lambda o: o.is_unweighed_release, seed=seed)

    def escalation_rate(self, code: str | None = None, *, seed: int = DEFAULT_SEED) -> Interval:
        pool = list(self.filtered(code))
        return _rate(pool, lambda o: o.is_escalation, seed=seed)

    def category_accuracy(self, code: str | None = None, *, seed: int = DEFAULT_SEED) -> Interval:
        pool = [o for o in self.filtered(code) if o.must_redact and o.was_withheld]
        return _rate(pool, lambda o: o.category_correct, seed=seed)

    def detector_recall(self, code: str | None = None, *, seed: int = DEFAULT_SEED) -> Interval:
        pool = list(self.filtered(code))
        return _rate(pool, lambda o: o.detected, seed=seed)

    def decomposition(self) -> dict[str, int]:
        """Where the leaks came from. The plan's error decomposition table, in three
        buckets rather than two: see `SpanOutcome.failed_because_mislabelled` for why the
        middle one had to be split out of the last one."""
        leaks = [o for o in self.outcomes if o.is_leak]
        undetected = sum(1 for o in leaks if o.failed_because_undetected)
        mislabelled = sum(1 for o in leaks if o.failed_because_mislabelled)
        return {
            "leaks": len(leaks),
            "detector_missed": undetected,
            "detector_mislabelled": mislabelled,
            "decision_wrong": len(leaks) - undetected - mislabelled,
            "must_redact_spans": sum(1 for o in self.outcomes if o.must_redact),
            "must_be_weighed_spans": sum(1 for o in self.outcomes if o.must_be_weighed),
            "unweighed_releases": sum(1 for o in self.outcomes if o.is_unweighed_release),
        }

    def confusion(self) -> dict[tuple[str, str], int]:
        """True code against proposed code. "-" is the proposed code for an undetected
        span, which is a real outcome and not a missing value."""
        out: dict[tuple[str, str], int] = {}
        for o in self.outcomes:
            key = (o.true_code, o.proposed_code or "-")
            out[key] = out.get(key, 0) + 1
        return out

    def codes_present(self) -> tuple[str, ...]:
        return tuple(sorted({o.true_code for o in self.outcomes}))

    def summary(self) -> dict[str, object]:
        d = self.decomposition()
        out: dict[str, object] = {
            "spans": len(self.outcomes),
            "documents": len(self.doc_ids),
            "over_redaction_rate": str(self.over_redaction_rate()),
            "unweighed_release_rate": str(self.unweighed_release_rate()),
            "escalation_rate": str(self.escalation_rate()),
            "detector_recall": str(self.detector_recall()),
            "false_positive_spans": len(self.unlabelled_proposals),
            **{f"decomposition_{k}": v for k, v in d.items()},
        }
        if self.label_source.is_complete:
            out["leak_rate"] = str(self.leak_rate())
            out["category_accuracy"] = str(self.category_accuracy())
        return out


class Clustered(Protocol):
    """Anything that knows which document it came from.

    `_rate` is generic over this rather than tied to `SpanOutcome`, because the detector
    evaluation resamples its own records over the same clusters and should share one
    estimator rather than own a second copy of the arithmetic.

    Declared as a read-only property rather than `doc_id: str`. A protocol member written
    as a bare annotation is a *settable* attribute, which a frozen dataclass does not
    satisfy, and every record on both sides of this is frozen.
    """

    @property
    def doc_id(self) -> str: ...


def _rate[C: Clustered](
    pool: Sequence[C],
    predicate: Callable[[C], bool],
    *,
    seed: int,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> Interval:
    """A proportion with a bootstrap interval resampled over documents."""
    if not pool:
        return UNDEFINED
    hits = np.array([1.0 if predicate(o) else 0.0 for o in pool])
    point = float(hits.mean())

    by_doc: dict[str, list[float]] = {}
    for o, h in zip(pool, hits, strict=True):
        by_doc.setdefault(o.doc_id, []).append(float(h))
    docs = list(by_doc)
    if len(docs) < 2:
        # One document gives no between-document variation to resample. Report the point
        # estimate with an undefined interval rather than a fabricated one.
        return Interval(
            point=point, low=float("nan"), high=float("nan"), n=len(pool), clusters=len(docs)
        )

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(docs), size=(resamples, len(docs)))
    draws = np.empty(resamples)
    values = [by_doc[d] for d in docs]
    for r in range(resamples):
        picked = [v for i in idx[r] for v in values[i]]
        draws[r] = sum(picked) / len(picked) if picked else np.nan
    low, high = np.nanpercentile(draws, [2.5, 97.5])
    return Interval(
        point=point, low=float(low), high=float(high), n=len(pool), clusters=len(docs)
    )


def score(
    results: Mapping[str, tuple[DocumentProposals, LabelSet]],
    *,
    taxonomy: Taxonomy | None = None,
    jurisdiction: str = "federal",
) -> Scored:
    """Match proposals to labels by overlap, one document at a time.

    `jurisdiction` decides what a label's code *means*, and it has to be the same
    jurisdiction the proposals were made under. Two codes decide differently under ATIPPA
    than federally, so scoring an NL run against federal ground truth would count a
    correctly escalated span as an error, silently and in the flattering direction for
    whichever configuration happened to match. Federal is the default because every
    published number in this repository is federal.
    """
    t = taxonomy or default_taxonomy()
    outcomes: list[SpanOutcome] = []
    unlabelled: list[Proposal] = []
    source = LabelSource.CONSTRUCTED

    for doc_id, (proposals, labels) in results.items():
        source = labels.source
        used: set[tuple[int, int, int]] = set()
        for label in labels:
            best: Proposal | None = None
            best_overlap = 0
            for p in proposals:
                if p.page != label.page:
                    continue
                hit = p.detection.offsets.intersection(label.offsets)
                if hit is not None and len(hit) > best_overlap:
                    best, best_overlap = p, len(hit)
            if best is not None:
                used.add(best.key)
            outcomes.append(
                SpanOutcome(
                    doc_id=doc_id,
                    label=label,
                    proposal=best,
                    true_decision=t.decision(label.code, jurisdiction),
                    proposed_decision=best.decision if best else None,
                )
            )
        unlabelled.extend(p for p in proposals if p.key not in used)

    return Scored(
        outcomes=tuple(outcomes),
        unlabelled_proposals=tuple(unlabelled),
        label_source=source,
        taxonomy=t,
    )
