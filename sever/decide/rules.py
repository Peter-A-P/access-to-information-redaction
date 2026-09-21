"""Deterministic rules over the context record.

Ordering is the whole design. The rules run in a fixed sequence and the first one to fire
wins, so the sequence is a statement of precedence and it is deliberate:

  1. The requester's own information beats everything. A person's own file is the thing
     they asked for.
  2. Inherently sensitive identifiers beat capacity. A director's medical care plan number
     is not about being a director, and the exclusion for officials is expressly limited to
     information that "relates to the position or functions".
  3. Non-personal entity types are discarded before any role reasoning, so a detector
     false positive is not dressed up as a decision.
  4. Then capacity, then the public register, then the death rule.
  5. Anything left is escalated. There is no rule that releases a span because nothing
     matched; the residual is withheld and the reviewer is asked.

Each rule returns the code, a confidence and a sentence of explanation naming the evidence
it used, because a redaction schedule that says "R1" and a redaction schedule that says
"R1: named as the complainant, no title anywhere in the record" are different products.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sever.context.record import ContextRecord
from sever.detect.types import EntityType
from sever.ingest.document import BlockKind


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    code: str
    confidence: float
    reason: str
    rule: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")


Rule = Callable[[ContextRecord], RuleOutcome | None]

# Block kinds where a bare name is being used administratively rather than described. A
# name in a distribution list is not, on its own, evidence of anything.
_ADMIN_BLOCKS = frozenset({BlockKind.EMAIL_HEADER, BlockKind.ATTACHMENT_NOTE, BlockKind.HEADER})


def requester_own_information(ctx: ContextRecord) -> RuleOutcome | None:
    """K1. Fires first, and fires on identifiers as well as names: the requester's own
    medical care plan number is theirs."""
    if not ctx.is_requester:
        return None
    match = ctx.requester_match
    assert match is not None
    detail = match.detail or f"matched the configured requester on {match.matched_on!r}"
    return RuleOutcome(
        code="K1",
        confidence=0.99 if match.strength.value in ("exact", "normalised") else 0.9,
        reason=f"The requester's own information: {detail}.",
        rule="requester_own_information",
    )


def requester_ambiguous(ctx: ContextRecord) -> RuleOutcome | None:
    """E1. A partial name that could be the requester or could be someone else is the one
    case where guessing is unacceptable in both directions, so it never reaches the
    model."""
    if not ctx.is_requester_ambiguous:
        return None
    match = ctx.requester_match
    assert match is not None
    return RuleOutcome(
        code="E1",
        confidence=1.0,
        reason=(
            f"{ctx.text!r} could be the requester or another person named in this record "
            f"({match.detail}). Withheld pending the reviewer's answer."
        ),
        rule="requester_ambiguous",
    )


def inherently_sensitive(ctx: ContextRecord) -> RuleOutcome | None:
    """R1 for health numbers, insurance numbers, dates of birth and financial details,
    whoever they belong to. Runs before the capacity rules on purpose."""
    if not ctx.entity_type.is_inherently_sensitive:
        return None
    return RuleOutcome(
        code="R1",
        confidence=0.97,
        reason=(
            f"A {ctx.entity_type.value.replace('_', ' ')} is personal information about "
            f"an individual whatever their role; the exclusion for officials reaches only "
            f"information about the position."
        ),
        rule="inherently_sensitive",
    )


def not_personal_information(ctx: ContextRecord) -> RuleOutcome | None:
    """K6. An organisation, a place, a bare date or a job title with no person attached.

    Yields to positive evidence that the span is a person, because the entity type is the
    detector's *guess* while a register match or a paired title is an observation about
    this record. Language models mistype names routinely and the mistake is not random:
    "Perpetua Quirke" came back as a LOCATION, and without this guard K6 fired before the
    public-register rule could and a minister's name was released as "not personal
    information" for the wrong reason. Right answer, wrong reasoning, and the reasoning is
    what goes in the schedule.

    ## The job-title guard that was here until 2026-09-21

    A job title with any other person mentioned in the same sentence used to yield, on the
    reasoning that "a title beside a name may be identifying in a small unit". It was
    written on the first build day, no test ever covered it, and measuring unlabelled
    detections found what it actually did: **every span this tool withholds that no persona
    owns is a bare job title escalated by this guard**, 16 of them in twenty documents.
    "Minister", "Deputy Minister", "Manager", "officer". About one box over the word
    "Minister" per page, each one costing a reviewer a decision.

    The guard also put this module in direct contradiction with the privacy boundary.
    `sever/decide/placeholders.py` does not substitute a job title before sending a request,
    and says why in as many words: "Regional Director is a position, not a person". So the
    tool was sending a title to a vendor on the grounds that it is not personal information
    and then putting a box over it on the grounds that it might be. Both cannot be right,
    and the boundary's reading is the one the taxonomy agrees with.

    What remains of the concern is real but narrower than the guard was: a *unique* office
    in a small unit can identify its holder. That is not a property of the word "Minister"
    and it is not detectable from a co-mention count, so it belongs with the reviewer, who
    sees the page. `docs/escalation.md` records it as a thing this tool does not decide.
    """
    if ctx.entity_type.is_about_a_person:
        return None
    if ctx.register_match is not None or ctx.title is not None:
        return None
    return RuleOutcome(
        code="K6",
        confidence=0.9,
        reason=(
            f"Detected as {ctx.entity_type.value.replace('_', ' ')}, which is not "
            f"information about an identifiable individual."
        ),
        rule="not_personal_information",
    )


def official_capacity(ctx: ContextRecord) -> RuleOutcome | None:
    """K2. A name paired with a title, or a name signing on letterhead."""
    if ctx.cluster_ambiguous:
        return None
    if ctx.title is not None:
        where = ctx.title_source or "the record"
        return RuleOutcome(
            code="K2",
            confidence=0.95 if ctx.title_source in ("signature", "letterhead") else 0.85,
            reason=(
                f"Named with the title {ctx.title!r} in {where.replace('_', ' ')}, so this "
                f"is an officer or employee acting in an official capacity."
            ),
            rule="official_capacity_title",
        )
    if any(m.source == "signature" for m in ctx.role_mentions):
        return RuleOutcome(
            code="K2",
            confidence=0.8,
            reason="Appears in the signature block of this record, signing in an official capacity.",
            rule="official_capacity_signature",
        )
    return None


def official_capacity_contact(ctx: ContextRecord) -> RuleOutcome | None:
    """K2 for a work email or telephone number sitting in a signature block or letterhead.
    A business address and telephone number are named in the exclusion itself."""
    if ctx.entity_type not in (EntityType.EMAIL, EntityType.PHONE, EntityType.ADDRESS):
        return None
    if ctx.block_kind not in (BlockKind.SIGNATURE, BlockKind.LETTERHEAD, BlockKind.FOOTER):
        return None
    return RuleOutcome(
        code="K2",
        confidence=0.85,
        reason=(
            f"A business contact detail in the {ctx.block_kind.value.replace('_', ' ')} of "
            f"the record; business address and telephone number are within the exclusion "
            f"for officials."
        ),
        rule="official_capacity_contact",
    )


def public_register(ctx: ContextRecord) -> RuleOutcome | None:
    """K3. Already published, with the source recorded."""
    if ctx.register_match is None:
        return None
    return RuleOutcome(
        code="K3",
        confidence=0.9,
        reason=f"Already publicly available: {ctx.register_match.reason}.",
        rule="public_register",
    )


def deceased_over_twenty_years(ctx: ContextRecord) -> RuleOutcome | None:
    """K4, and only where the record itself carries the date of death.

    Not implemented as a guess. A date of death has to be in the sentence or the cluster's
    text for this to fire; absent a date the person may be alive and the span is escalated
    by the fallthrough, which is why there is no "probably historical" branch here.
    """
    import re

    if ctx.entity_type is not EntityType.PERSON:
        return None
    text = ctx.sentence
    m = re.search(
        r"\b(?:died|deceased|date of death|d\.)\s*(?:on\s+)?(?:in\s+)?(\d{4}-\d{2}-\d{2}|\b(?:19|20)\d{2}\b)",
        text,
        re.IGNORECASE,
    )
    if m is None:
        return None
    import datetime as dt

    raw = m.group(1)
    year = int(raw[:4])
    if dt.date.today().year - year <= 20:
        return RuleOutcome(
            code="E1",
            confidence=1.0,
            reason=(
                f"Recorded as having died in {year}, which is within twenty years, so the "
                f"exclusion for the long dead does not apply and the role question stands."
            ),
            rule="deceased_within_twenty_years",
        )
    return RuleOutcome(
        code="K4",
        confidence=0.9,
        reason=(
            f"The record states a death in {year}, more than twenty years ago, so this is "
            f"outside the definition of personal information."
        ),
        rule="deceased_over_twenty_years",
    )


def mixed_span(ctx: ContextRecord) -> RuleOutcome | None:
    """E2. The requester and a third party in one sentence, where the tool has not been
    able to place the other person. Severance is mandatory but where to cut is the
    reviewer's judgement."""
    if not ctx.co_mentions_in_sentence:
        return None
    if not ctx.is_requester:
        return None
    return RuleOutcome(
        code="E2",
        confidence=0.8,
        reason=(
            f"The requester and {len(ctx.co_mentions_in_sentence)} other named "
            f"individual(s) appear in one sentence. Severance is required but the cut is "
            f"a judgement, so the span is withheld and referred."
        ),
        rule="mixed_span",
    )


def unresolved(ctx: ContextRecord) -> RuleOutcome:
    """The fallthrough. Never releases."""
    if ctx.entity_type is EntityType.PERSON:
        reason = (
            f"No title, no signature-block or letterhead mention, no register entry and no "
            f"match to the requester. The record does not say whether {ctx.text!r} is an "
            f"official or a third party."
        )
    else:
        reason = (
            f"A {ctx.entity_type.value.replace('_', ' ')} that could not be attributed to "
            f"the requester, to an official acting in an official capacity, or to a "
            f"published source."
        )
    return RuleOutcome(code="E1", confidence=0.5, reason=reason, rule="unresolved")


# The order is the precedence. Changing it changes the tool's behaviour, so it lives in
# one place and the tests assert the cases that turn on it.
DEFAULT_RULES: tuple[Rule, ...] = (
    requester_ambiguous,
    requester_own_information,
    inherently_sensitive,
    not_personal_information,
    mixed_span,
    official_capacity,
    official_capacity_contact,
    public_register,
    deceased_over_twenty_years,
)


@dataclass(frozen=True, slots=True)
class RuleResult:
    outcome: RuleOutcome
    # True when a rule decided; False when the fallthrough did. The residual is what goes
    # to the model, so this flag is the split between the rules-only and the full pipeline.
    decided_by_rule: bool


def apply(ctx: ContextRecord, rules: Sequence[Rule] = DEFAULT_RULES) -> RuleResult:
    for rule in rules:
        outcome = rule(ctx)
        if outcome is not None:
            return RuleResult(outcome=outcome, decided_by_rule=True)
    return RuleResult(outcome=unresolved(ctx), decided_by_rule=False)
