"""Four model layers on one fixed sample of the residual: does the stated probability mean anything?

The threshold sweep (`sever.eval.thresholds`) answers what a threshold does to the published
rates. It does not answer the question the decision models were brought in for (PLAN.md
12.48): when a model says 0.8, is it right about 80 percent of the time? That needs the
model's own answer set beside the truth, span by span, for each model on the same spans, and
for a model that cannot be run over the whole corpus (Kev-0.8B on a laptop processor, about
20 seconds a request) a sample small enough to finish.

**The sample** is `data/decision-sample.json`: a simple random 150 of the 449 spans the rules
left to a model on the validation split, seed 20261020, drawn on 2026-10-20 on the code at
a0fdc88, before the personal-contact rule (ab37c1c). Random rather than chosen for failure, so
its accuracy and calibration estimate the residual's. Frozen as a file because a later rule
changes the residual, and a redrawn sample would no longer match the answers recorded for
it. A span a later rule now decides never reaches a model and drops out of every column alike.

**The truth** is the label overlapping the detection most, or, where no label overlaps, not
personal information, which a correct answer releases under any keep code.

**What is scored** is each model's own answer, not the pipeline's proposal: right code;
accepted (at or above the threshold, and not an escalate code, since E1 and E2 are the model
declining); a leak (must-withhold truth, accepted keep); and a must-keep span withheld (keep
truth, and the answer refused, escalated, or not keep). Replay only: every answer comes from
a committed cache, and a span a cache does not hold is reported as unanswered, never sent.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sever.context.record import ContextRecord
from sever.corpus.generate import build
from sever.corpus.labels import LabelSet
from sever.corpus.personas import PUBLIC_BODY_DOMAIN
from sever.decide.decision_model import DecisionModelDecider
from sever.decide.model import GatewayModelDecider, ModelUnavailable
from sever.decide.pipeline import DecisionEngine
from sever.decide.rules import RuleOutcome
from sever.detect.engine import SeverDetector
from sever.eval.confusion import Interval, clustered_rate
from sever.eval.report import CachingDetector, config_for
from sever.ingest.document import Document
from sever.taxonomy.loader import Decision, Taxonomy, default_taxonomy

DEFAULT_SAMPLE = Path("data/decision-sample.json")
NOT_PERSONAL = "none"
THRESHOLDS: tuple[float, ...] = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9)
BINS: tuple[tuple[float, float], ...] = (
    (0.0, 0.3),
    (0.3, 0.5),
    (0.5, 0.7),
    (0.7, 0.9),
    (0.9, 1.01),
)

Key = tuple[str, int, int, int]  # doc_id, page, start, end


@dataclass(frozen=True, slots=True)
class SampleModel:
    """One model layer, read from its committed answer cache."""

    label: str
    model: str
    cache: Path
    decision_model: bool
    note: str


# The four the project has answers for. Kev-0.8B was served on this laptop's processor
# (`kev.serve --run jaredpalmer/kev-0.8b`, fp32) under 04's `kev` entry, whose model id is
# the same for every Kev size, so its cache file carries the size in its name.
MODELS: tuple[SampleModel, ...] = (
    SampleModel(
        "Haiku 5.5",
        "anthropic/claude-haiku-5-5",
        Path("results/model-answers.jsonl"),
        False,
        "language model, stated confidence",
    ),
    SampleModel(
        "Jev 1.14",
        "openrouter/typesafe/jev-1.14",
        Path("results/model-answers-jev.jsonl"),
        True,
        "TypeSafe, through OpenRouter",
    ),
    SampleModel(
        "Kev 4B",
        "openrouter/jaredpalmer/kev-4b",
        Path("results/model-answers-kev.jsonl"),
        True,
        "open weights, through OpenRouter (Phala)",
    ),
    SampleModel(
        "Kev 0.8B",
        "kev/kev-latest",
        Path("results/model-answers-kev-0.8b.jsonl"),
        True,
        "open weights, this laptop's processor, fp32",
    ),
)


@dataclass(frozen=True, slots=True)
class SampleAnswer:
    doc_id: str
    gold: str
    code: str | None
    p: float


@dataclass(frozen=True, slots=True)
class ThresholdRow:
    threshold: float
    accepted: int
    right: int
    leaks: int
    keep_withheld: int


@dataclass(frozen=True, slots=True)
class ModelScore:
    model: SampleModel
    answered: int
    accuracy: Interval
    bins: tuple[tuple[float, float, int, float], ...]  # low, high, n, share right
    rows: tuple[ThresholdRow, ...]
    must_keep: int


def load_sample(path: Path = DEFAULT_SAMPLE) -> dict[Key, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        (str(r["key"][0]), int(r["key"][1]), int(r["key"][2]), int(r["key"][3])): str(r["gold"])
        for r in data["spans"]
    }


def _key(ctx: ContextRecord) -> Key:
    d = ctx.detection
    return (ctx.doc_id, d.page, d.offsets.start, d.offsets.end)


def gold_code(ctx: ContextRecord, labels: LabelSet) -> str:
    """The label overlapping the detection most, or NOT_PERSONAL."""
    d = ctx.detection
    best, overlap = NOT_PERSONAL, 0
    for s in labels.spans:
        if s.page != d.page:
            continue
        o = min(s.offsets.end, d.offsets.end) - max(s.offsets.start, d.offsets.start)
        if o > overlap:
            best, overlap = s.code, o
    return best


@dataclass
class _Recorder:
    """Asks the inner decider one sampled span at a time and records what it said.

    One span per call is the same request as the batch would send: the placeholder policy
    is built from `universe` and the page from `document`, neither from the batch. Spans
    outside the sample are not asked and stay escalated, which the recorder does not score.
    """

    inner: GatewayModelDecider
    sample: dict[Key, str]
    answers: dict[Key, RuleOutcome | None]
    name: str = "sample-recorder"

    def decide(
        self,
        contexts: Sequence[ContextRecord],
        *,
        universe: Sequence[ContextRecord] = (),
        document: Document | None = None,
    ) -> Sequence[RuleOutcome | None]:
        for c in contexts:
            k = _key(c)
            if k not in self.sample:
                continue
            try:
                (outcome,) = self.inner.decide(
                    [c], universe=universe or contexts, document=document
                )
            except ModelUnavailable:
                continue
            self.answers[k] = outcome
        return [None] * len(contexts)


def collect(model: SampleModel, sample: dict[Key, str]) -> list[SampleAnswer]:
    """The model's cached answers on the sample, replay only. Nothing is sent."""
    cls = DecisionModelDecider if model.decision_model else GatewayModelDecider
    inner = cls(
        gateway=None,
        model=model.model,
        enabled=True,
        run_id="decision-sample",
        cache_path=model.cache,
        replay_only=True,
        public_body_domains=(PUBLIC_BODY_DOMAIN,),
    )
    answers: dict[Key, RuleOutcome | None] = {}
    recorder = _Recorder(inner=inner, sample=sample, answers=answers)
    corpus = build(documents=210, seed=20270802)
    det = CachingDetector(inner=SeverDetector())
    taxonomy = default_taxonomy()
    docs = {k[0] for k in sample}
    for item in corpus.of_split("validation"):
        if item.doc_id not in docs:
            continue
        DecisionEngine(
            config=config_for(item),
            detector=det,
            taxonomy=taxonomy,
            model=recorder,
            model_confidence_threshold=0.0,
        ).propose(item.rendered.document)
    return [
        SampleAnswer(
            doc_id=k[0], gold=sample[k], code=o.code if o else None, p=o.confidence if o else 0.0
        )
        for k, o in sorted(answers.items())
    ]


def score_answers(
    model: SampleModel, answers: Sequence[SampleAnswer], taxonomy: Taxonomy | None = None
) -> ModelScore:
    tax = taxonomy or default_taxonomy()

    def decision(code: str | None) -> Decision | None:
        if code is None:
            return None
        return Decision.KEEP if code == NOT_PERSONAL else tax.decision(code)

    def right(a: SampleAnswer) -> bool:
        if a.gold == NOT_PERSONAL:
            return decision(a.code) is Decision.KEEP
        return a.code == a.gold

    def accepted(a: SampleAnswer, t: float) -> bool:
        return a.code is not None and a.p >= t and decision(a.code) is not Decision.ESCALATE

    rows = []
    for t in THRESHOLDS:
        acc = [a for a in answers if accepted(a, t)]
        rows.append(
            ThresholdRow(
                threshold=t,
                accepted=len(acc),
                right=sum(right(a) for a in acc),
                leaks=sum(
                    decision(a.gold) is Decision.REDACT and decision(a.code) is Decision.KEEP
                    for a in acc
                ),
                keep_withheld=sum(
                    decision(a.gold) is Decision.KEEP
                    and not (accepted(a, t) and decision(a.code) is Decision.KEEP)
                    for a in answers
                ),
            )
        )
    bins = []
    for lo, hi in BINS:
        b = [a for a in answers if lo <= a.p < hi]
        bins.append((lo, min(hi, 1.0), len(b), sum(right(a) for a in b) / len(b) if b else 0.0))
    return ModelScore(
        model=model,
        answered=len(answers),
        accuracy=clustered_rate(answers, right),
        bins=tuple(bins),
        rows=tuple(rows),
        must_keep=sum(decision(a.gold) is Decision.KEEP for a in answers),
    )


def run(sample_path: Path = DEFAULT_SAMPLE) -> tuple[int, list[ModelScore]]:
    sample = load_sample(sample_path)
    return len(sample), [score_answers(m, collect(m, sample)) for m in MODELS]


def to_markdown(sampled: int, scores: Sequence[ModelScore]) -> str:
    lines = [
        f"**Sample:** {sampled} spans drawn at random from the 449 the rules left to a model on "
        f"the validation split (`data/decision-sample.json`, seed 20261020). Each model's own "
        f"answer, replayed from its committed cache; nothing spent. Interval: 95 percent, "
        f"resampled over documents.",
        "",
        "| Model | Answered | Right code | Kept spans in the sample |",
        "|---|---:|---|---:|",
    ]
    for s in scores:
        lines.append(
            f"| {s.model.label} ({s.model.note}) | {s.answered} | {s.accuracy} | {s.must_keep} |"
        )
    lines += ["", "**Calibration: share right, by the probability the model stated**", ""]
    lines.append("| Stated | " + " | ".join(s.model.label for s in scores) + " |")
    lines.append("|---|" + "---|" * len(scores))
    for i, (lo, hi, *_rest) in enumerate(scores[0].bins):
        cells = []
        for s in scores:
            _, _, n, share = s.bins[i]
            cells.append(f"{share:.0%} of {n}" if n else "none")
        lines.append(f"| {lo:.1f} to {hi:.1f} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "**What each threshold accepts.** Accepted: at or above the threshold and not an "
        "escalate code. Leaks: must-withhold spans accepted as keep. Kept withheld: must-keep "
        "spans refused, escalated, or answered as withhold.",
        "",
        "| Threshold | "
        + " | ".join(f"{s.model.label}: accepted, right, leaks, kept withheld" for s in scores)
        + " |",
        "|---|" + "---|" * len(scores),
    ]
    for i, t in enumerate(THRESHOLDS):
        cells = [
            f"{r.accepted}, {r.right}, {r.leaks}, {r.keep_withheld}"
            for r in (s.rows[i] for s in scores)
        ]
        lines.append(f"| `{t:.2f}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write(sampled: int, scores: Sequence[ModelScore], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!-- Generated by `sever eval-sample`. Do not hand-edit. -->\n\n"
        "# Four model layers on one sample of the residual\n\n"
        + to_markdown(sampled, scores)
        + "\n",
        encoding="utf-8",
    )
    return path
