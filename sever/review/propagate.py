"""Withhold it once, and it is withheld everywhere it appears in the record.

Asked for by Peter on 2026-10-18, after the third reviewer. In a real file the same name,
email address or health card number appears many times, and a reviewer who withholds it
once means it everywhere. Without this they do it again by hand on every page, and the
instance they miss is a leak: one of reviewer 3's nine unaided misses was a delegate's full
name the second time it appeared.

The rules, each of which is a decision rather than a default:

  * **Withholding spreads; releasing never does.** The same name can be an official signing
    on page 1 and a complainant on page 4. Withholding it everywhere costs, at worst, a box
    the reviewer can lift; releasing it everywhere could put a third party's name in a
    stranger's hands.
  * **Exact values only.** A name spreads only as a whole name of two words or more,
    matched ignoring case, accents and line breaks; "Wong" alone does not, because another
    Wong may be somebody else. An identifier (a telephone, health card, insurance or file
    number) matches on its letters and digits, so "709-555-0142" finds "709 555 0142". An
    email address matches whole.
  * **Never over a reviewer's decision.** An occurrence the reviewer has already acted on,
    or that overlaps a span they acted on, is left exactly as they left it. An occurrence
    the tool proposed to release is withheld, and shows as withheld, so the reviewer can
    see it and lift it.
  * **Logged like any other decision.** Each occurrence is its own row in the audit log,
    with the reason naming where the original decision was made, so the log says which
    boxes a person drew and which followed from one. A spread row never spreads again.
  * **Off in the reviewer study.** Three reviewers were timed without it; a fourth with it
    would not be comparable.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sever.decide.pipeline import Proposal
from sever.ingest.document import Document, Offsets

PROPAGATED_REASON = "Withheld because the same value was withheld"

# An identifier is a value with at least this many digits. Fewer and "page 12" or "s. 19"
# would spread.
_MIN_DIGITS = 5
_SEPARATORS = r"[\s\-.()/]*"
_NAME_WORD = re.compile(r"[^\W\d_]{2,}")


def _fold_char(ch: str) -> str:
    """One character, lower-cased with its accent removed, and always one character, so
    offsets in the folded text are offsets in the page."""
    base = unicodedata.normalize("NFKD", ch)[:1] or ch
    low = base.lower()
    return low if len(low) == 1 else ch


def fold(text: str) -> str:
    return "".join(_fold_char(c) for c in text)


@dataclass(frozen=True, slots=True)
class Occurrence:
    page: int
    offsets: Offsets


def value_pattern(value: str) -> re.Pattern[str] | None:
    """How to find `value` elsewhere in the record, or None when it is not a value that
    spreads (a single word, a short number, a fragment)."""
    stripped = value.strip()
    if not stripped:
        return None
    alnum = [c for c in stripped if c.isalnum()]
    digits = sum(c.isdigit() for c in alnum)
    if "@" in stripped:
        body = re.escape(fold(stripped))
        return re.compile(rf"(?<![\w.@-]){body}(?![\w@-]|\.\w)")
    if digits >= _MIN_DIGITS:
        body = _SEPARATORS.join(re.escape(fold(c)) for c in alnum)
        return re.compile(rf"(?<![0-9a-z]){body}(?![0-9a-z])")
    words = stripped.split()
    if digits or len(words) < 2 or sum(1 for w in words if _NAME_WORD.search(w)) < 2:
        return None
    body = r"\s+".join(re.escape(fold(w)) for w in words)
    # Not inside a longer name: "Odette Tulk-Byrne" and "O'Odette Tulk" are someone else.
    return re.compile(rf"(?<![\w'\u2019-]){body}(?!\w|[-'\u2019]\w)")


def occurrences(document: Document, value: str) -> tuple[Occurrence, ...]:
    pattern = value_pattern(value)
    if pattern is None:
        return ()
    out: list[Occurrence] = []
    for page in document:
        for m in pattern.finditer(fold(page.text)):
            out.append(Occurrence(page.number, Offsets(m.start(), m.end())))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Spread:
    """One occurrence to withhold, and how: approving the tool's span where it is exactly
    the occurrence, adding a span where the tool drew none."""

    page: int
    offsets: Offsets
    proposal: Proposal | None


def plan(
    document: Document,
    value: str,
    *,
    source: Occurrence,
    proposals: Sequence[Proposal],
    acted: Mapping[int, Sequence[Offsets]],
) -> tuple[Spread, ...]:
    """Every other occurrence of `value` that should now be withheld.

    `acted` is, per page, every span the reviewer has already acted on or added. An
    occurrence overlapping any of them is skipped, which also skips the source itself.
    """
    by_page: dict[int, list[Proposal]] = {}
    for p in proposals:
        by_page.setdefault(p.page, []).append(p)
    out: list[Spread] = []
    for occ in occurrences(document, value):
        if occ.page == source.page and occ.offsets.overlaps(source.offsets):
            continue
        if any(occ.offsets.overlaps(a) for a in acted.get(occ.page, ())):
            continue
        exact = next(
            (p for p in by_page.get(occ.page, ()) if p.detection.offsets == occ.offsets), None
        )
        out.append(Spread(occ.page, occ.offsets, exact))
    return tuple(out)


__all__ = [
    "PROPAGATED_REASON",
    "Occurrence",
    "Spread",
    "fold",
    "occurrences",
    "plan",
    "value_pattern",
]
