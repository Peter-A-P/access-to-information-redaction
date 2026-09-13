"""Ground truth: what each span in a corpus document ought to be.

A label is a claim about one span: this stretch of this page is category R1, and it is
about persona p007. The corpus generator emits labels as it renders, so they are exact by
construction rather than approximate by annotation.

Two label sources exist and they are not interchangeable, so each label says which it is:

  * CONSTRUCTED, from the generator. Complete: every span the generator inserted is
    labelled, so a span the detector finds that has no label is a detector false positive
    (or a real miss in the generator, which verification catches).
  * OBSERVED, from a published release. Incomplete by nature: what is visible in a
    released record was judged releasable by a human, so a visible span is a genuine
    must-keep, but what sits under the existing black boxes cannot be recovered and is not
    a label at all. Leak rate is therefore not computable on this track, and the evaluation
    refuses to compute it rather than quietly reporting a number that means nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from sever.ingest.document import Offsets


class LabelSource(StrEnum):
    CONSTRUCTED = "constructed"
    OBSERVED = "observed"
    VERIFIED = "verified"

    @property
    def is_complete(self) -> bool:
        """True when the absence of a label means the span is not personal information.
        Only complete tracks can produce a leak rate."""
        return self in (LabelSource.CONSTRUCTED, LabelSource.VERIFIED)


@dataclass(frozen=True, slots=True)
class LabelledSpan:
    page: int
    offsets: Offsets
    text: str
    code: str
    source: LabelSource = LabelSource.CONSTRUCTED
    persona_id: str | None = None
    # The template field that produced it (third_party.home_address). Kept because the
    # per-category confusion matrix is more useful when a systematic failure can be traced
    # to a field rather than only to a category.
    field_name: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if len(self.text) != len(self.offsets):
            raise ValueError(
                f"label text {self.text!r} does not match its offsets on page {self.page}"
            )

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.page, self.offsets.start, self.offsets.end)

    def to_json(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "start": self.offsets.start,
            "end": self.offsets.end,
            "text": self.text,
            "code": self.code,
            "source": self.source.value,
            "persona_id": self.persona_id,
            "field_name": self.field_name,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> LabelledSpan:
        return cls(
            page=int(d["page"]),
            offsets=Offsets(int(d["start"]), int(d["end"])),
            text=str(d["text"]),
            code=str(d["code"]),
            source=LabelSource(d.get("source", "constructed")),
            persona_id=d.get("persona_id"),
            field_name=d.get("field_name"),
            note=d.get("note"),
        )


@dataclass(frozen=True, slots=True)
class LabelSet:
    """Every label for one document."""

    doc_id: str
    spans: tuple[LabelledSpan, ...] = ()
    source: LabelSource = LabelSource.CONSTRUCTED
    # Set once a person has read the page and confirmed the labels. The plan's
    # "hand-verified" claim is this field, and `sever corpus verify` is what sets it.
    verified_pages: frozenset[int] = field(default_factory=frozenset)

    def __iter__(self) -> Iterator[LabelledSpan]:
        return iter(self.spans)

    def __len__(self) -> int:
        return len(self.spans)

    def on_page(self, page: int) -> tuple[LabelledSpan, ...]:
        return tuple(s for s in self.spans if s.page == page)

    def at(self, page: int, offsets: Offsets) -> LabelledSpan | None:
        """The label covering a span, by overlap. Exact-offset matching would make the
        evaluation a test of the detector's boundary conventions rather than of its
        decisions, so overlap is the rule and it is stated here rather than buried in the
        scorer."""
        best: LabelledSpan | None = None
        best_overlap = 0
        for s in self.spans:
            if s.page != page:
                continue
            hit = s.offsets.intersection(offsets)
            if hit is not None and len(hit) > best_overlap:
                best, best_overlap = s, len(hit)
        return best

    def by_code(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.spans:
            out[s.code] = out.get(s.code, 0) + 1
        return dict(sorted(out.items()))

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "doc_id": self.doc_id,
                        "source": self.source.value,
                        "verified_pages": sorted(self.verified_pages),
                    }
                )
                + "\n"
            )
            for s in self.spans:
                fh.write(json.dumps(s.to_json()) + "\n")
        return path

    @classmethod
    def read(cls, path: Path) -> LabelSet:
        with path.open(encoding="utf-8") as fh:
            header = json.loads(fh.readline())
            spans = tuple(LabelledSpan.from_json(json.loads(line)) for line in fh if line.strip())
        return cls(
            doc_id=str(header["doc_id"]),
            spans=spans,
            source=LabelSource(header.get("source", "constructed")),
            verified_pages=frozenset(header.get("verified_pages", [])),
        )


def merge(sets: Iterable[LabelSet]) -> dict[str, LabelSet]:
    return {s.doc_id: s for s in sets}


def counts_by_code(sets: Sequence[LabelSet]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in sets:
        for code, n in s.by_code().items():
            out[code] = out.get(code, 0) + n
    return dict(sorted(out.items()))
