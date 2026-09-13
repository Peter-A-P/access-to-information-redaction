"""Model decisions on the residual, through the 04 gateway, on placeholders only.

The rules decide the clear cases. What reaches here is the genuinely ambiguous remainder:
a name with no title anywhere, an identifier in an odd place, a person mentioned once. The
model is asked one question per span with a constrained answer, and anything it is not
confident about goes back to escalation rather than into a released document.

Three properties are enforced in this file rather than assumed:

  1. Nothing raw leaves. The placeholder policy substitutes, and `policy.guard` inspects
     the serialised request body before it is handed to the gateway. A leak raises and
     nothing is sent.
  2. Every call goes through `boundary.Gateway` with the data class recorded on the call.
     There is no direct HTTP path here and no vendor SDK import.
  3. An answer whose code is not in the taxonomy is discarded, not coerced. A model that
     invents a category has failed, and quietly mapping its answer to the nearest real one
     would hide that.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sever.context.record import ContextRecord
from sever.decide.placeholders import PlaceholderPolicy, redact_context
from sever.decide.rules import RuleOutcome
from sever.taxonomy.loader import Taxonomy, default_taxonomy

# The gateway records this on every call. 04's policy for the class is what will perform
# the substitution once Part B exists; until then the substitution happens here and the
# header is the honest declaration of what the payload contains.
DATA_CLASS = "personal"
DEFAULT_MODEL = "anthropic/claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 400

SYSTEM_PROMPT = """\
You are assisting a government access-to-information analyst who is deciding, span by \
span, which personal information in a record must be withheld and which must be released.

You never see names. Every person, address, identifier and contact detail has been \
replaced with a typed placeholder such as [PERSON_3] before this request was built. Decide \
from the structure and the context you are given, not from the literal text.

Answer with one category code:

R1 - third-party personal information: an identifiable individual who is not the requester \
and is not acting in an official capacity.
R2 - a span in which a third party's information cannot be separated from the requester's.
K1 - the requester's own personal information.
K2 - an officer or employee of a public body, or a contractor, in information that relates \
to the position or its functions: name, title, business contact details, work opinions and \
actions. Not their home address, personal number, health or their own grievance.
K3 - already publicly available.
K4 - an individual dead more than twenty years, where the record says so.
K5 - consent on the file, or a discretionary benefit of a financial nature.
K6 - not personal information about an identifiable individual at all: an organisation, a \
place, a bare date, a generic role.
E1 - you cannot tell from what you were given whether this is an official or a third party.
E2 - a mixed span you cannot see how to sever.

Rules that override your judgement:

- If is_configured_requester is true, the answer is K1 unless other people share the span.
- A title paired with the person is strong evidence of K2, but only for information about \
the position. An inherently sensitive identifier is never K2.
- If the evidence does not decide it, answer E1. Withholding and asking is correct and \
costs little. Guessing K on a third party releases someone's private information and \
cannot be undone.

Reply with JSON only, no prose, in exactly this shape:
{"code": "R1", "confidence": 0.0 to 1.0, "evidence": "the field or phrase you relied on"}
"""


class ModelUnavailable(RuntimeError):
    """The gateway library or its configuration is missing."""


@dataclass(frozen=True, slots=True)
class ModelAnswer:
    code: str
    confidence: float
    evidence: str
    raw: str


def parse_answer(text: str, taxonomy: Taxonomy) -> ModelAnswer | None:
    """Parse the constrained JSON. Returns None on anything unparseable or off-taxonomy,
    which the pipeline treats as no answer and therefore as escalation."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    code = str(data.get("code", "")).strip().upper()
    valid = {c.code for c in taxonomy.categories}
    if code not in valid:
        return None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    confidence = min(max(confidence, 0.0), 1.0)
    return ModelAnswer(
        code=code,
        confidence=confidence,
        evidence=str(data.get("evidence", ""))[:400],
        raw=match.group(0),
    )


@dataclass
class GatewayModelDecider:
    """Decides the residual through `boundary.Gateway`.

    `enabled` defaults to False and the CLI must be told to turn it on. That is not
    timidity: a corpus run is thousands of calls and the portfolio's rule is that a hard
    spend cap is set before the first call, so the safe default is the one that cannot
    spend anything by accident.
    """

    gateway: Any = None
    model: str = DEFAULT_MODEL
    taxonomy: Taxonomy = field(default_factory=default_taxonomy)
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = 0.0
    purpose: str = "sever.decide"
    enabled: bool = False
    # Every request built, kept for the test that asserts no raw entity left and for the
    # cost ledger reconciliation. Bounded so a full corpus run does not hold the whole
    # request history in memory.
    sent: list[dict[str, Any]] = field(default_factory=list)
    keep_last: int = 200
    name: str = "gateway-model"

    def decide(
        self,
        contexts: Sequence[ContextRecord],
        *,
        universe: Sequence[ContextRecord] = (),
    ) -> Sequence[RuleOutcome | None]:
        if not contexts:
            return []
        if not self.enabled:
            # Not an error. The rules-only pipeline is a published baseline and it runs
            # this path in CI; every span simply stays escalated.
            return [None] * len(contexts)
        policy = self.policy_for(contexts, universe)
        return [self._decide_one(c, policy) for c in contexts]

    @staticmethod
    def policy_for(
        contexts: Sequence[ContextRecord], universe: Sequence[ContextRecord] = ()
    ) -> PlaceholderPolicy:
        """Build the substitution policy over every entity in the document.

        `universe` rather than `contexts` is the whole point. The spans being sent are the
        residual the rules could not decide; the sentences around them are full of entities
        the rules decided confidently, and those sentences travel in the payload. A policy
        built from the residual alone substitutes the span and ships its neighbours.
        """
        pool = universe if universe else contexts
        return PlaceholderPolicy.for_detections(c.detection for c in pool)

    def build_request(
        self, ctx: ContextRecord, policy: PlaceholderPolicy
    ) -> tuple[str, dict[str, object]]:
        """The user message and the payload it was built from.

        Separated from sending so the test can build a request for every context in the
        corpus and assert the guard, without a gateway and without a network.
        """
        payload = redact_context(ctx, policy)
        body = json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True)
        message = (
            "Decide the category for this span.\n\n"
            f"{body}\n\n"
            "Reply with JSON only."
        )
        # The guard runs on everything that would be serialised into the request, which is
        # the system prompt plus this message. Nothing is sent if it raises.
        policy.guard(SYSTEM_PROMPT + "\n" + message, where="model decision request")
        return message, payload

    def _decide_one(self, ctx: ContextRecord, policy: PlaceholderPolicy) -> RuleOutcome | None:
        message, payload = self.build_request(ctx, policy)
        gateway = self.gateway or _default_gateway()
        try:
            from boundary import ChatRequest
        except ImportError as exc:  # pragma: no cover
            raise ModelUnavailable(
                "boundary is not installed. Install the gateway extra with "
                "`uv pip install -e '.[gateway]'`, or run the rules-only pipeline."
            ) from exc

        request = ChatRequest(
            model=self.model,
            system=SYSTEM_PROMPT,
            messages=({"role": "user", "content": message},),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._record({"payload": payload, "message": message, "model": self.model})
        response = gateway.chat(
            request,
            purpose=self.purpose,
            metadata={"data_class": DATA_CLASS, "doc_id": ctx.doc_id, "page": ctx.page_number},
        )
        answer = parse_answer(_text_of(response), self.taxonomy)
        if answer is None:
            return None
        return RuleOutcome(
            code=answer.code,
            confidence=answer.confidence,
            reason=(
                f"The model placed this span as {answer.code} at {answer.confidence:.2f} "
                f"from the context alone, seeing placeholders rather than names. "
                f"Its evidence: {answer.evidence}"
            ),
            rule="model",
        )

    def _record(self, entry: dict[str, Any]) -> None:
        self.sent.append(entry)
        if len(self.sent) > self.keep_last:
            del self.sent[: len(self.sent) - self.keep_last]


def _text_of(response: Any) -> str:
    for attr in ("text", "content", "output_text"):
        value = getattr(response, attr, None)
        if isinstance(value, str):
            return value
    return str(response)


def _default_gateway() -> Any:  # pragma: no cover - needs a configured gateway
    try:
        from boundary import Gateway
    except ImportError as exc:
        raise ModelUnavailable(
            "boundary is not installed. Install the gateway extra with "
            "`uv pip install -e '.[gateway]'`, or run the rules-only pipeline."
        ) from exc
    config = os.environ.get("BOUNDARY_CONFIG")
    if not config:
        raise ModelUnavailable(
            "BOUNDARY_CONFIG is not set, so there is no gateway configuration to route "
            "through. Point it at a boundary.yaml with a spend cap set."
        )
    return Gateway.from_config(config, project="sever")
