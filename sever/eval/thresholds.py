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

from dataclasses import dataclass
from pathlib import Path

from sever.corpus.generate import Corpus, build
from sever.decide.pipeline import DecisionEngine, ModelDecider
from sever.detect.engine import SeverDetector
from sever.detect.types import Detector
from sever.eval.confusion import Interval, score
from sever.eval.report import CachingDetector, config_for
from sever.taxonomy.loader import default_taxonomy

# Coarse on purpose. The intervals on 210 documents are still wide enough that a finer
# grid would be reporting noise as structure.
DEFAULT_THRESHOLDS: tuple[float, ...] = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.01)


@dataclass(frozen=True, slots=True)
class Row:
    threshold: float
    leak: Interval
    over: Interval
    escalation: Interval
    accepted: int
    offered: int

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
            for p in proposals:
                if p.rule in ("model", "below_threshold"):
                    offered += 1
                    if p.rule == "model":
                        accepted += 1
        scored = score(pool, taxonomy=taxonomy)  # type: ignore[arg-type]
        rows.append(
            Row(
                threshold=threshold,
                leak=scored.leak_rate(),
                over=scored.over_redaction_rate(),
                escalation=scored.escalation_rate(),
                accepted=accepted,
                offered=offered,
            )
        )

    summary = getattr(model, "spend_summary", None)
    return Sweep(
        rows=rows,
        documents=len(c),
        pages=c.page_count,
        model_name=str(getattr(model, "model", "unknown")),
        spend_note=str(summary()) if callable(summary) else "",
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
