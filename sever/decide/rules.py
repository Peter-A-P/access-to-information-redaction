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

import re
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


def archival_age(ctx: ContextRecord) -> RuleOutcome | None:
    """K7 for an archival record about someone the record shows was born more than 110
    years ago.

    Added 2026-10-18 for the held-out release packages, where Library and Archives Canada
    released the families in immigration case files and the tool withheld every "son" and
    "wife". It runs only when the request says the records are archival
    (`RequestConfig.archival`), and only on evidence in the record: the page's own latest
    year, or a birth stated beside the person's name. It runs after the requester rules and
    before everything that withholds, because 110 years from birth covers a health number
    and a family relationship as much as a name: none of them is withheld for privacy once
    the person it is about is past the rule.
    """
    if ctx.archival_cutoff is None or not ctx.entity_type.is_about_a_person:
        return None
    cutoff = ctx.archival_cutoff
    if ctx.birth_year is not None and ctx.birth_year <= cutoff:
        why = (
            f"the record puts this person's birth in or before {ctx.birth_year}, more than "
            f"110 years ago"
        )
    elif ctx.page_year is not None and ctx.page_year <= cutoff:
        why = (
            f"the latest year on this page is {ctx.page_year}, so everyone it names was born "
            f"more than 110 years ago"
        )
    else:
        return None
    return RuleOutcome(
        code="K7",
        confidence=0.85,
        reason=f"An archival record, and {why}; the archives may disclose it.",
        rule="archival_age",
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


def employee_number(ctx: ContextRecord) -> RuleOutcome | None:
    """R1 for an employee number, wherever it appears and whoever it belongs to.

    Ruled on 2026-10-18 in the reviewer study: an employee number is an identifying number
    assigned to the person, not information about the position, so it is withheld even in
    a signature block beside a name and title that are released. Until this rule it fell
    through to the model, which read the signature block and released it as "a work
    identifier tied to the position" 16 times in one run. A ruling that is the same every
    time belongs here rather than in a prompt. Runs before the capacity rules for the same
    reason `inherently_sensitive` does.
    """
    if ctx.entity_type is not EntityType.EMPLOYEE_ID:
        return None
    return RuleOutcome(
        code="R1",
        confidence=0.95,
        reason=(
            "An employee number is an identifying number assigned to the person, not "
            "information about the position, so it is withheld even where the name and "
            "title beside it are released."
        ),
        rule="employee_number",
    )


def family_relationship(ctx: ContextRecord) -> RuleOutcome | None:
    """R1 for a family relationship pointing at a third party: "the client's sibling".

    The first reviewer's ruling, 2026-10-08: once the name is severed, the relationship
    still identifies the person to a requester who knows their own family, so it goes too.
    Runs after the requester rules, so a relationship term the requester uses about
    themselves is not reached, and before anything that could release it.
    """
    if ctx.entity_type is not EntityType.KINSHIP:
        return None
    return RuleOutcome(
        code="R1",
        confidence=0.9,
        reason=(
            f"{ctx.text!r} is a family relationship. With the name severed it still "
            f"identifies the person to anyone who knows the family."
        ),
        rule="family_relationship",
    )


def complaint_party(ctx: ContextRecord) -> RuleOutcome | None:
    """R1 for the parties to a confidential workplace complaint, and their job titles.

    Reviewer 1's ruling, 2026-10-10: a complaint by or against an employee is about them,
    not about their position, so the exclusion for officials does not reach it, and a
    title is withheld with the name because in a small unit the title identifies the
    person. Runs after the requester rules, so a requester who is a party still gets
    their own information, and before both the rule that releases a bare title and the
    rules that release a titled official.
    """
    if ctx.complaint_party is None:
        return None
    return RuleOutcome(
        code="R1",
        confidence=0.85,
        reason=(
            f"{ctx.text!r} is {ctx.complaint_party} in a confidential workplace complaint. "
            f"That is about the person, not their position, and a title would identify them."
        ),
        rule="complaint_party",
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
    # A title in a message about its holder's own leave or grievance is that person's
    # title, and releasing it beside a withheld name identifies them in a small unit.
    if ctx.own_affairs_message and ctx.entity_type is EntityType.JOB_TITLE:
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
    """K2. A name paired with a title, or a name signing on letterhead.

    Not in a message about someone's own affairs, where a title in a signature block is
    no evidence that its holder is doing their job; see sever.context.own_affairs.
    """
    if ctx.cluster_ambiguous or ctx.own_affairs_message:
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
    if ctx.own_affairs_message:
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


def staff_directory(ctx: ContextRecord) -> RuleOutcome | None:
    """K2 for a full name or a work contact the published staff directory lists.

    Runs after every rule that can see the record say otherwise: the requester, an
    inherently sensitive identifier, the mixed span, a title or signature in the record
    itself. It never sees a span one of those settled. Its confidence is below the title
    rule's because the evidence is about the name and not about the sentence: an employee
    who is the complainant in their own grievance is in the directory too.
    """
    if ctx.directory_match is None or ctx.cluster_ambiguous or ctx.own_affairs_message:
        return None
    return RuleOutcome(
        code="K2",
        confidence=0.75,
        reason=f"{ctx.directory_match.reason}, so this is an officer or employee.",
        rule="staff_directory",
    )


# Words that make a sentence about the member rather than about the work. A rank says
# someone is in the forces; it says nothing about whether this sentence is their job or
# their life, and these are the sentences where it is their life.
_PERSONAL_MATTER = re.compile(
    r"harass|complain|grievance|medical|injur|wound|casualt|killed|\bdied\b|death|"
    r"deceased|funeral|memorial|compassionate|sick|illness|diagnos|disciplin|"
    r"court martial|summary trial|misconduct|pregnan|maternity|parental|divorce|"
    r"next of kin|family|spouse|estate|\bleave\b",
    re.IGNORECASE,
)


def military_rank(ctx: ContextRecord) -> RuleOutcome | None:
    """K2 for a person the record gives a Canadian Armed Forces rank, in a record the forces
    produced.

    Added 2026-10-17 for the real-record track, where every one of 533 spans was withheld
    and a good share of them were officers named with their rank in the forces' own
    correspondence. A member of the forces is an officer or employee of the institution, so
    a rank is evidence of the capacity the exclusion for officials turns on.

    It is evidence about the person, not about the sentence, which is the same weakness the
    staff directory has, so it sits beside that rule at the same confidence and after every
    rule that reads the sentence: a requester, an identifier, a complaint, a title in a
    signature block all win first. And it stands aside where the sentence is about the
    member's own life rather than the work: a corporal's injury, a captain's compassionate
    leave and a sergeant's memorial service are about them, and a rank does not make them
    official business. Those escalate.
    """
    if ctx.rank is None or ctx.cluster_ambiguous:
        return None
    if ctx.entity_type is not EntityType.PERSON:
        return None
    if _PERSONAL_MATTER.search(ctx.sentence):
        return None
    return RuleOutcome(
        code="K2",
        confidence=0.75,
        reason=(
            f"Named with the rank {ctx.rank!r} in a Defence record, so a member of the "
            f"Canadian Armed Forces; nothing in the sentence is about them personally."
        ),
        rule="military_rank",
    )


def deceased_over_twenty_years(ctx: ContextRecord) -> RuleOutcome | None:
    """K4, and only where the record itself carries the date of death.

    Not implemented as a guess. A date of death has to be in the sentence or the cluster's
    text for this to fire; absent a date the person may be alive and the span is escalated
    by the fallthrough, which is why there is no "probably historical" branch here.
    """
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
    archival_age,
    inherently_sensitive,
    employee_number,
    family_relationship,
    complaint_party,
    not_personal_information,
    mixed_span,
    official_capacity,
    official_capacity_contact,
    public_register,
    staff_directory,
    military_rank,
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
