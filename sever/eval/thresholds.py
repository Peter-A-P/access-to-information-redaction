"""What the model's confidence threshold is worth, measured rather than chosen.

`DecisionEngine.model_confidence_threshold` was a number somebody picked: 0.7, with a
comment admitting it was a starting value. This module replaces the comment with a curve.

The threshold is applied to an answer that has already come back, so a sweep needs the
same answers read again rather than new ones. `GatewayModelDecider.cache_path` makes that
exact: one paid run fills the cache, and every threshold after it is free and is scored
against identical model output. Without the cache a sweep would be several runs of a
non-deterministic system compared against each other, which measures the model's variance
as much as the threshold.

What the curve is for. A threshold trades the two errors against each other in opposite
directions, and they are not symmetric:

  * Raising it sends more of the model's answers back to escalation. Over-redaction and
    escalation rise, the leak rate falls, and the cost is a reviewer's time.
  * Lowering it accepts more answers. Over-redaction falls, and the leak rate rises, and
    the cost is a third party's personal information in a released record.

So the right threshold is not the one that minimises total error. It is the lowest one
whose leak rate is still acceptable, and this module prints both columns beside each other
so that the choice is made in front of the reader rather than in a default argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sever.corpus.generate import Corpus, build
from sever.decide.pipeline import DecisionEngine, ModelDecider, default_threshold_for
from sever.detect.engine import SeverDetector
from sever.detect.types import Detector
from sever.eval.confusion import Interval, Scored, score
from sever.eval.report import CachingDetector, config_for
from sever.taxonomy.loader import default_taxonomy

# Coarse on purpose. The intervals on 210 documents are still wide enough that a finer
# grid would be reporting noise as structure.
DEFAULT_THRESHOLDS: tuple[float, ...] = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.01)
# Accepts no answer, so it is the rules alone. The selection rule compares against it.
RULES_ONLY = 1.01
# The splits the selection rule reads and is then scored on (PLAN.md 2.2).
SELECT_ON, SCORE_ON = "validation", "test"


@dataclass(frozen=True, slots=True)
class SplitScore:
    leaks: int
    leak: Interval
    over: Interval


def _split_score(scored: Scored) -> SplitScore:
    return SplitScore(
        leaks=sum(1 for o in scored.outcomes if o.is_leak),
        leak=scored.leak_rate(),
        over=scored.over_redaction_rate(),
    )


@dataclass(frozen=True, slots=True)
class Row:
    threshold: float
    leak: Interval
    over: Interval
    escalation: Interval
    accepted: int
    offered: int
    # The same answers scored on one split at a time, for the selection rule.
    by_split: dict[str, SplitScore] = field(default_factory=dict)

    @property
    def accepted_share(self) -> float:
        return self.accepted / self.offered if self.offered else 0.0


@dataclass
class Sweep:
    rows: list[Row]
    documents: int
    pages: int
    model_name: str
    spend_note: str
    # What the tool runs this model at when nobody says otherwise. Reported beside the
    # threshold the rule picks, because the two need not be the same and here are not.
    running: float | None = None

    def selected(self) -> Row | None:
        """The rule fixed before looking (PLAN.md 2.4): the lowest threshold at which the
        model adds no leak over the rules alone on the validation split."""
        rules = next((r for r in self.rows if r.threshold >= RULES_ONLY), None)
        if rules is None or SELECT_ON not in rules.by_split:
            return None
        floor = rules.by_split[SELECT_ON].leaks
        return next(
            (
                r
                for r in sorted(self.rows, key=lambda r: r.threshold)
                if SELECT_ON in r.by_split and r.by_split[SELECT_ON].leaks <= floor
            ),
            None,
        )

    def selection_markdown(self) -> list[str]:
        chosen = self.selected()
        rules = next((r for r in self.rows if r.threshold >= RULES_ONLY), None)
        if chosen is None or rules is None or SCORE_ON not in chosen.by_split:
            return []
        lines = [
            "",
            "**The threshold rule, fixed before looking.** The lowest threshold at which the "
            f"model adds no leak over the rules alone on the {SELECT_ON} split "
            f"({rules.by_split[SELECT_ON].leaks} leaks with the rules alone there) picks "
            f"`{chosen.threshold:.2f}`. Scored once on the {SCORE_ON} split:",
            "",
            f"| On the {SCORE_ON} split | Leak rate | Over-redaction |",
            "|---|---|---|",
            f"| the rules alone | {rules.by_split[SCORE_ON].leak} | "
            f"{rules.by_split[SCORE_ON].over} |",
            f"| `{chosen.threshold:.2f}`, the threshold the rule picked (the reported result) "
            f"| {chosen.by_split[SCORE_ON].leak} | {chosen.by_split[SCORE_ON].over} |",
        ]
        running = next(
            (r for r in self.rows if self.running is not None and abs(r.threshold - self.running) < 1e-9),
            None,
        )
        if running is not None and running is not chosen and SCORE_ON in running.by_split:
            lines.append(
                f"| `{running.threshold:.2f}`, the threshold the tool runs at, chosen after "
                f"the {SCORE_ON} split was seen | {running.by_split[SCORE_ON].leak} | "
                f"{running.by_split[SCORE_ON].over} |"
            )
        return lines

    def to_markdown(self) -> str:
        lines = [
            f"**Corpus:** {self.documents} documents, {self.pages} pages. "
            f"Model: {self.model_name}. {self.spend_note}.",
            "",
            "| Confidence threshold | Model answers accepted | Leak rate | "
            "Over-redaction | Escalation |",
            "|---|---:|---|---|---|",
        ]
        for r in self.rows:
            label = f"`{r.threshold:.2f}`"
            if r.threshold <= 0.0:
                label += " (accept every answer)"
            elif r.threshold > 1.0:
                label += " (accept none: rules only)"
            lines.append(
                f"| {label} | {r.accepted}/{r.offered} ({r.accepted_share:.0%}) | "
                f"{r.leak} | {r.over} | {r.escalation} |"
            )
        lines += self.selection_markdown()
        return "\n".join(lines)


def sweep(
    model: ModelDecider,
    *,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    documents: int = 210,
    seed: int = 20270802,
    detector: Detector | None = None,
    corpus: Corpus | None = None,
) -> Sweep:
    """Score the corpus once per threshold against one set of model answers.

    The detector is cached across every pass, so the only work repeated per threshold is
    the rules and the scoring. The model is asked for each span once and every later pass
    replays it from the answer cache, which is what makes the rows comparable.
    """
    det = CachingDetector(inner=detector or SeverDetector())
    c = corpus or build(documents=documents, seed=seed)
    taxonomy = default_taxonomy()
    rows: list[Row] = []

    for threshold in thresholds:
        pool: dict[str, tuple[object, object]] = {}
        split_of: dict[str, str] = {}
        accepted = offered = 0
        for item in c:
            doc = item.rendered.document
            proposals = DecisionEngine(
                config=config_for(item),
                detector=det,
                taxonomy=taxonomy,
                model=model,
                model_confidence_threshold=threshold,
            ).propose(doc)
            pool[doc.doc_id] = (proposals, item.rendered.labels)
            split_of[doc.doc_id] = c.split.get(doc.doc_id, "")
            for p in proposals:
                if p.rule in ("model", "below_threshold", "own_affairs_model_release"):
                    offered += 1
                    if p.rule == "model":
                        accepted += 1
        scored = score(pool, taxonomy=taxonomy)  # type: ignore[arg-type]
        by_split = {
            name: _split_score(
                score(
                    {k: v for k, v in pool.items() if split_of[k] == name},  # type: ignore[misc]
                    taxonomy=taxonomy,
                )
            )
            for name in (SELECT_ON, SCORE_ON)
            if name in split_of.values()
        }
        rows.append(
            Row(
                threshold=threshold,
                leak=scored.leak_rate(),
                over=scored.over_redaction_rate(),
                escalation=scored.escalation_rate(),
                accepted=accepted,
                offered=offered,
                by_split=by_split,
            )
        )

    summary = getattr(model, "spend_summary", None)
    return Sweep(
        rows=rows,
        documents=len(c),
        pages=c.page_count,
        model_name=str(getattr(model, "model", "unknown")),
        spend_note=str(summary()) if callable(summary) else "",
        running=default_threshold_for(model),
    )


def write(result: Sweep, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!-- Generated by `sever eval-thresholds`. Do not hand-edit. -->\n\n"
        "# The model confidence threshold, swept\n\n"
        + result.to_markdown()
        + "\n",
        encoding="utf-8",
    )
    return path
