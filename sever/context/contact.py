"""A contact detail the record itself calls personal: "my personal mobile", "her home number".

An official's work telephone is released with the official (`official_capacity_contact`);
the same official's personal mobile is not, because it is information about the person
and not about the position. Nothing in the number says which it is. The words in front of
it do, and a reader goes by them.

Found on 2026-10-20 with Jev 1.14 as the model layer. In the incident reports an official
writes "My personal mobile,\\n709-555-..., is recorded here because it is the number the
ambulance service called back on". The span reached the model with the line it sits on,
which does not contain the words, and Jev called the number an official's contact (K2) at
0.51 to 0.54, seven times in 210 documents; every leak the model added at a 0.50 threshold
was this one. The rule was written after that run was scored, and PLAN.md 12.50 says so.

**What it reads.** The text before the span, back to the end of the previous sentence and
across line breaks, because the page's sentence splitter stops at a line end. The words
must end within a few characters of the span, so "my personal mobile is off; call the
office on 709-..." does not mark the office number.

**What it does not claim.** The vocabulary is "personal", "home", "private" or "own" before
a phone, mobile, cell, line, number or email, and "my mobile" or "my cell". "Her number" or
"reach me on" is not enough, because officials write both about their work lines.
"""

from __future__ import annotations

import re

from sever.ingest.document import Offsets

_PERSONAL_CONTACT = re.compile(
    r"\b(?:(?:personal|home|private|own)\s+"
    r"(?:mobile|cell(?:phone)?|(?:tele)?phone(?:\s+number)?|line|number|e-?mail(?:\s+address)?)"
    r"|my\s+(?:mobile|cell(?:phone)?))\b",
    re.IGNORECASE,
)
# What may stand between the words and the span: punctuation, a line break, "is", "was",
# "number", "no.", "at", "on".
_BETWEEN = re.compile(
    r"^[\s,:;(\-]*(?:(?:is|was|number|no\.?|at|on)[\s,:;(\-]*){0,2}$", re.IGNORECASE
)
_LOOKBACK = 120


def personal_contact_before(text: str, offsets: Offsets) -> bool:
    """Whether the record calls the contact detail at `offsets` personal, just before it."""
    window = text[max(0, offsets.start - _LOOKBACK) : offsets.start]
    for stop in (". ", ".\n", "\n\n"):
        at = window.rfind(stop)
        if at >= 0:
            window = window[at + len(stop) :]
    last = None
    for m in _PERSONAL_CONTACT.finditer(window):
        last = m
    return last is not None and _BETWEEN.match(window[last.end() :]) is not None


__all__ = ["personal_contact_before"]
