"""Typed placeholders: how a frontier model decides an access-to-information question
without seeing a single name.

The composition argument of this project in one file. The decision layer needs to know
whether a span is an official acting in an official capacity or a third party, and that is
a property of the *context*: a title in a signature block, a match against a public
register, a position in an email header. It is not a property of the literal string
"Marie Doucette". So every detected entity is replaced by a typed placeholder before the
request is built, the model reasons over the structure, and the answer is rehydrated
locally.

PLAN.md has this done by the gateway's policy for data class `personal` (04 Part B). That
policy does not exist yet, so the substitution is performed here and the request is still
sent through the gateway. When 04 Part B lands, this module becomes the fallback and the
guard below stays where it is, because a guard that only runs when you remember to call it
is not a guard.

`RawEntityLeak` is raised *before* anything is sent. It is not a test helper. The test
asserts the same property, but the property is enforced in the code path so that it holds
on runs nobody is watching.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from sever.context.record import ContextRecord
from sever.context.requester import normalise, normalise_identifier
from sever.detect.types import Detection, EntityType

# Strings short enough that requiring their absence would be meaningless: a two-letter
# surname fragment appears in ordinary prose. Substitution still replaces them; the guard
# does not fail on them.
_MIN_GUARDED_LENGTH = 4

# Detected types that are not personal information and are deliberately NOT substituted.
#
# This is the one place where the boundary is drawn on purpose rather than by default, so
# the reasoning belongs here. "Regional Director" is a position, not a person, and the
# whole K2 decision turns on whether a title is paired with the span. Replacing it with
# [JOB_TITLE_2] would delete precisely the evidence the model is being asked to weigh and
# would leave escalation as the only possible answer. The same goes for the name of a
# department. Neither identifies an individual on its own, and the taxonomy says so: an
# organisation is K6.
#
# Everything else is substituted, including places and dates, because a town plus a date
# plus a role identifies a person in a small province even though none of the three is a
# name.
NOT_SUBSTITUTED = frozenset({EntityType.JOB_TITLE, EntityType.ORGANISATION})

# A name part shorter than this is not distinctive enough to substitute on: replacing
# every "de" or "Le" in a document would mangle ordinary prose.
MIN_ALIAS_LENGTH = 3

HONORIFICS = frozenset(
    {"mr", "mrs", "ms", "miss", "dr", "prof", "hon", "sir", "madam", "rev", "mx"}
)

# Words that turn up inside a mis-detected person span and are not names. Registering one
# as an alias is not a privacy failure, but it is a denial-of-service on the guard: every
# request containing the ordinary word "date" would be refused, and the pipeline would
# stop. The detector is fixed not to produce these (it no longer lets a PERSON span cross
# a line break), and this list is the second line of defence for the ones it still will.
NOT_NAME_PARTS = frozenset(
    {
        "date", "time", "name", "file", "case", "page", "from", "sent", "subject",
        "present", "regrets", "client", "worker", "staff", "note", "notes", "report",
        "office", "email", "phone", "address", "encl", "attention", "memorandum",
        "confidential", "department", "division", "branch", "section", "regional",
        "the", "and", "for", "with", "this", "that", "your", "our",
    }
)


class RawEntityLeak(RuntimeError):
    """A detected entity survived substitution and would have left the boundary."""


@dataclass
class PlaceholderPolicy:
    """A per-document, stable mapping from entity text to typed placeholder.

    Stable matters: the same person must get the same placeholder on page 1 and page 7, or
    the model cannot reason about consistency across a record, which is the thing the
    model-only baseline is bad at.

    Two properties here were added after the corpus-wide leak test caught their absence.
    Both are easy to get wrong and invisible when you do, so both are written down.

    First, a policy must be built over *every* detection in the document, not only over the
    spans being sent. The residual spans are the ones the rules could not decide, but the
    sentence around a residual span contains entities the rules decided perfectly well, and
    that sentence is in the payload. Building the policy from the residual alone would have
    sent 74 real values, including dates of birth and health numbers, across a corpus of
    twelve documents.

    Second, a detected full name has to license the substitution of its parts. The detector
    finds "Marie Chaulk"; the prose two sentences later says "Marie". A policy keyed on the
    exact surface form replaces the first and ships the second. So each part of a detected
    person's name becomes an alias for the same placeholder, which also keeps the model's
    view consistent: one person, one token, whatever the prose calls them.
    """

    # Every surface form that gets substituted, mapped to its placeholder. Includes the
    # name-part aliases, so it is larger than the set of placeholders.
    _by_value: dict[str, str] = field(default_factory=dict)
    # One entry per placeholder, mapped to the canonical value. Used for rehydration.
    _by_placeholder: dict[str, str] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def for_detections(
        cls, detections: Iterable[Detection], *, extra: Mapping[str, EntityType] = {}
    ) -> PlaceholderPolicy:
        policy = cls()
        # Longest first, so "Marie Doucette" is substituted before "Doucette" and the
        # surname does not survive inside an already-substituted string.
        ordered = sorted(detections, key=lambda d: -len(d.text))
        for d in ordered:
            if d.entity_type in NOT_SUBSTITUTED:
                continue
            placeholder = policy.placeholder_for(d.text, d.entity_type)
            if d.entity_type is EntityType.PERSON:
                policy.add_aliases(d.text, placeholder)
            elif d.entity_type is EntityType.EMAIL:
                # The local part of a work address is very often the name with the
                # separators removed, and it survives any truncation of the address.
                # Registering it means the name goes even where only a fragment of the
                # address made it into the context.
                local = d.text.split("@", 1)[0]
                if len(local) >= MIN_ALIAS_LENGTH:
                    policy._by_value.setdefault(local.casefold(), placeholder)
        for value, kind in sorted(extra.items(), key=lambda kv: -len(kv[0])):
            policy.placeholder_for(value, kind)
        return policy

    def add_aliases(self, name: str, placeholder: str) -> None:
        """Let each part of a person's name stand for the whole.

        Skipped where the part already belongs to a different person: collapsing two people
        onto one token would tell the model they are the same person, which is a worse
        error than a name part it has not been given.
        """
        for part in name.replace(",", " ").split():
            cleaned = part.strip(".'\"()").casefold()
            if len(cleaned) < MIN_ALIAS_LENGTH or cleaned in HONORIFICS:
                continue
            # SAFE_CAPITALISED is the decision vocabulary the second pass refuses to
            # mask: months, job titles, the words of the legislation, the furniture of a
            # memorandum. A word on that list is not a name part either, and deriving the
            # two from one list keeps them from drifting. A better language model made
            # this matter: it typed the heading word "Minutes" as a person, "minutes"
            # became an alias, and the guard then refused every request containing the
            # ordinary word.
            if cleaned in NOT_NAME_PARTS or cleaned in SAFE_CAPITALISED:
                continue
            if not cleaned.isalpha():
                continue
            existing = self._by_value.get(cleaned)
            if existing is not None and existing != placeholder:
                continue
            self._by_value.setdefault(cleaned, placeholder)

    def placeholder_for(self, value: str, entity_type: EntityType) -> str:
        key = self._key(value)
        if not key:
            return value
        existing = self._by_value.get(key)
        if existing is not None:
            return existing
        label = entity_type.value.upper()
        n = self._counts.get(label, 0) + 1
        self._counts[label] = n
        placeholder = f"[{label}_{n}]"
        self._by_value[key] = placeholder
        self._by_placeholder[placeholder] = value
        return placeholder

    @staticmethod
    def _key(value: str) -> str:
        return value.strip().casefold()

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(self._by_placeholder.values())

    @property
    def substituted_values(self) -> tuple[str, ...]:
        """Every surface form that gets replaced, longest first."""
        return tuple(sorted(self._by_value, key=len, reverse=True))

    def apply(self, text: str) -> str:
        """Replace every known entity, and every part of a known name, with a placeholder."""
        if not text:
            return text
        out = text
        for value in self.substituted_values:
            placeholder = self._by_value[value]
            # Word boundaries matter for the short aliases: without them "Marie" inside
            # "Mariewood" would be replaced and the released prose corrupted.
            out = re.sub(
                r"(?<!\w)" + re.escape(value) + r"(?!\w)",
                placeholder,
                out,
                flags=re.IGNORECASE,
            )
        return out

    def rehydrate(self, text: str) -> str:
        out = text
        for placeholder, value in self._by_placeholder.items():
            out = out.replace(placeholder, value)
        return out

    @staticmethod
    def _contains_word(haystack: str, needle: str) -> bool:
        """Whether `needle` occurs in `haystack` as a whole word.

        A plain `in` test was what this used to do, and it stopped the pipeline on
        ordinary English. A document-wide policy licenses the parts of a name as well as
        the whole, so the surname Le Drew puts "drew" on the guarded list, and "drew" is
        inside "withdrew". A minute recording that a delegation withdrew therefore refused
        to send, over a word that is nobody's name.

        Fail-closed means a false positive costs a run rather than a person, so this was
        never a leak. It is still a defect: a guard that refuses ordinary words trains
        whoever maintains it to route around it.

        Narrowing to a whole-word match loses nothing real. Every occurrence that is
        actually the name is still a whole word, and an occurrence that is a fragment
        inside a longer word is not the name. The boundaries are Unicode-aware, so an
        accented name is bounded correctly.
        """
        if not needle:
            return False
        pattern = rf"(?<![^\W\d_]){re.escape(needle)}(?![^\W\d_])"
        return re.search(pattern, haystack) is not None

    def guard(self, payload: str, *, where: str = "outbound request") -> None:
        """Refuse to let a raw entity leave.

        Checks the literal value, the accent-and-case-normalised value, and the
        digits-only form of anything numeric, because "709-555-0142" and "7095550142" are
        the same telephone number and only one of them is caught by a substring test.
        """
        haystack = payload
        normalised_haystack = normalise(payload)
        digits_haystack = normalise_identifier(payload)
        offenders: list[str] = []
        for value in {*self._by_placeholder.values(), *self._by_value}:
            if len(value.strip()) < _MIN_GUARDED_LENGTH:
                continue
            # A single ordinary word that the detector claimed as a person is still
            # substituted, but it is not something the guard will refuse a request over.
            #
            # The detector typed the heading word "Minutes" as a PERSON. Substitution
            # duly replaced it, and then the guard failed the request anyway, because the
            # payload's own `document_type` field says "meeting_minutes". That is this
            # module's constant, not document content, and refusing to send because of it
            # would stop the pipeline over a false positive rather than over a leak.
            #
            # The residual risk is a real person whose name is exactly a vocabulary word,
            # a Ms March or a Mr Page. They are still substituted, so nothing of theirs
            # leaves; only the assertion is relaxed, and only for one-word values.
            if " " not in value.strip() and value.strip().casefold() in SAFE_CAPITALISED:
                continue
            if self._contains_word(haystack, value):
                offenders.append(value)
                continue
            n = normalise(value)
            if n and self._contains_word(normalised_haystack, n):
                offenders.append(value)
                continue
            if any(ch.isdigit() for ch in value):
                d = normalise_identifier(value)
                if len(d) >= 6 and d in digits_haystack:
                    offenders.append(value)
        if offenders:
            raise RawEntityLeak(
                f"{len(offenders)} detected entit{'y' if len(offenders) == 1 else 'ies'} "
                f"would have left the boundary in the {where}: "
                f"{', '.join(repr(o) for o in sorted(set(offenders))[:5])}"
                f"{' and others' if len(set(offenders)) > 5 else ''}. "
                f"Nothing was sent."
            )



# --- the second pass, which does not trust the detector -----------------------------
#
# Everything above substitutes what the detector found. That is necessary and it is not
# sufficient, and the corpus-wide guard is what made the gap impossible to ignore: after
# the policy covered every detection in the document, seven persona names still reached
# the request, because the detector had not found them. Presidio's recall on PERSON is
# high, not perfect, and a privacy boundary whose strength equals a model's recall is not
# a boundary.
#
# So the outbound text gets a second pass that assumes nothing. Anything shaped like a
# proper noun, and anything shaped like an identifier, is masked unless it is on a list of
# words that carry decision-relevant meaning and cannot identify anyone: months, weekdays,
# the vocabulary of job titles and public bodies, the words of the legislation.
#
# The trade is deliberate and it is measurable in the right direction. Over-masking costs
# the model context and therefore accuracy, and the paired placeholders-against-raw-text
# ablation in PLAN.md section 1 measures exactly that cost. Under-masking sends a real
# person's name to a vendor, which is not measurable and not reversible. When one side of
# a trade shows up in a results table and the other side shows up in a breach, the choice
# makes itself.

# A name-shaped token, and the shapes here are the whole point.
#
# This pattern used to be `\b[A-Z][a-z]{2,}(?:['\u2019-][A-Z]?[a-z]+)*\b`, which is ASCII
# and assumes a name is one capital followed by lowercase letters. Three name shapes that
# are ordinary in Newfoundland and Labrador walked straight through it, and "walked through
# it" means a real person's name was handed to a model vendor:
#
#   Renee with an acute accent   no match at all. `[a-z]` does not contain the accented
#                                letter, so the match stopped after three characters and
#                                then failed its own trailing \b, because the next
#                                character is still a word character under Unicode.
#   MacDonald, McCarthy          no match at all, for the same reason in reverse: there is
#                                no word boundary between "Mac" and "Donald".
#   O'Brien                      matched "Brien" only. "O" has no lowercase run after it,
#                                so the match began after the apostrophe.
#
# None of this was theoretical and none of it was found by the corpus: the corpus had no
# accented name, no apostrophe and no Mac or Mc surname in 5,355 spans, which is why every
# test passed. Project 04 reported the same three shapes getting past their own second pass
# and said that re-running this project's evaluation would not show the difference. It did
# not, and that is what sent this pattern for a reading.
#
# The replacement matches a token of Unicode letters that may be joined by an apostrophe,
# a hyphen or a period, and leaves the decision about whether it is a name to `_is_name`,
# where it can be written in Python rather than smuggled into a character class.
_TOKEN = re.compile(r"[^\W\d_]+(?:['\u2019.\-][^\W\d_]+)*")
_SEPARATORS = re.compile(r"['\u2019.\-]")
_DIGIT_RUN = re.compile(r"\b\d[\d\s.,/-]{2,}\d\b")
_YEAR = re.compile(r"^(?:1[89]|20)\d{2}$")


def _is_name_shaped(token: str) -> bool:
    """Whether a token should be masked as a possible name.

    Three conditions, and each one is load-bearing:

      * It starts with an uppercase letter. Lowercase prose is not a name.
      * It is not entirely uppercase. An all-capitals token is a heading or an acronym
        ("NOTES", "ATIPPA", "MCP"), and masking those would leave the model reading a page
        of boxes. This is also what the old pattern did, by requiring a lowercase run, and
        it is kept deliberately rather than by accident.
      * It has at least three letters. Initials and "St" identify nobody on their own.

    Unicode-aware throughout: `str.isupper` and `str.islower` know about accented letters
    and the character classes do not.
    """
    letters = [c for c in token if c.isalpha()]
    if len(letters) < 3:
        return False
    if not letters[0].isupper():
        return False
    return any(c.islower() for c in letters)


def _is_safe(token: str) -> bool:
    """Whether a name-shaped token is on the list of words that identify nobody.

    Checked part by part as well as whole, so that a hyphenated or apostrophised
    compound of safe words stays readable ("Newfoundland-Labrador") while a compound with
    any unknown part is masked entirely ("Anne-Marie", "Coady-Vokey"). Masking the whole
    compound rather than the unknown part is the safe direction: half a hyphenated surname
    is still a surname.
    """
    if token.casefold() in SAFE_CAPITALISED:
        return True
    parts = [p for p in _SEPARATORS.split(token) if p]
    return len(parts) > 1 and all(p.casefold() in SAFE_CAPITALISED for p in parts)

UNKNOWN_NAME = "[NAME?]"
UNKNOWN_NUMBER = "[NUMBER?]"

# Grouped rather than one blob so that a reader can see what each group is for, and
# split from variables rather than from a literal so the intent is a vocabulary list
# rather than a hard-coded tuple somebody flattened.
_SAFE_GROUPS: tuple[str, ...] = (
    # Calendar
    "January February March April May June July August September October November",
    "December Monday Tuesday Wednesday Thursday Friday Saturday Sunday",
    # The structure of a record
    "Subject Date Sent From Cc Bcc Attention Dear Sincerely Regards Yours Encl",
    "Memorandum Minutes Present Regrets Confidential Draft Copy Page Tab Schedule",
    "Attachment Enclosure Appendix Note Notes Report Summary Findings Recommendation",
    "Background Action Contact Telephone Email Address Client File Case Reference",
    "Department Division Branch Section Office Ministry Minister Deputy Assistant",
    "Director Manager Officer Analyst Coordinator Supervisor Investigator Inspector",
    "Adjudicator Registrar Commissioner Solicitor Counsel Superintendent Principal",
    # Public bodies and roles
    "Worker Practitioner Physician Nurse Receptionist Administrator Clerk Executive",
    "Senior Policy Program Programme Regional Corporate Operations Services Service",
    "Health Community Justice Safety Children Seniors Social Development Digital",
    "Government Human Resources Committee Board Council Commission Agency Authority",
    "Newfoundland Labrador Canada Canadian Province Provincial Federal",
    "Access Information Protection Privacy Act Section Subsection Part Regulation",
    "Court Supreme Trial Division Commissioner Review Appeal Request Applicant",
    "Requester Respondent Complainant Witness Third Party Public Body Record Records",
    "The This That These Those There Their They When Where While With Without What",
    "Which Who Whose How Because However Although Therefore Please Thank Thanks If",
    "In On At For And But Not No Yes Our Your My His Her Its All Any Some Each Both",
    "After Before During Following Further Under Over Above Below Between Within",
    # Legislation and process
    "Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Twenty Thirty Sixty",
    "One First Second Third Fourth Fifth Last Next Previous Same Other Another New",
    "Approximately About Around Nothing Something Anything Everything Someone Anyone",
    "Everyone Nobody Both Either Neither",
)

# Capitalised words that are not names and that the decision turns on: a job title, the
# name of a public body, a month, the words of a statute's title. Losing these would
# leave the model nothing to reason from, and none of them identifies an individual.
SAFE_CAPITALISED = frozenset(
    word.casefold() for group in _SAFE_GROUPS for word in group.split()
)

def scrub_unrecognised(text: str) -> str:
    """Mask anything name-shaped or identifier-shaped that the policy did not already
    replace. Detector-independent by design; see the note above."""
    if not text:
        return text

    def mask_word(m: re.Match[str]) -> str:
        word = m.group(0)
        if not _is_name_shaped(word):
            return word
        return word if _is_safe(word) else UNKNOWN_NAME

    out = _TOKEN.sub(mask_word, text)

    def mask_number(m: re.Match[str]) -> str:
        raw = m.group(0)
        # A bare year is left alone: whether someone died more than twenty years ago is a
        # taxonomy question (K4) and the year is what answers it. A year identifies nobody.
        if _YEAR.match(raw.strip()):
            return raw
        return UNKNOWN_NUMBER

    return _DIGIT_RUN.sub(mask_number, out)


def outbound(text: str, policy: PlaceholderPolicy) -> str:
    """The only way free text is allowed into a request: substitute, then scrub."""
    return scrub_unrecognised(policy.apply(text))

def redact_context(ctx: ContextRecord, policy: PlaceholderPolicy) -> dict[str, object]:
    """The context record as the model sees it: structure intact, every name gone.

    Note what survives. The block kind, the document type, the presence of a title and
    where it was found, whether the register matched, how many pages the person appears
    on. That is the evidence the decision actually rests on, which is why the paired
    ablation in PLAN.md section 1 is expected to cost little. Whether it does is a
    measurement, not an assumption, and `sever eval placeholders` runs it.
    """
    return {
        "span": outbound(ctx.text, policy),
        "entity_type": ctx.entity_type.value,
        "block": ctx.block_kind.value,
        "document_type": ctx.doc_type.value,
        "page": ctx.page_number,
        "pages_in_document": ctx.pages_in_document,
        "heading": outbound(ctx.heading, policy) if ctx.heading else None,
        "sentence": outbound(ctx.sentence, policy),
        "message_index": ctx.message_index,
        "is_configured_requester": ctx.is_requester,
        "requester_match_ambiguous": ctx.is_requester_ambiguous,
        # The title is a job title, not a name, and it is the K2 signal. It is passed
        # through so the model can weigh it; a title is not personal information.
        "title_paired_with_this_person": ctx.title,
        "title_found_in": ctx.title_source,
        "mentioned_in": sorted({m.source for m in ctx.role_mentions}),
        "matches_public_register": ctx.register_match is not None,
        "appears_on_pages": list(ctx.cluster_pages),
        "distinct_surface_forms": len(ctx.cluster_surface_forms),
        "coreference_ambiguous": ctx.cluster_ambiguous,
        "other_people_in_same_sentence": len(ctx.co_mentions_in_sentence),
    }


def policy_for(
    contexts: Sequence[ContextRecord], *, also: Mapping[str, EntityType] = {}
) -> PlaceholderPolicy:
    return PlaceholderPolicy.for_detections((c.detection for c in contexts), extra=also)
