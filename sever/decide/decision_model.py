"""The residual decided by a decision model: Jev through OpenRouter, or Kev on this machine.

A decision model takes a state and a question with named options and returns a
probability for every option, and no text. That is the shape of this project's question
exactly: given the masked record, which category is this span? And it is aimed at the
weakness the language model showed. With Claude Haiku 5.5 the confidence threshold threw
away 476 correct answers for every two leaks it prevented, because the model reported 0.80
or 0.85 whether it was right or wrong (docs/rejected.md section 7). TypeSafe states that
Jev's probabilities are calibrated: a 0.8 is right about 80 percent of the time. Whether
that holds here is what the validation split is for.

What is the same as the language model, and deliberately so:

  * **The evidence.** The state is the request the language model is given, field for field:
    the context record on placeholders, the whole page masked, the requester's placeholder.
    It is built by `GatewayModelDecider.build_request`, so it passes the same guard, and
    nothing reaches the decision model that the language model would not have been sent.
  * **The path.** Through the 04 gateway with data class `personal`, which since boundary
    1.5 has a `decisions` provider kind for exactly this interface.
  * **The answer cache.** Keyed by the model, the question and the state, so a run is
    replayed for nothing and the threshold is swept over one set of answers.

What differs:

  * **No "cannot tell" option.** The language model is offered E1 because it has no other way
    to say it is unsure. A calibrated model says so with its probabilities: a span is
    escalated when the probability of the category it chose is below the threshold. The
    options are the categories the tool decides, R1 to K7 and E2 (a mixed span is a real
    category, not a shrug). E1 and E3 are not offered: E1 is what a low probability means,
    and E3 is an exemption this tool does not decide.
  * **No stated reason.** The model writes nothing, so the redaction schedule's reason for a
    decided span is the probability and the runner-up, and the evidence a reviewer reads is
    the context record's own, as it is for a rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, ClassVar

from sever.context.record import ContextRecord
from sever.decide.model import GatewayModelDecider, PageView
from sever.decide.placeholders import PlaceholderPolicy, scrub_unrecognised
from sever.decide.rules import RuleOutcome

DEFAULT_DECISION_MODEL = "openrouter/typesafe/jev-1.14"
KEV_MODEL = "kev/kev-latest"
# Providers in 04's configuration whose kind is `decisions`. The CLI reads a model id
# against this to choose the decider, rather than guessing from the model's name.
DECISION_PROVIDERS = frozenset({"openrouter", "kev"})

# The threshold the tool runs a decision model at, chosen on 2026-10-20 and deliberately
# not the one reported. The rule fixed before looking (the lowest threshold at which the
# model adds no leak over the rules alone, on the validation split) picked 0.00 for Jev
# 1.14 once the personal-contact rule existed, and the test split confirmed it: no leak
# added, over-redaction 1.1 percent. That is the reported result. Accepting every answer
# would leave the model never unsure, against this repository's rule that an undecided
# span is withheld and escalated, so the tool escalates Jev's coin flips: below 0.60 its
# answer goes to the reviewer, at 0.5 points of over-redaction. PLAN.md 12.50.
DEFAULT_DECISION_THRESHOLD = 0.60

QUESTION_ID = "category"
# Codes offered as options. See the module docstring for why E1 and E3 are not.
NOT_OFFERED = frozenset({"E1", "E3"})

INSTRUCTIONS = (
    "The state is one span in a government record that an access-to-information analyst is "
    "deciding whether to withhold or release, with the whole page it sits on. Every person, "
    "address, identifier and contact detail is replaced by a typed placeholder, the same "
    "placeholder wherever the same person appears, so decide from who the page shows each "
    "person to be, not from names. `span` is the text being decided. "
    "`is_configured_requester` true, or a span belonging to `requester_placeholder`, means "
    "the person who made the request. An email placeholder written [EMAIL_PUBLIC_BODY_n] is "
    "on the public body's own domain. Which category is the span?"
)


def is_decision_model(model: str) -> bool:
    """Whether a gateway model id names a decision model, by its provider entry."""
    provider, _, _ = model.partition("/")
    return provider in DECISION_PROVIDERS


@dataclass
class DecisionModelDecider(GatewayModelDecider):
    """`GatewayModelDecider` with the request and the reply reshaped for a decision model."""

    model: str = DEFAULT_DECISION_MODEL
    # A decision model takes neither; sent, they would be refused by the 04 adapter.
    temperature: float | None = None
    effort: str | None = None
    name: str = "decision-model"
    # What `DecisionEngine` runs this decider at when no threshold is given.
    default_threshold: ClassVar[float] = DEFAULT_DECISION_THRESHOLD
    _question: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self._question = {
            QUESTION_ID: {
                "type": "choice",
                "instructions": INSTRUCTIONS,
                "criteria": self._criteria(),
            }
        }

    def _criteria(self) -> dict[str, str]:
        """Each offered code, described as the reviewers' reference card describes it.

        The examples go through the name scrub, as they do in the language model's guide,
        because they use invented names and an invented name can be a real person's.
        """
        out: dict[str, str] = {}
        for c in self.taxonomy.categories:
            if c.code in NOT_OFFERED:
                continue
            parts = [f"{c.name}. {' '.join(c.definition.split())}"]
            parts += [f"Example: {scrub_unrecognised(' '.join(e.split()))}" for e in c.examples]
            parts += [f"Trap: {' '.join(t.split())}" for t in c.traps]
            out[c.code] = " ".join(parts)
        return out

    @property
    def system_prompt(self) -> str:
        """The question, as canonical JSON. Not sent as a system prompt, which a decision
        model does not take; it is what the answer cache keys on in its place, so a change
        to the question or to a category's text is a new answer, not a replayed one."""
        return json.dumps(self._question, sort_keys=True, ensure_ascii=False)

    def build_request(
        self,
        ctx: ContextRecord,
        policy: PlaceholderPolicy,
        page_view: PageView | None = None,
    ) -> tuple[str, dict[str, object]]:
        """The state: the language model's payload exactly, guarded the same way."""
        _, payload = super().build_request(ctx, policy, page_view)
        state = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        policy.guard(state, where="decision model state")
        return state, payload

    def _chat_request(
        self, chat_request: Any, message: str, payload: dict[str, object]
    ) -> Any:
        return chat_request(
            model=self.model,
            messages=({"role": "user", "content": payload},),
            extra={"questions": self._question},
        )

    def _parse(self, reply: str) -> RuleOutcome | None:
        """The chosen code, at the probability the model gave it.

        Not Jev's `confidence` field, which measures how concentrated the distribution is
        rather than how likely the choice is to be right (OpenRouter's Jev documentation);
        the probability of the chosen option is the number TypeSafe says is calibrated.
        """
        try:
            answer = json.loads(reply)[QUESTION_ID]
            probabilities = {str(k): float(v) for k, v in answer["probabilities"].items()}
        except (ValueError, KeyError, TypeError):
            return None
        valid = {c.code for c in self.taxonomy.categories} - NOT_OFFERED
        ranked = sorted(
            ((p, code) for code, p in probabilities.items() if code in valid), reverse=True
        )
        if not ranked:
            return None
        (p, code), rest = ranked[0], ranked[1:]
        runner_up = f"; next {rest[0][1]} at {rest[0][0]:.2f}" if rest else ""
        return RuleOutcome(
            code=code,
            confidence=min(max(p, 0.0), 1.0),
            reason=(
                f"The decision model placed this span as {code} with probability {p:.2f}"
                f"{runner_up}, from the masked page, seeing placeholders rather than names."
            ),
            rule="model",
        )
