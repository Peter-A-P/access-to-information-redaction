"""Pattern recognisers for the identifiers a general PII engine does not know about.

Presidio finds names, emails and phone numbers. It does not know that HCS-2024-0881 is a
case file number, that "MCP 123 456 789 012" is a Newfoundland and Labrador medical care
plan number, or that EMP-40912 is an employee identifier. Those are exactly the strings an
access-to-information analyst spends the day on, and the smoke test in this project's
first hour had Presidio classify a file number as a LOCATION.

Each recogniser is a regular expression plus a confidence. The confidences are not tuned
here: they are starting values, and `sever eval detector` reports precision and recall per
recogniser on the labelled corpus so they can be set against evidence rather than taste.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from sever.detect.types import EntityType


@dataclass(frozen=True, slots=True)
class PatternRecogniser:
    name: str
    entity_type: EntityType
    pattern: re.Pattern[str]
    score: float
    # When set, the match only counts if one of these words appears within
    # `context_window` characters before it. Bare digit runs are ambiguous; "SIN 046 454
    # 286" is not.
    context_words: tuple[str, ...] = ()
    context_window: int = 40
    # The capture group holding the value, when the pattern needs to match a label it does
    # not want to redact. Group 0 is the whole match.
    group: int = 0

    def finditer(self, text: str) -> Iterator[tuple[int, int, str]]:
        for m in self.pattern.finditer(text):
            start, end = m.span(self.group)
            if start < 0:
                continue
            if self.context_words and not self._has_context(text, m.start()):
                continue
            yield start, end, text[start:end]

    def _has_context(self, text: str, at: int) -> bool:
        window = text[max(0, at - self.context_window) : at].lower()
        return any(w in window for w in self.context_words)


def _ci(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Newfoundland and Labrador MCP numbers are twelve digits, conventionally grouped in
# threes. The context requirement is doing real work: twelve grouped digits also describe
# a phone number written oddly and a purchase order. The window is a sentence rather than
# a few words, because "MCP number, taken for the ambulance service, is 404 474 556 704"
# puts the label 48 characters before the value; at 40 the number went unseen and the SIN
# pattern took its first nine digits (found by reviewer 1, 2026-10-10).
MCP_NUMBER = PatternRecogniser(
    name="nl_mcp_number",
    entity_type=EntityType.HEALTH_NUMBER,
    pattern=re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}[ -]?\d{3}\b"),
    score=0.85,
    context_words=("mcp", "medical care plan", "health card", "health number", "mcp#"),
    context_window=80,
)

# A social insurance number is nine digits in threes. Bare nine-digit runs are far too
# common to redact unconditionally, so this needs either the label or the grouping. Never
# nine digits out of a longer grouped run: a span that cuts a number releases the rest of
# it, which is how the last three digits of an MCP number reached a released page.
SIN_NUMBER = PatternRecogniser(
    name="sin",
    entity_type=EntityType.SIN,
    pattern=re.compile(r"(?<!\d[ -])\b\d{3}[ -]\d{3}[ -]\d{3}\b(?![ -]?\d)"),
    score=0.8,
)
SIN_LABELLED = PatternRecogniser(
    name="sin_labelled",
    entity_type=EntityType.SIN,
    pattern=_ci(r"\b(?:sin|social insurance(?: number)?)\s*[:#]?\s*(\d{3}[ -]?\d{3}[ -]?\d{3})\b"),
    score=0.95,
    group=1,
)

# Departmental file and case numbers: two to five letters, a year, a sequence. This is the
# shape used across the synthetic corpus and it matches the published federal releases'
# request numbers (A-2023-00412) as well.
FILE_NUMBER = PatternRecogniser(
    name="file_number",
    entity_type=EntityType.FILE_NUMBER,
    pattern=re.compile(r"\b[A-Z]{1,5}-(?:19|20)\d{2}-\d{3,6}\b"),
    score=0.9,
)
CASE_NUMBER = PatternRecogniser(
    name="case_number",
    entity_type=EntityType.CASE_NUMBER,
    # Two guards on the label word, and each was a bug before it was a guard.
    #
    # The trailing \b: without it "ref" matched inside "referred" and the group captured
    # "erred" as a case number, drawing a redaction box over the middle of an ordinary
    # word. Invisible until a better language model stopped claiming the surrounding span.
    #
    # The lookahead: a case number contains a digit. Without it the heading "CASE NOTES"
    # matched and "NOTES" was proposed as a case number, as were "case REVIEW" and "file
    # REPORT". Found on the first live model run, which was the first time anything read
    # the proposals one at a time. Project 04's equivalent patterns carry the same
    # lookahead and have neither bug; this one was fixed after checking against theirs.
    pattern=_ci(
        r"\b(?:case|file|reference|ref\.?|request)\b\s*(?:no\.?|number|#)?\s*[:#]?\s*"
        r"((?=[A-Z0-9\-/]*\d)[A-Z0-9][A-Z0-9\-/]{4,20})\b"
    ),
    score=0.8,
    group=1,
)

EMPLOYEE_ID = PatternRecogniser(
    name="employee_id",
    entity_type=EntityType.EMPLOYEE_ID,
    pattern=_ci(r"\b(?:emp(?:loyee)?|staff|payroll)\s*(?:id|no\.?|number|#)?\s*[:#-]?\s*([A-Z]{0,3}-?\d{4,8})\b"),
    score=0.85,
    group=1,
)

# Email addresses. Presidio has a recogniser for these and it is not enough: it missed
# "aaronpenashue@gov.nl.ca.example" outright, classifying only the "gov.nl.ca" inside it as
# a URL. Multi-label government domains are exactly the ones that appear in these records,
# and a missed work address is a leak, so the pattern here is deliberately permissive about
# the domain and the overlap rule lets it win over Presidio's URL claim.
EMAIL = PatternRecogniser(
    name="email",
    entity_type=EntityType.EMAIL,
    pattern=re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    score=0.95,
)

# Canadian postal codes. Format is strict enough to stand alone.
POSTAL_CODE = PatternRecogniser(
    name="postal_code",
    entity_type=EntityType.POSTAL_CODE,
    pattern=re.compile(r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b"),
    score=0.9,
)

# Street addresses. Loose on purpose: a missed address is a leak and a false positive is
# a K6 the decision layer discards cheaply.
STREET_ADDRESS = PatternRecogniser(
    name="street_address",
    entity_type=EntityType.ADDRESS,
    pattern=_ci(
        r"\b\d{1,5}[A-Z]?\s+(?:[A-Z][\w'.-]*\s+){0,3}"
        r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|drive|dr\.?|place|pl\.?|lane|ln\.?|"
        r"crescent|cres\.?|boulevard|blvd\.?|court|ct\.?|way|terrace|highway|hwy\.?)\b"
    ),
    # 0.75 is the honest confidence for a loose pattern, and it can stay honest.
    #
    # It was briefly raised to 0.9 as a workaround: project 04's analyzer resolved an
    # overlap by score first, so Presidio's LOCATION "Bannerman Street" at 0.85 beat this
    # pattern's "14 Bannerman Street", and the house number went into the released record.
    # boundary 0.5.1 resolves containment before score, so the longer span wins on being
    # the longer span rather than on an inflated number, and the workaround is gone.
    # sever's own resolver never had the problem: it orders by specificity, where ADDRESS
    # outranks LOCATION regardless of score.
    score=0.75,
)

DATE_OF_BIRTH = PatternRecogniser(
    name="date_of_birth",
    entity_type=EntityType.DATE_OF_BIRTH,
    pattern=_ci(
        r"\b(?:d\.?o\.?b\.?|date of birth|born(?: on)?)\s*[:#]?\s*"
        r"((?:\d{4}-\d{2}-\d{2})|(?:\d{1,2}\s+\w+\s+\d{4})|(?:\w+\s+\d{1,2},?\s+\d{4}))"
    ),
    score=0.9,
    group=1,
)

BANK_ACCOUNT = PatternRecogniser(
    name="bank_account",
    entity_type=EntityType.FINANCIAL,
    pattern=_ci(r"\b(?:account|acct\.?|transit|institution)\s*(?:no\.?|number|#)?\s*[:#]?\s*(\d{5,12})\b"),
    score=0.8,
    group=1,
)

# The role word of a job title, without a portfolio or a qualifier: "Coordinator" in "Access
# and Privacy Coordinator", "Minister" in "Minister of Health". Scoring reads it to decide
# whether a partly withheld title still identifies anyone (sever.eval.coverage); the
# recogniser below matches the whole title around it.
_ROLE = (
    r"assistant deputy minister|deputy minister|minister|director(?: of [A-Z][\w ]{2,30})?|"
    r"regional director|executive director|assistant director|manager|senior manager|"
    r"coordinator|co-ordinator|supervisor|analyst|policy analyst|senior policy analyst|"
    r"program officer|programme officer|officer|administrator|clerk|inspector|"
    r"investigator|adjudicator|registrar|commissioner|solicitor|counsel|"
    r"chief executive officer|chief[\w ]{0,20}officer|superintendent|principal|"
    r"social worker|case worker|nurse practitioner|physician|receptionist"
)
ROLE_WORD = _ci(rf"\b(?:{_ROLE})\b")

# Job titles. Not personal information in themselves, but the decision layer needs them:
# a title next to a name in a signature block is the strongest K2 signal there is.
#
# The whole title, not its last word (2026-10-10). A party's title in a confidential
# complaint is withheld, and a box over "Coordinator" that leaves "Access and Privacy"
# showing is a box drawn short, which reviewer 1 approved as drawn. So the multi-word titles
# the corpus uses come first, and a minister's portfolio is part of the title, read as
# capitalised words only (`(?-i:...)`), so that "the Minister of Health said" stops at
# "Health".
_PORTFOLIO = r"(?: of (?-i:[A-Z]\w+(?:,? (?:and )?[A-Z]\w+)*))?"
JOB_TITLE = PatternRecogniser(
    name="job_title",
    entity_type=EntityType.JOB_TITLE,
    pattern=_ci(
        r"\b(?:access and privacy coordinator|information and privacy commissioner|"
        rf"assistant deputy minister{_PORTFOLIO}|deputy minister{_PORTFOLIO}|"
        rf"minister{_PORTFOLIO}|{_ROLE})\b"
    ),
    score=0.7,
)

# Family relationships. "Partner" and "child" are left out: both are ordinary words in
# government prose (partner organisations, child care) far more often than they point at
# one person, and a term that withholds by default should not fire on the generic sense.
KINSHIP = PatternRecogniser(
    name="kinship",
    entity_type=EntityType.KINSHIP,
    pattern=_ci(
        r"\b(?:siblings?|brothers?|sisters?|mother|father|parents?|sons?|daughters?|"
        r"spouse|husband|wife|grand(?:mother|father|parent|son|daughter)s?|aunt|uncle|"
        r"nieces?|nephews?|cousins?|(?:mother|father|brother|sister|son|daughter)-in-law|"
        r"step(?:mother|father|son|daughter|brother|sister)s?)\b"
    ),
    score=0.6,
)

DEFAULT_RECOGNISERS: tuple[PatternRecogniser, ...] = (
    EMAIL,
    SIN_LABELLED,
    SIN_NUMBER,
    MCP_NUMBER,
    FILE_NUMBER,
    CASE_NUMBER,
    EMPLOYEE_ID,
    POSTAL_CODE,
    STREET_ADDRESS,
    DATE_OF_BIRTH,
    BANK_ACCOUNT,
    JOB_TITLE,
    KINSHIP,
)


def run(
    text: str, recognisers: Sequence[PatternRecogniser] = DEFAULT_RECOGNISERS
) -> list[tuple[int, int, str, PatternRecogniser]]:
    """Every match from every recogniser, unsorted and possibly overlapping. Overlap
    resolution belongs to the engine, which also has the Presidio results to weigh."""
    out: list[tuple[int, int, str, PatternRecogniser]] = []
    for r in recognisers:
        for start, end, matched in r.finditer(text):
            out.append((start, end, matched, r))
    return out
