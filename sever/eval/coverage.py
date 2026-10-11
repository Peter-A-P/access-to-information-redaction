"""Whether a box withholds a span: every letter and digit, or a remainder that names nobody.

One rule for every number this repository publishes, written once, because until
2026-10-10 there were two. The reviewer study counted a must-redact span as leaked unless
every letter and digit of it was under a withholding decision. The headline tables matched
each label to the proposal that overlapped it most and asked whether that one withheld, so
a box over nine digits of a twelve-digit MCP number, or over "Coordinator" alone in "Access
and Privacy Coordinator", counted as withholding the whole span. Reviewer 1 found the first
of those on their own screen.

**The rule.** A must-redact span is withheld when every letter and digit of it is under
some withholding box, or when what is left showing identifies nobody. A must-keep span is
over-redacted when any letter or digit of it is under a withholding box.

**What identifies nobody**, both set by reviewer 1 on 2026-10-10 after the run they change,
which is why the study keeps its strict column beside them:

  * A number of nine or more digits with at most `FRAGMENT_DIGITS` of them showing. Three
    digits of a twelve-digit health number identify nobody; card masking shows four.
  * A job title whose role word is withheld, leaving a qualifier or a unit: "Access and
    Privacy" beside a severed "Coordinator", "Corporate Services" beside a severed
    "Manager". A function or a unit is shared by several people; the whole position names
    its one holder. The role word is `ROLE_WORD` in the recognisers, the title without its
    qualifier or portfolio.

Nothing else qualifies. A surname beside a severed forename names someone, and so does most
of an employee number.
"""

from __future__ import annotations

from collections.abc import Sequence

from sever.corpus.labels import LabelledSpan

FRAGMENT_DIGITS = 4

Spans = Sequence[tuple[int, int]]


def _under(i: int, spans: Spans) -> bool:
    return any(s <= i < e for s, e in spans)


def covered(text: str, start: int, end: int, spans: Spans) -> tuple[bool, bool]:
    """(every letter and digit covered, any letter or digit covered) for text[start:end]."""
    positions = [i for i in range(start, end) if text[i].isalnum()]
    if not positions:
        return (True, False)
    hit = [_under(i, spans) for i in positions]
    return (all(hit), any(hit))


def is_number_fragment(text: str, start: int, end: int, spans: Spans) -> bool:
    """A number of nine or more digits with between one and `FRAGMENT_DIGITS` showing."""
    chars = [i for i in range(start, end) if text[i].isalnum()]
    if len(chars) < 9 or not all(text[i].isdigit() for i in chars):
        return False
    showing = sum(1 for i in chars if not _under(i, spans))
    return 0 < showing <= FRAGMENT_DIGITS


def is_title_qualifier(text: str, start: int, end: int, spans: Spans) -> bool:
    """A job title whose role word is withheld. False when no role word is found."""
    from sever.detect.recognisers import ROLE_WORD

    title = text[start:end]
    role = ROLE_WORD.search(title)
    if role is None:
        return False
    role_chars = [start + i for i in range(*role.span()) if title[i].isalnum()]
    return all(_under(i, spans) for i in role_chars)


def is_partial_that_identifies_nobody(label: LabelledSpan, text: str, spans: Spans) -> bool:
    """`text` is the page; `spans` the withholding boxes on it."""
    start, end = label.offsets.start, label.offsets.end
    if (label.field_name or "").endswith(".title"):
        return is_title_qualifier(text, start, end, spans)
    return is_number_fragment(text, start, end, spans)


def withheld(label: LabelledSpan, text: str, spans: Spans, *, must_redact: bool) -> bool:
    """The one rule. For a must-redact span: all of it, or a remainder that names nobody.
    For anything else: any of it, because any box over a must-keep span costs the requester."""
    full, touched = covered(text, label.offsets.start, label.offsets.end, spans)
    if not must_redact:
        return touched
    return full or is_partial_that_identifies_nobody(label, text, spans)
