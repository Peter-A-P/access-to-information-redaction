"""What a Defence record says about the people and the strings in it.

Written on 2026-10-17 after reading what the real-record track withheld. Six Library and
Archives Canada packages of Defence records, 533 spans that could be personal information,
and the tool withheld all of them. Most of the reason was in the spans themselves:

  * **Ranks read as people.** "LCol", "Maj" and "Capt" alone were PERSON spans 42 times,
    and the rules had no idea a rank is a title, so "LCol Kromrey" was a stranger with
    nothing said about their capacity.
  * **Units and headquarters read as people.** "KAF", "OPCOM", "HSU", "CEFCOM", "TFK" and
    "J1" came back as PERSON about a hundred times. None of them is anybody.
  * **OCR noise read as people.** "wu", "za", "iy", "pour lui": fragments with no
    capital letter, which no reader would take for a name.

This module answers those three and nothing else. Two of the answers are gated on the
record being a military one, because a rank or an acronym means something only where the
forces wrote it: "Capt" in a fisheries record is a ship's master, who is a third party.

## The vocabulary was written after reading the packages it is scored on

That has to be said plainly, because it changes what the real-record number is. Until
today the six packages were a test nobody had tuned against. The rank list below is the
CAF's own and would be the same had the packages never been read, but the acronym list is
not: it is the standard short forms of the Canadian Forces of 2001 to 2014, and the ones
that made the list are the ones the packages used. The next packages added to the manifest
are the held-out check, and `results/releases.md` says so above its table.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from sever.detect.recognisers import RANK_ALTERNATION, RANK_WORD
from sever.detect.types import Detection, EntityType
from sever.ingest.document import Document, Offsets

# A record the forces produced, or one about them. Read over the whole document, because
# the institution is usually named once, on a cover sheet or a letterhead, and the ranks
# are pages later.
MILITARY_MARKERS = re.compile(
    r"National Defence|Défense nationale|Defence nationale|Canadian (?:Armed )?Forces|"
    r"Forces (?:armées )?canadiennes|forces\.gc\.ca|\bDND\b|\bMDN\b|\bCEFCOM\b|"
    r"\bCJOC\b|\bJTF[- ]?A",
)


def is_military_record(document: Document) -> bool:
    return MILITARY_MARKERS.search(document.text) is not None


# Appointments: what a person is in a headquarters rather than what rank they hold. Not
# ranks, so never a title for the person beside them, but no more a person than a rank is.
APPOINTMENTS = frozenset(
    {
        "CO", "XO", "OC", "2IC", "DCO", "CoS", "COS", "ACOS", "DCOS", "RSM", "CSM",
        "Adjt", "Comd", "Cmdt", "Padre", "OPI", "LO", "ADC", "CDS", "VCDS", "DM", "ADM",
        "Chaplain", "Aumônier", "Aumonier",
    }
)

# Unit and formation words, and the headquarters and organisations of the period. A span
# made of nothing but these names a place in the order of battle.
UNIT_WORDS = frozenset(
    {
        "HQ", "Coy", "Bn", "Bde", "Sqn", "Regt", "Wing", "Pl", "Div", "Gp", "Flt", "Det",
        "Sig", "Fd", "Amb", "Sect", "Tp", "Bty", "Unit", "Rear", "Fwd", "Integ",
        "CF", "CAF", "DND", "MDN", "NDHQ", "QGDN", "CFB", "BFC", "CEFCOM", "COMFEC", "CJOC",
        "COIC", "CANSOFCOM", "CANOSCOM", "CANADACOM", "JTF", "JTFA", "JTF-Afg", "FOI",
        "TFK", "FOK", "TFA", "KAF", "ISAF", "NATO", "OTAN", "PRT", "OMLT", "NSE", "HSS",
        "HSU", "MMU", "CFHS", "CFHSG", "CFTPO", "SWA", "ROTO", "OPCOM", "OPCON", "TACOM",
        "TACON", "NDOC", "CFNOC", "DGIC", "Afg", "Ops", "Op",
    }
)

# Staff branches: J1 to J9, G1 to G9, S1 to S9, and the same with a letter after ("J3
# Plans" is two tokens, "J6" one).
_STAFF_BRANCH = re.compile(r"^[JGSAN][1-9][A-Z]?$")

_RANKS = re.compile(rf"^(?:{RANK_ALTERNATION})$")

# A token that could be part of somebody's name: a capital and then letters, a run of
# capitals ("CARRIERE", typed that way on a routing slip), or initials ("B.F", "J.H.C.").
_NAME_SHAPED = re.compile(r"^(?:[A-ZÀ-Þ][A-Za-zÀ-ÿ'\u2019-]+|(?:[A-Z]\.?){1,4})$")
_STRIP = ".,;:()[]{}\"'\u201c\u201d\u2018\u2019\u00ab\u00bb<>|!?*"

# Function words a span may carry around its vocabulary: "the TFK Comd".
_FUNCTION_WORDS = frozenset({"the", "of", "and", "de", "du", "la", "le", "des", "et"})


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"[\s/&]+", text):
        # In the address-book form only what comes before the first "@" can be a name or
        # initials; "HQ@Ottawa-Hull" is where an account sits, not who holds it.
        token = raw.split("@", 1)[0].strip(_STRIP)
        if token:
            out.append(token)
    return out


def has_name_shaped_token(text: str) -> bool:
    """False for "wu", "pour lui", "dés 22h00", ".19(1" and "OK2": nothing in them could be
    a name, whatever a model trained on news made of them."""
    return any(_NAME_SHAPED.match(t) for t in _tokens(text))


def is_rank(token: str) -> bool:
    return _RANKS.match(token) is not None


def is_vocabulary(part: str) -> bool:
    """True when every word of `part` is a rank, an appointment or a unit."""
    return classify_person_span(part) is not None


def _is_vocabulary(token: str) -> str | None:
    """'rank', 'appointment' or 'unit' for a military vocabulary token, else None."""
    if _RANKS.match(token):
        return "rank"
    if token in APPOINTMENTS:
        return "appointment"
    if token in UNIT_WORDS or _STAFF_BRANCH.match(token):
        return "unit"
    parts = [p for p in token.split("-") if p]
    if len(parts) > 1 and all(_is_vocabulary(p) for p in parts):
        return "unit"
    return None


def classify_person_span(text: str) -> EntityType | None:
    """The type a PERSON span made only of military vocabulary should have had.

    JOB_TITLE when it holds a rank or an appointment ("TFK Comd", "Base MWO"),
    ORGANISATION when it is units and headquarters only ("XO OPCOM" is a title, "CEFCOM J1"
    is a branch). None when any token is something else, which keeps "Goudie Capt" and
    "LCol Kromrey" people.
    """
    tokens = [t for t in _tokens(text) if t not in _FUNCTION_WORDS]
    if not tokens:
        return None
    kinds = [_is_vocabulary(t) for t in tokens]
    if any(k is None for k in kinds):
        return None
    if any(k in ("rank", "appointment") for k in kinds):
        return EntityType.JOB_TITLE
    return EntityType.ORGANISATION


def screen(document: Document, detections: Sequence[Detection]) -> tuple[Detection, ...]:
    """Drop the PERSON spans that are not name-shaped at all, and re-type the ones that are
    military vocabulary in a military record.

    The first runs on every record. A span with no capital letter in it identifies nobody
    to anybody, and a box over "pour lui" costs a reviewer a decision and the requester a
    word. The second runs only where `is_military_record` says the forces wrote it.

    Before the name sweep, on purpose: a PERSON "KAF" would otherwise license every other
    "KAF" in the record as a person.
    """
    military = is_military_record(document)
    out: list[Detection] = []
    for d in detections:
        if d.entity_type is not EntityType.PERSON:
            out.append(d)
            continue
        if not has_name_shaped_token(d.text):
            continue
        retyped = classify_person_span(d.text) if military else None
        if retyped is None:
            out.append(d)
        else:
            out.append(replace(d, entity_type=retyped, recogniser=f"military:{d.recogniser}"))
    return tuple(out)


# --- what a rank says about the person beside it ---------------------------------------

_BEFORE = re.compile(rf"(?<![\w/@])({RANK_ALTERNATION})\.?\s+$")
# After the name only in the address-book form, "Gifford LCol SW@Deployed@KAF", or at the
# end of a line: in prose a word after a surname is the next word of the sentence.
_AFTER = re.compile(rf"^[ \t]+({RANK_ALTERNATION})(?=[ \t]+[A-Z]{{1,6}}@|[ \t]*(?:\n|$))")


def rank_beside(text: str, offsets: Offsets) -> str | None:
    """The rank written inside a person span, just before it, or just after it in the
    address-book form. None where there is none."""
    span = text[offsets.start : offsets.end]
    inside = RANK_WORD.search(span)
    if inside is not None:
        return inside.group(0)
    before = _BEFORE.search(text[max(0, offsets.start - 30) : offsets.start])
    if before is not None:
        return before.group(1)
    after = _AFTER.match(text[offsets.end : offsets.end + 40])
    if after is not None:
        return after.group(1)
    return None


__all__ = [
    "APPOINTMENTS",
    "MILITARY_MARKERS",
    "UNIT_WORDS",
    "classify_person_span",
    "has_name_shaped_token",
    "is_military_record",
    "is_rank",
    "is_vocabulary",
    "rank_beside",
    "screen",
]
