"""Detector recall per entity type, measured against labels known by construction.

Project 04 shipped `boundary.redact` and said plainly that precision and recall per entity
type were not measured. This module measures the recall half, because this project is the
one place in the portfolio that can: every span in its corpus was inserted by a generator
that recorded exactly what it inserted and where, so a miss is a fact rather than a
judgement, and there are thousands of them.

What is and is not claimed here, stated once:

  * **Recall is measured and is sound.** The denominator is every value the generator
    inserted. A labelled span with no overlapping detection is a miss, full stop.
  * **Precision is not claimed.** The labels cover inserted values only. The prose around
    them is literal template text containing real organisations, places and dates that
    nobody labelled, so a detection with no label is usually a correct detection of
    something unlabelled rather than a false positive. Unlabelled detections are counted
    and broken down by recogniser, and called what they are.
  * **A synthetic corpus flatters a detector in one direction and not the other.** The
    values are generated, so they are well formed: a real record has a telephone number
    typed with a stray space and a name with an accent dropped. Recall here is therefore an
    upper bound on recall in the field. It is still the right number for comparing two
    detectors, which is what it is used for.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sever.corpus.generate import Corpus
from sever.detect.types import Detection, Detector, EntityType
from sever.eval.confusion import Interval, _rate

# The entity type each persona field is an instance of. The generator knows what it
# inserted, so this is a lookup rather than an inference.
FIELD_TYPES: dict[str, EntityType] = {
    "full_name": EntityType.PERSON,
    "given_name": EntityType.PERSON,
    "surname": EntityType.PERSON,
    "home_address": EntityType.ADDRESS,
    "office_address": EntityType.ADDRESS,
    "postal_code": EntityType.POSTAL_CODE,
    "personal_email": EntityType.EMAIL,
    "work_email": EntityType.EMAIL,
    "personal_phone": EntityType.PHONE,
    "work_phone": EntityType.PHONE,
    "date_of_birth": EntityType.DATE_OF_BIRTH,
    "date_of_death": EntityType.DATE,
    "mcp": EntityType.HEALTH_NUMBER,
    "sin": EntityType.SIN,
    "file_number": EntityType.FILE_NUMBER,
    "employee_id": EntityType.EMPLOYEE_ID,
    "title": EntityType.JOB_TITLE,
    "organisation": EntityType.ORGANISATION,
    "town": EntityType.LOCATION,
}


def field_type(field_name: str | None) -> EntityType | None:
    """The entity type behind a label's `role.field` string."""
    if not field_name:
        return None
    return FIELD_TYPES.get(field_name.rsplit(".", 1)[-1])


@dataclass(frozen=True, slots=True)
class SpanFound:
    doc_id: str
    kind: EntityType
    text: str
    found: bool
    # Set when found: which recogniser claimed it, and what type it called it.
    recogniser: str | None = None
    called: EntityType | None = None
    # True when the detection covers the whole labelled value, not merely part of it.
    #
    # Worth its own column, because overlap grading is lenient in a way that matters here.
    # Presidio finds "Bannerman Street" inside the labelled "14 Bannerman Street". That
    # overlaps, so it counts as found, and the box drawn over it releases the house number.
    # A partially covered address, name or identifier is a leak wearing a redaction, and a
    # recall figure on its own cannot see it.
    fully_covered: bool = False

    @property
    def typed_correctly(self) -> bool:
        return self.found and self.called is self.kind


@dataclass
class DetectorReport:
    detector: str
    spans: list[SpanFound] = field(default_factory=list)
    unlabelled: dict[str, int] = field(default_factory=dict)
    documents: int = 0

    def kinds(self) -> tuple[EntityType, ...]:
        return tuple(sorted({s.kind for s in self.spans}, key=lambda k: k.value))

    def recall(self, kind: EntityType | None = None) -> Interval:
        pool = [s for s in self.spans if kind is None or s.kind is kind]
        return _rate(_as_outcomes(pool), lambda o: o.found, seed=20270816)

    def coverage(self, kind: EntityType | None = None) -> Interval:
        """The share of labelled values a detection covers *entirely*. At most recall, and
        the gap between the two is where partial boxes release the rest of the value."""
        pool = [s for s in self.spans if kind is None or s.kind is kind]
        return _rate(_as_outcomes(pool), lambda o: o.fully_covered, seed=20270816)

    def type_accuracy(self, kind: EntityType | None = None) -> Interval:
        """Of the spans found, the share the detector also gave the right type. A span
        found but typed as a LOCATION when it is an ADDRESS is still redactable, so this is
        reported beside recall rather than folded into it."""
        pool = [s for s in self.spans if s.found and (kind is None or s.kind is kind)]
        return _rate(_as_outcomes(pool), lambda o: o.typed_correctly, seed=20270816)

    def misses(self, kind: EntityType) -> list[SpanFound]:
        return [s for s in self.spans if s.kind is kind and not s.found]

    def to_markdown(self) -> str:
        lines = [
            f"**Detector:** `{self.detector}`, over {self.documents} documents and "
            f"{len(self.spans)} inserted values whose type the generator recorded.",
            "",
            "| Entity type | Values | Recall | Fully covered | Typed correctly |",
            "|---|---:|---|---|---|",
        ]
        for kind in self.kinds():
            pool = [s for s in self.spans if s.kind is kind]
            lines.append(
                f"| `{kind.value}` | {len(pool)} | {self.recall(kind)} | "
                f"{self.coverage(kind)} | {self.type_accuracy(kind)} |"
            )
        lines += [
            f"| **all** | **{len(self.spans)}** | **{self.recall()}** | "
            f"**{self.coverage()}** | **{self.type_accuracy()}** |",
            "",
            f"Unlabelled detections: {sum(self.unlabelled.values())}. These are mostly "
            "correct detections of literal template text (real organisations, places and "
            "dates) that carries no label, not false positives; precision is not claimed.",
            "",
        ]
        return "\n".join(lines)


class _Outcome:
    """Adapts a SpanFound to what the shared cluster bootstrap expects."""

    __slots__ = ("doc_id", "found", "fully_covered", "typed_correctly")

    def __init__(self, s: SpanFound) -> None:
        self.doc_id = s.doc_id
        self.found = s.found
        self.fully_covered = s.fully_covered
        self.typed_correctly = s.typed_correctly


def _as_outcomes(spans: Sequence[SpanFound]) -> list[_Outcome]:
    return [_Outcome(s) for s in spans]


def evaluate(detector: Detector, corpus: Corpus) -> DetectorReport:
    report = DetectorReport(
        detector=getattr(detector, "name", type(detector).__name__),
        documents=len(corpus),
    )
    for item in corpus:
        doc = item.rendered.document
        detections: tuple[Detection, ...] = tuple(detector.detect(doc))
        claimed: set[tuple[int, int, int]] = set()

        for label in item.rendered.labels:
            kind = field_type(label.field_name)
            if kind is None:
                continue
            best: Detection | None = None
            best_overlap = 0
            for d in detections:
                if d.page != label.page:
                    continue
                hit = d.offsets.intersection(label.offsets)
                if hit is not None and len(hit) > best_overlap:
                    best, best_overlap = d, len(hit)
            if best is not None:
                claimed.add(best.key)
            report.spans.append(
                SpanFound(
                    doc_id=doc.doc_id,
                    kind=kind,
                    text=label.text,
                    found=best is not None,
                    recogniser=best.recogniser if best else None,
                    called=best.entity_type if best else None,
                    fully_covered=best is not None and best.offsets.contains(label.offsets),
                )
            )

        for d in detections:
            if d.key not in claimed:
                report.unlabelled[d.recogniser] = report.unlabelled.get(d.recogniser, 0) + 1
    return report


def compare(reports: Sequence[DetectorReport]) -> str:
    """Two or more detectors side by side, per entity type."""
    kinds: list[EntityType] = []
    for r in reports:
        for k in r.kinds():
            if k not in kinds:
                kinds.append(k)
    kinds.sort(key=lambda k: k.value)

    header = "| Entity type | Values | " + " | ".join(f"`{r.detector}`" for r in reports) + " |"
    rule = "|---|---:|" + "---|" * len(reports)
    lines = [header, rule]
    for kind in kinds:
        counts = {len([s for s in r.spans if s.kind is kind]) for r in reports}
        n = max(counts) if counts else 0
        cells = " | ".join(str(r.recall(kind)) for r in reports)
        lines.append(f"| `{kind.value}` | {n} | {cells} |")
    cells = " | ".join(f"**{r.recall()}**" for r in reports)
    lines.append(f"| **all** | **{len(reports[0].spans)}** | {cells} |")
    return "\n".join(lines)
