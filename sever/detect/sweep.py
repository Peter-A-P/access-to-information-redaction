"""Find the rest of a person once the record has named them somewhere.

A language model finds "Bernadette Le Drew" in a sentence and misses "Le Drew" on its own
in a distribution list three pages later. That is not a failure of orthography, and the
measurement in `results/names.md` is what says so: apostrophes and Mac prefixes cost almost
nothing, while a bare accented forename costs 7.4 points of person recall and a bare
two-token surname costs 6.4. The same accented characters in a surname cost 0.9. Position,
not spelling.

`tests/test_name_shapes_detected.py` has the probes. Every shape is found in prose with a
forename beside it, in a signature block, and in a distribution list. What is missed is an
unfamiliar token **standing alone**, and one honorific in front rescues all of them. The
model has learned the common names and not the uncommon ones, and it fails precisely where
there is no neighbouring evidence any model could use. A larger model does not help,
because the information is not in the sentence.

It is in the *document*, though, and that is the whole of this module. A record that names
Bernadette Le Drew once has told us that "Le Drew" is a person's name in this record. So
after the per-page detectors have run, every person they found licenses the other
occurrences of their name parts across the whole document.

This is not a new idea here, it is an old one applied in a second place.
`sever.decide.placeholders.PlaceholderPolicy.for_detections` already does exactly this for
the outbound privacy boundary, because a policy that substituted only the exact surface
form shipped the forename two sentences later. That was found by the corpus-wide leak test
in the first week. The detector had the same hole and nobody looked, because recall was
measured in aggregate and the misses were spread thinly across the low-context positions.

What this module is careful about, and why:

  * **Case-sensitive, whole-word matching.** The surname Le Drew licenses "Drew". It must
    not match "drew" the verb, nor "drew" inside "withdrew". The guard in `placeholders`
    learned the second half of that lesson the hard way and the fix is the same here.
  * **Never over an existing detection.** A swept span that overlapped a real one would
    fight it in overlap resolution and could shorten it.
  * **Vocabulary words are not swept.** The detector types the heading "Minutes" as a
    PERSON from time to time. Sweeping that would put a redaction box over the word in
    every minute of the corpus, which is a denial of service on the reviewer rather than a
    privacy gain.
  * **Parts, not just wholes, and longest first**, so "Bernadette Le Drew" is claimed as
    one span where it appears whole rather than as three.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from sever.detect.types import Detection, EntityType
from sever.ingest.document import Document, Offsets

# The confidence a swept span carries. Below the detectors' own PERSON scores on purpose:
# this is an inference from elsewhere in the document rather than a reading of the text in
# front of it, and where the two disagree about a stretch of text the direct reading should
# win. It is above `SeverDetector.min_score` so the span survives to the decision layer,
# where an unplaced person escalates rather than being released.
SWEPT_SCORE = 0.6

RECOGNISER = "name_sweep"

# Shorter than this and a "name part" is an initial or a particle, and sweeping "Le" or
# "St" across a document would mangle ordinary prose.
MIN_PART = 3


def _name_parts(name: str) -> list[str]:
    """The pieces of a detected name that may stand for the person on their own.

    Every contiguous run of tokens, not only single ones, because the surnames this module
    exists for are two tokens long. Splitting "Bernadette Le Drew" into words alone offers
    "Bernadette" and "Drew" and never "Le Drew", which is the form that actually appears in
    a distribution list. "Le" on its own is below `MIN_PART` and is correctly refused, so
    without the runs the surname would be swept as its second half and a redaction box
    would cover "Drew" and release "Le".

    Runs rather than a surname heuristic because a heuristic would have to know that "Le"
    is a particle and "Mary" in "Mary-Kate" is not, in a province with French, Irish and
    Innu naming all at once. A run is cheap, and the whole-word case-sensitive match at the
    other end is what keeps it safe.
    """
    tokens = [p.strip(".,;:'\"()") for p in name.strip().replace(",", " ").split()]
    tokens = [t for t in tokens if t]
    out = [name.strip()]
    for start in range(len(tokens)):
        for end in range(start + 1, len(tokens) + 1):
            out.append(" ".join(tokens[start:end]))
    return out


def _is_sweepable(part: str) -> bool:
    """Whether a name part may be searched for across the document."""
    from sever.decide.placeholders import NOT_NAME_PARTS, SAFE_CAPITALISED

    if len(part) < MIN_PART:
        return False
    if not part[0].isupper():
        return False
    folded = part.casefold()
    if folded in NOT_NAME_PARTS:
        return False
    # A single word that is also ordinary vocabulary: a month, a job title, the name of a
    # public body, "Minutes". Substituting it is harmless; sweeping it is not.
    return not (" " not in part and folded in SAFE_CAPITALISED)


def sweepable_parts(detections: Iterable[Detection]) -> list[str]:
    """Every surface form the document has already told us is part of a person's name,
    longest first so the longest claim is made first."""
    seen: set[str] = set()
    for d in detections:
        if d.entity_type is not EntityType.PERSON:
            continue
        for part in _name_parts(d.text):
            if _is_sweepable(part):
                seen.add(part)
    return sorted(seen, key=lambda p: (-len(p), p))


def sweep(document: Document, detections: Sequence[Detection]) -> tuple[Detection, ...]:
    """The spans a document-wide sweep adds to what the page detectors found.

    Returns only the new ones; the caller merges. Nothing here overlaps an existing
    detection or another swept span.
    """
    parts = sweepable_parts(detections)
    if not parts:
        return ()

    existing: dict[int, list[Offsets]] = {}
    for d in detections:
        existing.setdefault(d.page, []).append(d.offsets)

    added: list[Detection] = []
    for page in document:
        taken = list(existing.get(page.number, ()))
        text = page.text
        for part in parts:
            # Case-sensitive and whole-word. "Drew" is a surname; "drew" is a verb, and
            # "withdrew" is neither.
            pattern = rf"(?<![^\W\d_]){re.escape(part)}(?![^\W\d_])"
            for m in re.finditer(pattern, text):
                span = Offsets(m.start(), m.end())
                if any(span.overlaps(t) for t in taken):
                    continue
                taken.append(span)
                added.append(
                    Detection(
                        page=page.number,
                        offsets=span,
                        text=text[span.start : span.end],
                        entity_type=EntityType.PERSON,
                        score=SWEPT_SCORE,
                        recogniser=RECOGNISER,
                    )
                )
    return tuple(added)


RETYPED = "name_sweep:retyped"

# The types that mean "this is not information about an identifiable individual", and
# therefore the types whose rule releases the span. A name mistyped as one of these is not
# a missed detection, which recall would show, but a released one, which it would not.
_RELEASING_TYPES = frozenset({EntityType.LOCATION, EntityType.ORGANISATION})


def retype_known_people(
    document: Document, detections: Sequence[Detection]
) -> tuple[Detection, ...]:
    """Re-type a span the document has already told us is a person's name.

    Found while testing the sweep on Labrador surnames, and it is the more serious half of
    what the sweep is for. "Bernadette Tuglavina" is detected as a PERSON in the sentence
    that introduces her; the bare "Tuglavina" in the distribution list below is detected
    too, as a **LOCATION**.

    Recall cannot see this. The span is found, so it counts. What happens next is that
    `not_personal_information` fires on a LOCATION, returns K6, and K6 releases. A third
    party's surname goes into the released record wearing the reason "not information about
    an identifiable individual", which is both a leak and a false statement in the
    redaction schedule.

    The rule here is deliberately narrow: only where the existing span is **exactly** the
    same characters as a name part the document has already attributed to a person, and
    only where its current type is one that releases. Equal offsets and nothing else,
    because a name token inside a longer ADDRESS or ORGANISATION span is usually doing
    honest work there: "Hearn" inside "Hearn Building" is a place.
    """
    parts = set(sweepable_parts(detections))
    if not parts:
        return tuple(detections)
    out: list[Detection] = []
    for d in detections:
        if d.entity_type in _RELEASING_TYPES and d.text in parts:
            out.append(
                Detection(
                    page=d.page,
                    offsets=d.offsets,
                    text=d.text,
                    entity_type=EntityType.PERSON,
                    score=max(d.score, SWEPT_SCORE),
                    recogniser=RETYPED,
                )
            )
        else:
            out.append(d)
    return tuple(out)


def with_sweep(document: Document, detections: Sequence[Detection]) -> tuple[Detection, ...]:
    """`detections`, re-typed where the document contradicts them, plus what the sweep adds.

    Re-typing runs first so that the sweep does not then skip the span it would have added,
    and so that the added spans are decided by the same rule as the re-typed ones.
    """
    corrected = retype_known_people(document, detections)
    merged = [*corrected, *sweep(document, corrected)]
    return tuple(sorted(merged, key=lambda d: (d.page, d.offsets.start)))
