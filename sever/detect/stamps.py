"""The release stamp a federal institution prints on every page it discloses.

"Document disclosed under the Access to Information Act / Document divulgué en vertu de la
Loi sur l'accès à l'information" is on every page of a federal release package, and OCR
reads it a little differently each time. On the held-out packages the detector called "Loi
sur" and "Ia Loi sur" a person 26 times, so the tool proposed to withhold words of the stamp
the institution had added itself. Written 2026-10-18 from those packages, which is why it
is measured on the fresh set and not on them.

Only the stamp's own lines. A line that says "Access to Information Act" in a letter is not
a stamp, so a line qualifies only if it carries the stamp's own wording ("document disclosed
under", "document divulgué", "Loi sur l'accès") and is no longer than the stamp is. OCR
puts noise in front of it ("say Bocument divulgué ..."), so the wording may start anywhere
in the line.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from sever.detect.types import Detection
from sever.ingest.document import Document, Offsets

# OCR reads "la" as "Ia" and drops or swaps accents, so the French half is matched on the
# words that survive: "Document divulgu..." and "Loi sur ... acc...".
_STAMP_LINE = re.compile(
    r"ocument\s+disclosed\s+(?:under|by\s+the\s+ATIP)|ocument\s+divulgu|"
    r"loi\s+sur\s+\S{0,2}acc",
    re.IGNORECASE,
)
# The stamp is about 65 characters in either language; noise in front adds a few.
_STAMP_LENGTH = 90


def stamp_lines(text: str) -> list[Offsets]:
    out: list[Offsets] = []
    position = 0
    for line in text.split("\n"):
        if line.strip() and len(line.strip()) <= _STAMP_LENGTH and _STAMP_LINE.search(line):
            out.append(Offsets(position, position + len(line)))
        position += len(line) + 1
    return out


def drop_stamp_spans(
    document: Document, detections: Sequence[Detection]
) -> tuple[Detection, ...]:
    """Every detection except those inside a release stamp's lines."""
    lines = {p.number: stamp_lines(p.text) for p in document}
    return tuple(
        d for d in detections if not any(d.offsets.overlaps(s) for s in lines.get(d.page, ()))
    )


__all__ = ["drop_stamp_spans", "stamp_lines"]
