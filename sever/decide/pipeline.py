"""Detection, context, rules, then the model on what is left. Redact and escalate when
neither is sure.

The proposal is the unit that leaves this package. It carries the code, the decision the
taxonomy attaches to that code, the provisions, a sentence of explanation and where the
decision came from. Everything downstream (the reviewer app, the export, the schedule, the
evaluation) reads proposals and nothing else.

The safety property this module is responsible for is stated once, here, and asserted in
the tests: no path through `propose` releases a span that no rule and no model decided.
The fallthrough is E1, E1 is an escalate code, and an escalate code withholds.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol, runtime_checkable

from sever.context.record import SENTENCE_ONLY_BLANKS, ContextBuilder, ContextRecord
from sever.context.register import PublicRegister
from sever.context.requester import RequestConfig
from sever.decide import rules as rules_mod
from sever.detect.engine import SeverDetector
from sever.detect.types import Detection, Detector
from sever.ingest.document import Document
from sever.taxonomy.loader import Decision, Provision, Taxonomy, default_taxonomy

# Below this confidence a model answer is discarded and the span is escalated instead.
#
# 0.90, and it is measured rather than chosen. `sever eval-thresholds` sweeps it against
# one recorded set of model answers, so every row is the same answers read again rather
# than a fresh run of a system that varies; `results/thresholds.md` is the table and it is
# reproducible from the committed answer cache without a gateway.
#
# The curve is not smooth and that is the finding. Between 0.00 and 0.70 the published
# numbers do not move at all, even though acceptance falls from 100 percent to 66: the
# answers dropped in that range are the ones where the model itself said E1, and an
# escalation discarded for low confidence and an escalation the model asked for are the
# same decision. The threshold only starts doing work at 0.90, where the leak rate falls
# from 13.4 percent to 7.9 and over-redaction rises from 15.6 to 22.7. Above 0.90 it is
# flat again: 0.95 moves nothing, because the model almost never answers between the two.
#
# That shape says something about the model as much as about the threshold. Haiku 4.5
# reports its confidence in a handful of clusters rather than on a continuum, so this is a
# switch with one useful position rather than a dial.
#
# The reason it sits at the withholding end of that switch is the rule in CLAUDE.md:
# withhold and escalate when unsure. Releasing a third party's information cannot be
# undone; an escalation costs a reviewer a minute.
DEFAULT_THRESHOLD = 0.90


class Source(StrEnum):
    RULE = "rule"
    MODEL = "model"
    FALLTHROUGH = "fallthrough"
    BASELINE = "baseline"


@dataclass(frozen=True, slots=True)
class Proposal:
    """What the tool proposes for one span, and why."""

    detection: Detection
    code: str
    decision: Decision
    confidence: float
    reason: str
    source: Source
    rule: str | None = None
    provisions: tuple[Provision, ...] = ()
    # Set when the rules and the model disagreed. The proposal is then the safe one and
    # the reviewer sees both answers, because a disagreement is information.
    disagreement: str | None = None

    @property
    def page(self) -> int:
        return self.detection.page

    @property
    def withholds(self) -> bool:
        return self.decision.withholds

    @property
    def is_escalation(self) -> bool:
        return self.decision in (Decision.ESCALATE,)

    @property
    def key(self) -> tuple[int, int, int]:
        return self.detection.key

    @property
    def citation(self) -> str:
        if not self.provisions:
            return ""
        return "; ".join(f"s. {p.section}" for p in self.provisions)


@dataclass(frozen=True, slots=True)
class DocumentProposals:
    document: Document
    proposals: tuple[Proposal, ...]
    contexts: tuple[ContextRecord, ...] = ()

    def __iter__(self) -> Iterator[Proposal]:
        return iter(self.proposals)

    def __len__(self) -> int:
        return len(self.proposals)

    def on_page(self, page: int) -> tuple[Proposal, ...]:
        return tuple(p for p in self.proposals if p.page == page)

    @property
    def withheld(self) -> tuple[Proposal, ...]:
        return tuple(p for p in self.proposals if p.withholds)

    @property
    def escalations(self) -> tuple[Proposal, ...]:
        return tuple(p for p in self.proposals if p.is_escalation)

    def by_code(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self.proposals:
            out[p.code] = out.get(p.code, 0) + 1
        return dict(sorted(out.items()))


@runtime_checkable
class ModelDecider(Protocol):
    """The interface the model layer satisfies. See sever.decide.model.

    An actual Protocol rather than a base class, so that nothing in this module imports
    anything that can make a network call: the rules-only pipeline is a published baseline
    and runs in CI, and it should not be able to reach a gateway even by accident.
    """

    name: str

    def decide(
        self,
        contexts: Sequence[ContextRecord],
        *,
        universe: Sequence[ContextRecord] = (),
    ) -> Sequence[rules_mod.RuleOutcome | None]:
        """Decide `contexts`. `universe` is every context in the document, which the
        implementation needs in order to build a placeholder policy that covers the
        entities appearing *around* the spans being sent, not only the spans themselves."""
        ...


@dataclass
class DecisionEngine:
    """The pipeline. Construct once per request, run over every document."""

    config: RequestConfig
    detector: Detector = field(default_factory=SeverDetector)
    register: PublicRegister = field(default_factory=PublicRegister)
    taxonomy: Taxonomy = field(default_factory=default_taxonomy)
    rules: Sequence[rules_mod.Rule] = rules_mod.DEFAULT_RULES
    model: ModelDecider | None = None
    # Below this, a model answer is not trusted and the span is escalated instead.
    model_confidence_threshold: float = DEFAULT_THRESHOLD
    # Blank the document context before deciding. The sentence-only baseline.
    sentence_only: bool = False

    def contexts_for(self, document: Document) -> tuple[ContextRecord, ...]:
        detections = tuple(self.detector.detect(document))
        builder = ContextBuilder(config=self.config, register=self.register)
        contexts = builder.build(document, detections)
        if self.sentence_only:
            contexts = tuple(c.blanked(*SENTENCE_ONLY_BLANKS) for c in contexts)
        return contexts

    def propose(self, document: Document) -> DocumentProposals:
        contexts = self.contexts_for(document)
        rule_results = [rules_mod.apply(c, self.rules) for c in contexts]

        model_answers: list[rules_mod.RuleOutcome | None] = [None] * len(contexts)
        if self.model is not None:
            residual = [i for i, r in enumerate(rule_results) if not r.decided_by_rule]
            if residual:
                answers = self.model.decide(
                    [contexts[i] for i in residual], universe=contexts
                )
                for i, answer in zip(residual, answers, strict=True):
                    model_answers[i] = answer

        proposals = tuple(
            self._combine(ctx, result, answer)
            for ctx, result, answer in zip(contexts, rule_results, model_answers, strict=True)
        )
        return DocumentProposals(document=document, proposals=proposals, contexts=contexts)

    def _combine(
        self,
        ctx: ContextRecord,
        result: rules_mod.RuleResult,
        model: rules_mod.RuleOutcome | None,
    ) -> Proposal:
        if result.decided_by_rule and model is None:
            return self._proposal(ctx, result.outcome, Source.RULE)
        if model is None:
            return self._proposal(ctx, result.outcome, Source.FALLTHROUGH)
        if model.confidence < self.model_confidence_threshold:
            escalated = rules_mod.RuleOutcome(
                code="E1",
                confidence=model.confidence,
                reason=(
                    f"The model proposed {model.code} at {model.confidence:.2f}, below the "
                    f"{self.model_confidence_threshold:.2f} threshold. Withheld and referred. "
                    f"Its reasoning: {model.reason}"
                ),
                rule="below_threshold",
            )
            return self._proposal(ctx, escalated, Source.MODEL)
        if result.decided_by_rule and result.outcome.code != model.code:
            safe = result.outcome if _is_safer(result.outcome.code, model.code) else model
            escalated = rules_mod.RuleOutcome(
                code="E1" if safe.code.startswith("K") else safe.code,
                confidence=min(result.outcome.confidence, model.confidence),
                reason=(
                    f"The rules proposed {result.outcome.code} and the model proposed "
                    f"{model.code}. Withheld and referred rather than resolved silently. "
                    f"Rules: {result.outcome.reason} Model: {model.reason}"
                ),
                rule="rules_model_disagreement",
            )
            return replace(
                self._proposal(ctx, escalated, Source.MODEL),
                disagreement=f"rules={result.outcome.code} model={model.code}",
            )
        return self._proposal(ctx, model, Source.MODEL)

    def _proposal(
        self, ctx: ContextRecord, outcome: rules_mod.RuleOutcome, source: Source
    ) -> Proposal:
        decision = self.taxonomy.decision(outcome.code)
        return Proposal(
            detection=ctx.detection,
            code=outcome.code,
            decision=decision,
            confidence=outcome.confidence,
            reason=outcome.reason,
            source=source,
            rule=outcome.rule,
            provisions=self.taxonomy.provisions(outcome.code, self.config.jurisdiction),
        )


def _is_safer(a: str, b: str) -> bool:
    """True when code `a` withholds and `b` does not. Used only to pick which reasoning to
    surface first on a disagreement; the proposal itself is always the withholding one."""
    return a[0] in "RE" and b[0] == "K"


def blunt_baseline(
    document: Document,
    detector: Detector,
    taxonomy: Taxonomy | None = None,
    jurisdiction: str = "federal",
) -> DocumentProposals:
    """Redact every detected span. The baseline this project exists to beat on the
    must-keep column, and the one it will not beat on leak rate."""
    t = taxonomy or default_taxonomy()
    proposals = tuple(
        Proposal(
            detection=d,
            code="R1",
            decision=Decision.REDACT,
            confidence=1.0,
            reason="Blunt baseline: every detected entity is redacted.",
            source=Source.BASELINE,
            rule="blunt",
            provisions=t.provisions("R1", jurisdiction),
        )
        for d in detector.detect(document)
    )
    return DocumentProposals(document=document, proposals=proposals)
