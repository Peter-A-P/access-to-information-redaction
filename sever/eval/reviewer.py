"""Reviewer minutes per page, with and without proposals.

Section 10 asks for this and it is the one number in the definition of done that no amount
of computation can produce. Every other measurement here is a program run over a corpus.
This one requires a person to sit down and read, twice, under two conditions, and the code's
whole job is to make that sitting count for something: to time it honestly, to keep the two
arms apart, and to refuse to report a number when there is not enough of it.

## What is being compared

`sever review --mode proposals` serves a record with the tool's proposals on it.
`sever review --mode unaided` serves the same record with the proposals dropped before the
session is built, so the reviewer finds and categorises every severance themselves. That is
the honest control: finding the span is most of the work, and an arm that highlighted the
spans while hiding only the suggested category would measure how long it takes to agree with
a highlight.

## Why the interval resamples over documents

Pages within a document are not independent. One record's personas, one record's density of
third parties, one reviewer's growing familiarity with a template: a bootstrap over pages
would treat twenty pages of the same letter as twenty facts. Resampling documents is the
same estimator the rest of this project uses, for the same reason.

## What this refuses to do

It will not report an arm from a single document, because there is nothing to resample and
the interval would be fabricated. It will not report a comparison unless both arms have
data. And it will not silently drop a page whose timing is missing: a page completed after a
restart has no served-at stamp, `Session.complete_page` returns None rather than guessing,
and the count of untimed pages is printed beside the result so that a reader can see how
much of the session went unmeasured.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sever.eval.confusion import BOOTSTRAP_RESAMPLES, DEFAULT_SEED

DEFAULT_TIMINGS = Path("review/timings.jsonl")

# Below this, an arm is reported as collected rather than as a result. Two documents is the
# floor for a bootstrap to mean anything at all; this is the floor for the number to be
# worth putting in a README.
MINIMUM_DOCUMENTS = 3


@dataclass(frozen=True, slots=True)
class Timed:
    """One page a reviewer finished, and how long it took them."""

    doc_id: str
    page: int
    mode: str
    seconds: float
    spans_on_page: int
    actions: int


@dataclass(frozen=True, slots=True)
class Estimate:
    """Seconds per page, with a percentile interval resampled over documents."""

    point: float
    low: float
    high: float
    pages: int
    documents: int

    @property
    def undefined(self) -> bool:
        return self.documents < 2

    @property
    def minutes(self) -> float:
        return self.point / 60.0

    @property
    def pages_per_hour(self) -> float:
        return 3600.0 / self.point if self.point else 0.0

    def __str__(self) -> str:
        if not self.pages:
            return "no pages timed"
        if self.undefined:
            return (
                f"{self.point:.0f}s per page (interval undefined: {self.documents} "
                f"document, {self.pages} pages)"
            )
        return (
            f"{self.point:.0f}s per page ({self.low:.0f} to {self.high:.0f}), "
            f"{self.pages} pages over {self.documents} documents"
        )


def read(paths: Sequence[Path]) -> tuple[Timed, ...]:
    """Every timed page across the given files, in the order they were written."""
    rows: list[Timed] = []
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            rows.append(
                Timed(
                    doc_id=str(d["doc_id"]),
                    page=int(d["page"]),
                    mode=str(d["mode"]),
                    seconds=float(d["seconds"]),
                    spans_on_page=int(d.get("spans_on_page", 0)),
                    actions=int(d.get("actions", 0)),
                )
            )
    return tuple(rows)


def estimate(
    rows: Iterable[Timed], *, seed: int = DEFAULT_SEED, resamples: int = BOOTSTRAP_RESAMPLES
) -> Estimate:
    """Mean seconds per page, resampled over documents."""
    pool = list(rows)
    if not pool:
        return Estimate(
            point=float("nan"), low=float("nan"), high=float("nan"), pages=0, documents=0
        )
    by_doc: dict[str, list[float]] = {}
    for r in pool:
        by_doc.setdefault(r.doc_id, []).append(r.seconds)
    point = float(np.mean([r.seconds for r in pool]))
    docs = list(by_doc)
    if len(docs) < 2:
        return Estimate(
            point=point, low=float("nan"), high=float("nan"), pages=len(pool), documents=len(docs)
        )
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(docs), size=(resamples, len(docs)))
    values = [by_doc[d] for d in docs]
    draws = np.empty(resamples)
    for draw in range(resamples):
        picked = [v for i in idx[draw] for v in values[i]]
        draws[draw] = float(np.mean(picked)) if picked else np.nan
    low, high = np.nanpercentile(draws, [2.5, 97.5])
    return Estimate(
        point=point, low=float(low), high=float(high), pages=len(pool), documents=len(docs)
    )


@dataclass(frozen=True, slots=True)
class Study:
    arms: dict[str, Estimate]
    rows: tuple[Timed, ...]
    # Pages a reviewer completed that carry no timing, counted from the audit log. A page
    # completed after a restart has no served-at stamp and is not guessed at. Zero when no
    # audit log was given, which is also when the number is unknown rather than known to be
    # zero, so the table says which case it is in.
    completed_pages: int | None = None

    @property
    def untimed(self) -> int | None:
        if self.completed_pages is None:
            return None
        return max(self.completed_pages - len(self.rows), 0)

    @property
    def has_both_arms(self) -> bool:
        return {"proposals", "unaided"} <= set(self.arms)

    @property
    def comparable(self) -> bool:
        """Both arms present, and each one resting on enough documents to be reported."""
        return self.has_both_arms and all(
            self.arms[a].documents >= MINIMUM_DOCUMENTS for a in ("proposals", "unaided")
        )

    @property
    def speedup(self) -> float:
        """How many times faster the aided arm is. Greater than one means the tool helped."""
        if not self.has_both_arms:
            return float("nan")
        aided = self.arms["proposals"].point
        return self.arms["unaided"].point / aided if aided else float("nan")

    def to_markdown(self) -> str:
        if not self.rows:
            lines = [
                "No review sessions have been timed yet.",
                "",
                "This is the one measurement in the definition of done that a program cannot "
                "produce: it needs a person to review the same records twice, once with the "
                "tool's proposals and once without them. `sever review --mode proposals` and "
                "`sever review --mode unaided` record the timings, and this table fills in "
                "from `review/timings.jsonl`.",
            ]
            return "\n".join(lines)
        lines = [
            "| Arm | Seconds per page | Minutes per page | Pages per hour | Pages | Documents |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for name in ("proposals", "unaided"):
            e = self.arms.get(name)
            if e is None:
                lines.append(f"| {name} | not collected | | | | |")
                continue
            lines.append(
                f"| {name} | {e} | {e.minutes:.1f} | {e.pages_per_hour:.0f} | "
                f"{e.pages} | {e.documents} |"
            )
        lines.append("")
        if self.untimed:
            lines.append(
                f"**{self.untimed} completed page(s) carry no timing** and are not in the "
                f"table above. A page completed after the server restarted has no "
                f"served-at stamp, and a missing measurement is recorded as missing rather "
                f"than estimated."
            )
            lines.append("")
        elif self.completed_pages is None:
            lines.append(
                "How many completed pages went untimed is not known here: pass the audit "
                "log to `sever eval-reviewer --audit` and it is counted."
            )
            lines.append("")
        if self.comparable:
            lines.append(
                f"The proposals arm is **{self.speedup:.1f} times** the speed of the unaided "
                f"arm on this evidence."
            )
        elif self.has_both_arms:
            lines.append(
                f"Both arms have been started but neither has reached {MINIMUM_DOCUMENTS} "
                f"documents, so no ratio is reported. What is above is what has been "
                f"collected, not a result."
            )
        else:
            missing = sorted({"proposals", "unaided"} - set(self.arms))
            lines.append(
                f"Only one arm has been run, so there is nothing to compare. Missing: "
                f"{', '.join(missing)}."
            )
        lines += [
            "",
            "Intervals are 95 percent bootstrap percentile intervals resampled over "
            "documents rather than pages, because pages within a record are not "
            "independent: one record's density of third parties, and one reviewer's "
            "growing familiarity with its template, are single facts and not many.",
            "",
            "The unaided arm is served the same records with the proposals dropped before "
            "the session is built, so the reviewer finds and categorises every severance "
            "themselves. Highlighting the spans and hiding only the suggested category "
            "would measure how long it takes to agree with a highlight, which is not the "
            "question.",
        ]
        return "\n".join(lines)


def completed_from_audit(path: Path, request_id: str | None = None) -> int:
    """How many pages a reviewer marked complete, whatever the clock did.

    The audit log is the record of what was reviewed; the timings file is the record of
    what was measured. The difference between them is what this study could not see, and
    a study that cannot say how much it missed is not reporting, it is selecting.
    """
    from sever.review.audit import Action, AuditLog

    with AuditLog(path) as log:
        rows = log.rows(request_id=request_id)
        return sum(1 for r in rows if r.action is Action.PAGE_COMPLETE)


def run(
    paths: Sequence[Path] | None = None,
    *,
    audit: Path | None = None,
    request_id: str | None = None,
) -> Study:
    rows = read(list(paths) if paths is not None else [DEFAULT_TIMINGS])
    modes = sorted({r.mode for r in rows})
    completed = (
        completed_from_audit(audit, request_id) if audit is not None and audit.is_file() else None
    )
    return Study(
        arms={m: estimate([r for r in rows if r.mode == m]) for m in modes},
        rows=rows,
        completed_pages=completed,
    )


def write(study: Study, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!-- Generated by `sever eval-reviewer`. Do not hand-edit. -->\n\n"
        "# Reviewer minutes per page, with and without proposals\n\n"
        + study.to_markdown()
        + "\n",
        encoding="utf-8",
    )
    return path
