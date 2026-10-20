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

import hashlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sever.context.record import ContextRecord
from sever.decide.placeholders import (
    PlaceholderPolicy,
    outbound,
    redact_context,
    scrub_unrecognised,
)
from sever.decide.rules import RuleOutcome
from sever.detect.types import EntityType
from sever.gateway import BoundaryUnavailable, require_boundary
from sever.ingest.document import Document
from sever.taxonomy.loader import Taxonomy, default_taxonomy

# The data class this project's calls carry. CLAUDE.md requires that every model call
# goes through the 04 gateway with class `personal`, and as of boundary 0.5.1 that is a
# real parameter on `Gateway.chat` with its own ledger column, so it is passed as one.
#
# Earlier versions had nowhere to put it and it travelled inside `purpose`, which reached
# the ledger as free text and could not be queried. That workaround is gone. What the
# class does NOT do is redact anything: the gateway records it, and the substitution
# happens here, in sever.decide.placeholders, before the request is built.
DATA_CLASS = "personal"
CAPS_PROJECT = "access-to-information-redaction"
DEFAULT_MODEL = "anthropic/claude-haiku-5-5"
# Haiku 5.5 thinks before it answers and the thinking counts against this ceiling, so it
# is set for the thinking and the answer together. A run at low effort used about 300
# output tokens a call; 400 was set for Haiku 4.5, which did not think.
DEFAULT_MAX_TOKENS = 4000
# Low, because this is classification: the effort sweep in the API guidance puts
# classification at low, and the measured run (results/results.md) is at low.
DEFAULT_EFFORT = "low"

SYSTEM_PROMPT = """\
You are assisting a government access-to-information analyst who is deciding, span by \
span, which personal information in a record must be withheld and which must be released.

You never see names. Every person, address, identifier and contact detail has been \
replaced with a typed placeholder such as [PERSON_3] before this request was built. Decide \
from the structure and the context you are given, not from the literal text.

Answer with one category code:

R1 - third-party personal information: an identifiable individual who is not the requester \
and is not acting for a public body. This includes anyone who does not work for the public \
body even when they act professionally: a physician, lawyer, counsellor or landlord writing \
about a client is a third party, and so are their name, practice address and telephone.
R2 - a span in which a third party's information cannot be separated from the requester's.
K1 - the requester's own personal information.
K2 - an officer, employee or contractor of a public body, in information about the position \
or its functions: their name, title, work email, work telephone and office address, and \
their work opinions and actions. Only the public body's own people. Never their employee \
number, home address, personal telephone, health, leave, discipline or their own grievance \
or complaint: in a message about those, the employee is a third party (R1), work address and \
all.
K3 - already publicly available.
K4 - an individual dead more than twenty years, where the record says so.
K5 - consent on the file, or a discretionary benefit of a financial nature.
K6 - not personal information about an identifiable individual at all: an organisation, a \
place, a bare date, a generic role. A place that is somebody's home or practice is not K6.
E1 - you cannot tell from what you were given whether this is an official or a third party.
E2 - a mixed span you cannot see how to sever.

Rules that override your judgement:

- If is_configured_requester is true, or the span belongs to requester_placeholder, the \
answer is K1 unless other people share the span.
- A title paired with the person is strong evidence of K2, but only for information about \
the position. An inherently sensitive identifier is never K2.
- Decide what the record shows. When it does not decide it, answer E1: withholding and \
asking costs the reviewer little, and guessing K on a third party releases someone's \
private information and cannot be undone.

Reply with JSON only, no prose, in exactly this shape:
{"code": "R1", "confidence": 0.0 to 1.0, "evidence": "the field or phrase you relied on"}
"""

# Added to the system prompt only when the decider is told the public body's own email
# domains. Only then, because the prompt is part of the answer-cache key: an unconditional
# change would orphan every recorded answer and the published rows would stop reproducing
# from the committed cache.
PUBLIC_BODY_DOMAIN_NOTE = """
An email placeholder written [EMAIL_PUBLIC_BODY_n] is an address on the public body's own \
email domain, and a plain [EMAIL_n] is an address on any other domain. A public-body \
address is a work address, which is evidence about the position its holder occupies. It is \
not proof that the person is acting in an official capacity in this record: an employee's \
own grievance, health or leave is written from the same domain.
"""

# Added only when the decider sends the page, for the same cache-key reason as the note
# above.
PAGE_NOTE = """
The request also carries page_text: the whole page the span is on, with every person, \
address, identifier and contact replaced by the same placeholders used in the span, so \
[PERSON_3] in the span and [PERSON_3] on the page are the same person. Read it to work \
out who is who: who wrote and who signed, under what title, to whom a message was sent, \
and what it is about. requester_placeholder, when it is not null, is the placeholder of \
the person who made this request. A placeholder written [PERSON_3 or PERSON_6] is a name \
part two people share, written alone; which of them it is, the page around it says.
"""


@dataclass(frozen=True, slots=True)
class PageView:
    """The document as the model may see it: each page masked, and who the requester is.

    One sentence was all the model used to get, and with the rules first and every answer
    accepted, Opus 5.5 escalated 627 of the 3,780 spans that had to be released, most of
    them saying the sentence did not show who the person was. The page does: the signature
    block with its title, the From and To lines, the subject. Every value on it goes
    through `outbound`, the same substitution and scrub as the sentence, and the guard
    reads the result before anything is sent.
    """

    pages: dict[int, str]
    requester: str | None

    @classmethod
    def of(
        cls,
        document: Document,
        universe: Sequence[ContextRecord],
        policy: PlaceholderPolicy,
    ) -> PageView:
        requester = next(
            (
                outbound(c.text, policy)
                for c in universe
                if c.is_requester and c.entity_type is EntityType.PERSON
            ),
            None,
        )
        return cls(
            pages={p.number: outbound(p.text, policy) for p in document.pages},
            requester=requester,
        )


def category_guide(taxonomy: Taxonomy) -> str:
    """Every category as the reviewers' reference card has it: definition, examples, traps.

    The prompt's own list is one line a code, and a model given the page read it
    literally. With the page attached and nothing else changed, Haiku 5.5 released 16
    employee numbers as "a work identifier tied to the position" and 17 outside
    physicians' practice addresses as "a business premises", both against rulings that
    were in the taxonomy or the reviewer study and not in the prompt. Generated from the
    loaded taxonomy rather than copied, so a ruling added to the YAML reaches the model
    in the same commit.
    """
    lines = ["", "The categories in full, with the traps reviewers are warned about:"]
    for c in taxonomy.categories:
        lines.append(f"\n{c.code} - {c.name}. {' '.join(c.definition.split())}")
        # Through the second pass, because the worked examples use invented names and an
        # invented name can be a real person's: "Mr Byrne" in the R2 example matched a
        # persona's surname and the guard refused the request, correctly.
        lines += [f"  Example: {scrub_unrecognised(' '.join(e.split()))}" for e in c.examples]
        lines += [f"  Trap: {' '.join(t.split())}" for t in c.traps]
    return "\n".join(lines) + "\n"


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
    # None, because Haiku 5.5 (like every 5.5 model) refuses a non-default temperature with
    # a 400. Set it only for a model that takes one.
    temperature: float | None = None
    # Sent as output_config.effort. None sends nothing, which is what an older model that
    # rejects the field (Haiku 4.5) needs.
    effort: str | None = DEFAULT_EFFORT
    # Reaches the ledger row as free text. The data class travels in its own field now;
    # this says what the call was for.
    purpose: str = "sever.decide: the residual the rules could not place"
    data_class: str = DATA_CLASS
    # Groups a run's rows in the ledger and is what the per-run spend cap is measured
    # against. A corpus run is thousands of calls and wants to be one run, not thousands.
    run_id: str | None = None
    enabled: bool = False
    # Every request built, kept for the test that asserts no raw entity left and for the
    # cost ledger reconciliation. Bounded so a full corpus run does not hold the whole
    # request history in memory.
    sent: list[dict[str, Any]] = field(default_factory=list)
    keep_last: int = 200
    name: str = "gateway-model"
    # The run's own accounting, filled from each response. See `_account`.
    calls: int = 0
    cost_usd: float = 0.0
    uncosted: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    call_uids: list[str] = field(default_factory=list)
    # An on-disk cache of replies, keyed by the exact request. Off unless a path is given.
    #
    # This is not a speed optimisation, it is what makes the threshold defensible. The
    # confidence threshold is applied to the model's answer *after* the answer comes back,
    # so a sweep over thresholds does not need new answers, it needs the same answers read
    # again. Without a cache, measuring five thresholds means paying five times and
    # comparing five different sets of model answers, which is not a sweep, it is five
    # runs. With it, one paid run buys every threshold and the comparison is exact.
    #
    # Safe to commit only because the requests contain placeholders and never names, which
    # is the same property tests/test_no_raw_entity_leaves.py asserts for the corpus.
    cache_path: Path | None = None
    _cache: dict[str, str] = field(default_factory=dict, repr=False)
    cache_reads: int = 0
    # The distinct requests this run asked for, as opposed to the number of spans it
    # decided. The gap between them is how much the payloads repeat, which is a property of
    # the payloads rather than of the run: see the ablation in `sever/eval/placeholders.py`,
    # where masked payloads repeat across documents and raw ones cannot, because the names
    # make each one unique. Counted from keys touched here, not from `len(self._cache)`,
    # which would also count answers this run loaded from disk and never asked for.
    _keys_seen: set[str] = field(default_factory=set, repr=False)
    # Replay the cache and refuse to send anything. This is what makes the model numbers
    # reproducible from a clone: the cache is committed, the gateway is a private
    # repository, and a stranger checking the published table has neither a key nor a
    # reason to spend money. A cache miss is an error rather than a quiet call, because
    # the failure it guards against is a run that was meant to be free and was not.
    replay_only: bool = False
    # The public body's own email domains, which the operator configures as it configures
    # the requester. Empty, the default, sends exactly what was sent before it existed.
    public_body_domains: tuple[str, ...] = ()
    # Send the span's whole page, masked, and the requester's placeholder, rather than one
    # sentence, and the full category guide. On by default since 2026-10-20: with one
    # sentence the model escalated what the page would have settled (docs/rejected.md,
    # section 7). Off is the one-sentence ablation.
    with_page: bool = True

    @property
    def system_prompt(self) -> str:
        prompt = SYSTEM_PROMPT
        if self.public_body_domains:
            prompt += PUBLIC_BODY_DOMAIN_NOTE
        if self.with_page:
            prompt += PAGE_NOTE + category_guide(self.taxonomy)
        return prompt

    def __post_init__(self) -> None:
        if self.cache_path is not None and self.cache_path.is_file():
            with self.cache_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    self._cache[str(row["key"])] = str(row["reply"])

    def _cache_key(self, message: str) -> str:
        h = hashlib.sha256()
        # Effort is in the key because it changes the answer: the same request at low and at
        # high effort is two different questions to the model, and replaying one for the
        # other would publish an answer nobody asked for.
        for part in (self.model, self.effort or "", self.system_prompt, message):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()

    def _cache_put(self, key: str, reply: str) -> None:
        self._cache[key] = reply
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "reply": reply}, ensure_ascii=False) + "\n")

    def decide(
        self,
        contexts: Sequence[ContextRecord],
        *,
        universe: Sequence[ContextRecord] = (),
        document: Document | None = None,
    ) -> Sequence[RuleOutcome | None]:
        if not contexts:
            return []
        if not self.enabled:
            # Not an error. The rules-only pipeline is a published baseline and it runs
            # this path in CI; every span simply stays escalated.
            return [None] * len(contexts)
        policy = self.policy_for(contexts, universe, self.public_body_domains)
        page_view = (
            PageView.of(document, universe or contexts, policy)
            if self.with_page and document is not None
            else None
        )
        return [self._decide_one(c, policy, page_view) for c in contexts]

    @staticmethod
    def policy_for(
        contexts: Sequence[ContextRecord],
        universe: Sequence[ContextRecord] = (),
        public_body_domains: Sequence[str] = (),
    ) -> PlaceholderPolicy:
        """Build the substitution policy over every entity in the document.

        `universe` rather than `contexts` is the whole point. The spans being sent are the
        residual the rules could not decide; the sentences around them are full of entities
        the rules decided confidently, and those sentences travel in the payload. A policy
        built from the residual alone substitutes the span and ships its neighbours.
        """
        pool = universe if universe else contexts
        return PlaceholderPolicy.for_detections(
            (c.detection for c in pool), public_body_domains=public_body_domains
        )

    def build_request(
        self,
        ctx: ContextRecord,
        policy: PlaceholderPolicy,
        page_view: PageView | None = None,
    ) -> tuple[str, dict[str, object]]:
        """The user message and the payload it was built from.

        Separated from sending so the test can build a request for every context in the
        corpus and assert the guard, without a gateway and without a network.
        """
        payload = redact_context(ctx, policy)
        if page_view is not None:
            payload["page_text"] = page_view.pages.get(ctx.page_number)
            payload["requester_placeholder"] = page_view.requester
        body = json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True)
        message = (
            "Decide the category for this span.\n\n"
            f"{body}\n\n"
            "Reply with JSON only."
        )
        # The guard runs on the message, which is everything in the request built from the
        # record. Nothing is sent if it raises.
        #
        # Not on the system prompt, since 2026-10-20. That is fixed text generated from the
        # taxonomy and holds nothing from any record, and once it carried the full category
        # guide it held ordinary words a record can also contain: on a Library and Archives
        # Canada package the detector typed "years" and "1968" as entities, both appear in
        # the guide ("dead more than twenty years", "died in 1968"), and the guard refused
        # to send the tool's own instructions. The guide's worked examples go through the
        # name scrub all the same; see `category_guide`.
        policy.guard(message, where="model decision request")
        return message, payload

    def _decide_one(
        self,
        ctx: ContextRecord,
        policy: PlaceholderPolicy,
        page_view: PageView | None = None,
    ) -> RuleOutcome | None:
        message, payload = self.build_request(ctx, policy, page_view)
        key = self._cache_key(message)
        self._keys_seen.add(key)
        hit = self._cache.get(key)
        if hit is not None:
            self.cache_reads += 1
            return self._parse(hit)
        if self.replay_only:
            raise ModelUnavailable(
                f"replay-only, and the answer cache does not hold this span "
                f"({ctx.doc_id} {ctx.text!r}). The cache was recorded against a particular "
                f"corpus, seed and prompt; changing any of them invalidates it, and the "
                f"run has to be paid for again."
            )
        gateway = self.gateway or _default_gateway()
        try:
            require_boundary()
            from boundary import ChatRequest
        except (BoundaryUnavailable, ImportError) as exc:  # pragma: no cover
            raise ModelUnavailable(
                f"{exc} Or run the rules-only pipeline, which needs nothing from 04."
            ) from exc

        request = self._chat_request(ChatRequest, message, payload)
        self._record({"payload": payload, "message": message, "model": self.model})
        # purpose, run_id and data_class, and no metadata mapping: an earlier version of
        # this call passed one. It typechecked, it passed every test, and it would have
        # raised TypeError the first time the model layer was switched on, because nothing
        # exercised this line. tests/test_model_layer.py now does, against a fake built
        # from the real signature.
        response = gateway.chat(
            request,
            purpose=self.purpose,
            run_id=self.run_id,
            data_class=self.data_class,
        )
        self._account(response)
        reply = _text_of(response)
        self._cache_put(key, reply)
        return self._parse(reply)

    def _chat_request(
        self, chat_request: Any, message: str, payload: dict[str, object]
    ) -> Any:
        """The gateway request for one span. A hook, so a decision model can send the same
        span as a state and a question rather than as a prompt."""
        return chat_request(
            model=self.model,
            system=self.system_prompt,
            messages=({"role": "user", "content": message},),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            extra={"output_config": {"effort": self.effort}} if self.effort else {},
        )

    def _parse(self, reply: str) -> RuleOutcome | None:
        """One reply, cached or fresh, as an outcome. A hook for the same reason."""
        return self._outcome(parse_answer(reply, self.taxonomy))

    @property
    def keys_seen(self) -> frozenset[str]:
        """The cache keys this run asked for, which `sever cost` uses to say which arm of
        a run paid for which answer."""
        return frozenset(self._keys_seen)

    @property
    def distinct_requests(self) -> int:
        """How many different requests this run needed, however many spans it decided."""
        return len(self._keys_seen)

    def _outcome(self, answer: ModelAnswer | None) -> RuleOutcome | None:
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

    def _account(self, response: Any) -> None:
        """What the run cost, from the gateway's own costing rather than an estimate.

        The ledger is the record of truth and `boundary ledger` can be queried directly;
        this is here so `sever report` can print the cost of the run beside the numbers
        the run produced, which is the pairing the portfolio's budget rule wants.
        """
        self.calls += 1
        cost = getattr(response, "cost_usd", None)
        if isinstance(cost, int | float):
            self.cost_usd += float(cost)
        else:
            self.uncosted += 1
        if getattr(response, "cached", False):
            self.cache_hits += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        uid = getattr(response, "call_uid", None)
        if isinstance(uid, str) and len(self.call_uids) < self.keep_last:
            # 04 asked for these so a ledger row can be joined to the decision it made.
            self.call_uids.append(uid)

    def spend_summary(self) -> str:
        if not self.calls:
            if self.cache_reads:
                return f"{self.cache_reads} answers replayed from the cache, nothing spent"
            return "no model calls"
        per = self.cost_usd / self.calls
        parts = [
            f"{self.calls} model calls",
            f"US${self.cost_usd:.4f}",
            f"US${per:.5f} per call",
            f"{self.input_tokens} in / {self.output_tokens} out tokens",
        ]
        if self.cache_hits:
            parts.append(f"{self.cache_hits} served from the gateway cache")
        if self.cache_reads:
            parts.append(f"{self.cache_reads} replayed from the answer cache, free")
        if self.uncosted:
            parts.append(f"{self.uncosted} uncosted, so the total is a floor")
        return ", ".join(parts)

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
        require_boundary()
        from boundary import Gateway
    except (BoundaryUnavailable, ImportError) as exc:
        raise ModelUnavailable(
            f"{exc} Or run the rules-only pipeline, which needs nothing from 04."
        ) from exc
    config = os.environ.get("BOUNDARY_CONFIG")
    if not config:
        raise ModelUnavailable(
            "BOUNDARY_CONFIG is not set, so there is no gateway configuration to route "
            "through. Point it at a boundary.yaml with a spend cap set."
        )
    # The project key is the repository name, not the package name, because that is what
    # keys caps.yaml in the 04 repository and what every other project uses. A key with no
    # entry there silently falls to the US$10 monthly default, which a full corpus run
    # would hit partway through.
    return Gateway.from_config(config, project=CAPS_PROJECT)
