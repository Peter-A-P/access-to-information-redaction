"""How old a record is, and how old the people in it are: what the archival rule reads.

Written 2026-10-18 after the held-out release packages. Library and Archives Canada released
"son", "wife" and the names of a Chinese immigration case file's family, and the tool
withheld all of it. Federally the archives may disclose personal information once 110 years
have elapsed since the individual's birth (Privacy Regulations, s. 6(c), reached through
Privacy Act 8(3) and Access to Information Act 19(2)(c)); that is taxonomy code K7.

The rule needs a year of birth, and the record has to supply it. Two ways it does, and this
module reads only those:

  * **The page's own date.** Everyone a page names was born before the page was written. So
    a page whose latest year is 1913 names nobody born after 1913, and in 2026 every one of
    them is past 110. The latest year anywhere on the page is used, not the earliest: a
    1950 letter that recalls a 1913 landing is a 1950 page, and a later year read off a
    stamp or a file number only makes the rule more careful.
  * **A birth stated beside the name.** "Wong Ding Yip, born 1897", or "Wong Ding Yip, aged
    54" on a page dated 1951, which puts the birth no later than 1951 minus 54. Only
    directly after the name, so that "Wong, aged 54, and his son Ping" gives the father an
    age and not the son.

What it does not read, on purpose: a file title's date range, which is metadata about the
file and not the date of a page; and an age anywhere else in the sentence. Both would decide
more spans, and both would sometimes decide them about the wrong person.
"""

from __future__ import annotations

import re

from sever.ingest.document import Offsets

ARCHIVAL_YEARS = 110

# A plausible year: 1800 to 2099, standing alone.
# The second year of "1913-1962" counts: a hyphen before a year is a range far more often
# than an identifier, and the later year is the careful one to keep.
_YEAR = re.compile(r"(?<![\w])(1[89]\d\d|20\d\d)(?![\w])")

# A line break is allowed inside "Gin Wah, age\n12": a typed interview wraps there.
_AGE_AFTER = re.compile(r"^[ \t]*[,(][ \t]*(?:aged?|age:?)\s*(\d{1,3})\b", re.IGNORECASE)
_BORN_AFTER = re.compile(
    r"^[ \t]*[,(]?[ \t]*(?:born|b\.)[^.\n]{0,30}?(?<!\d)(1[89]\d\d|20\d\d)(?!\d)",
    re.IGNORECASE,
)


_RANGE_START = re.compile(r"(?<!\w)(?:1[89]\d\d|20\d\d)\s*$")


def years_in(text: str, *, as_of: int) -> list[int]:
    """Every standalone year on the page up to `as_of`, leaving out identifiers."""
    out: list[int] = []
    for m in _YEAR.finditer(text):
        before = text[max(0, m.start() - 8) : m.start()].rstrip()
        # After a hyphen, only the end of a range ("1913-1962") is a year. "CH-1-1910" and
        # "A-2026-01845" are identifiers, and a year read out of one could date a 1950s
        # page to 1910 and release everyone on it.
        if before.endswith("-") and not _RANGE_START.search(before[:-1]):
            continue
        year = int(m.group(1))
        if year <= as_of:
            out.append(year)
    return out


def page_year(text: str, *, as_of: int) -> int | None:
    """The latest year on the page, or None where there is none."""
    years = years_in(text, as_of=as_of)
    return max(years) if years else None


def birth_year_beside(
    text: str, offsets: Offsets, *, page_year: int | None
) -> int | None:
    """The latest year this person can have been born, from what is written straight after
    their name: a year of birth, or an age on a page whose date is known."""
    after = text[offsets.end : offsets.end + 60]
    born = _BORN_AFTER.match(after)
    if born is not None:
        return int(born.group(1))
    age = _AGE_AFTER.match(after)
    if age is not None and page_year is not None:
        years = int(age.group(1))
        if 0 < years < 120:
            return page_year - years
    return None


_DIED = re.compile(
    r"\b(?:died|deceased|date of death|d\.)\b[^.\n]{0,20}?\b((?:1[89]|20)\d{2})(?:-\d{2}-\d{2})?\b"
    r"|\b(?:died|deceased|date of death)\b[^.]{0,30}?\b((?:1[89]|20)\d{2})\b",
    re.IGNORECASE,
)


def death_year_after(text: str, offsets: Offsets, *, others: tuple[Offsets, ...] = ()) -> int | None:
    """The year of death written after a person's name, in the same sentence.

    The sentence is read to its full stop across line breaks, because the page's sentence
    splitter stops at a line end: "Prepared by Priya Yetman,\nthen the building's
    inspector, who died on 1992-04-16." is one sentence to a reader and two to the
    splitter, and the K4 rule, reading only the first, never saw the death (24 must-release
    spans on 2026-10-20). Another person named between the name and the death owns it
    instead, so nothing is returned.
    """
    window = text[offsets.end : offsets.end + 240]
    stop = min((i for i in (window.find(". "), window.find(".\n")) if i >= 0), default=-1)
    if stop >= 0:
        window = window[: stop + 1]
    m = _DIED.search(window)
    if m is None:
        return None
    at = offsets.end + m.start()
    if any(offsets.end <= o.start < at for o in others):
        return None
    return int(m.group(1) or m.group(2))


__all__ = [
    "ARCHIVAL_YEARS",
    "birth_year_beside",
    "death_year_after",
    "page_year",
    "years_in",
]
