"""What a person decided, span by span: the thing an export has to apply.

Until this module existed the export applied the tool's *proposals* to any page the audit
log said was complete. A reviewer who rejected a proposal still had it redacted, and a
reviewer who selected a name the tool had missed and severed it got a released record with
that name in clear. The gate checked that a person had looked at every page and then threw
away what they said. The tool proposes; a person decides; and the decision was not being
read.

So the rule here is one function, `final_spans`, that reads the log and the proposals
together and says, for every span anybody touched, whether it is withheld and under which
code. The export, the schedule and the reviewer study all read it, so the three of them
cannot disagree about what the reviewer did.

The precedence is the audit log's: the latest row per span wins, and earlier rows stay in
the log as history. A proposal with no reviewer row keeps the tool's decision, which only
matters for a page nobody completed, and such a page is never released anyway.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sever.decide.pipeline import Proposal, Source
from sever.detect.types import Detection, EntityType
from sever.ingest.document import Document, Offsets
from sever.review.audit import Action, AuditRow
from sever.taxonomy.loader import Decision, Taxonomy


class Origin(StrEnum):
    PROPOSAL = "proposal"
    REVIEWER = "reviewer"


@dataclass(frozen=True, slots=True)
class FinalSpan:
    """One span after review: where it is, what it is, and whether it leaves the record."""

    page: int
    start: int
    end: int
    code: str | None
    withholds: bool
    origin: Origin
    proposed_code: str | None = None

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.page, self.start, self.end)


def _withholds(row: AuditRow, taxonomy: Taxonomy, jurisdiction: str | None) -> bool:
    """Whether the latest action on a span keeps it out of the record.

    `CHANGE_CATEGORY` is the case that needs the taxonomy: moving a span from R1 to R2
    keeps it withheld, moving it to K2 releases it. The action alone cannot say which, so
    the code it was moved to decides, under the same jurisdiction the proposals were made
    in.
    """
    if row.action is Action.CHANGE_CATEGORY:
        if row.final_code is None:
            return True
        return taxonomy.decision(row.final_code, jurisdiction).withholds
    return row.action.withholds


def final_spans(
    rows: Iterable[AuditRow],
    proposals: Sequence[Proposal],
    *,
    doc_id: str,
    taxonomy: Taxonomy,
    jurisdiction: str | None = None,
) -> tuple[FinalSpan, ...]:
    """Every span of one document after review, sorted by position.

    `rows` is the audit log for the request; rows for other documents are ignored. A span
    the reviewer added and then released again (an undo) is present with `withholds`
    false, so a caller counting what the reviewer severed does not count it.
    """
    latest: dict[tuple[int, int, int], AuditRow] = {}
    for row in rows:
        if row.doc_id != doc_id or row.span_start is None or row.span_end is None:
            continue
        if row.action in (Action.PAGE_COMPLETE, Action.COMMENT):
            continue
        latest[(row.page, row.span_start, row.span_end)] = row

    out: dict[tuple[int, int, int], FinalSpan] = {}
    for p in proposals:
        key = (p.page, p.detection.offsets.start, p.detection.offsets.end)
        acted = latest.pop(key) if key in latest else None
        if acted is None:
            out[key] = FinalSpan(
                page=p.page,
                start=key[1],
                end=key[2],
                code=p.code,
                withholds=p.withholds,
                origin=Origin.PROPOSAL,
                proposed_code=p.code,
            )
            continue
        code = acted.final_code if acted.final_code is not None else p.code
        out[key] = FinalSpan(
            page=p.page,
            start=key[1],
            end=key[2],
            code=None if acted.action is Action.REJECT else code,
            withholds=_withholds(acted, taxonomy, jurisdiction),
            origin=Origin.PROPOSAL,
            proposed_code=p.code,
        )
    # What is left is spans the tool never proposed: the reviewer's additions, and any
    # later action on them.
    for key, row in latest.items():
        out[key] = FinalSpan(
            page=key[0],
            start=key[1],
            end=key[2],
            code=None if row.action is Action.REJECT else row.final_code,
            withholds=_withholds(row, taxonomy, jurisdiction),
            origin=Origin.REVIEWER,
        )
    return tuple(sorted(out.values(), key=lambda s: s.key))


def withheld(spans: Iterable[FinalSpan]) -> tuple[FinalSpan, ...]:
    return tuple(s for s in spans if s.withholds)


def as_released(
    spans: Iterable[FinalSpan],
    proposals: Sequence[Proposal],
    document: Document,
    *,
    taxonomy: Taxonomy,
    jurisdiction: str = "federal",
) -> tuple[Proposal, ...]:
    """The reviewer's decisions in the shape the export and the schedule take.

    Only withheld spans come back. A proposal the reviewer accepted is returned as it was;
    one they moved to another withholding code carries that code and its provisions, so the
    schedule cites what the reviewer relied on rather than what the tool suggested; and a
    span they selected themselves becomes a proposal from `Source.REVIEWER`.
    """
    by_key = {p.key: p for p in proposals}
    out: list[Proposal] = []
    for s in spans:
        if not s.withholds:
            continue
        code = s.code or "E1"
        decision = taxonomy.decision(code, jurisdiction)
        if not decision.withholds:
            # Withheld under a keep code: the reviewer pressed Withhold on a span the tool
            # proposed to release. The text goes; the schedule says a person decided it
            # and cites no provision, rather than citing the keep provision for a
            # severance.
            decision = Decision.REDACT
        provisions = (
            taxonomy.provisions(code, jurisdiction)
            if taxonomy.decision(code, jurisdiction).withholds
            else ()
        )
        original = by_key.get(s.key)
        if original is not None and original.code == code and original.withholds:
            out.append(original)
            continue
        text = document.page(s.page).text[s.start : s.end]
        detection = (
            original.detection
            if original is not None
            else Detection(
                page=s.page,
                offsets=Offsets(s.start, s.end),
                text=text,
                entity_type=EntityType.PERSON,
                score=1.0,
                recogniser="reviewer:selection",
            )
        )
        out.append(
            Proposal(
                detection=detection,
                code=code,
                decision=decision,
                confidence=1.0,
                reason="Severed by the reviewer.",
                source=Source.REVIEWER,
                provisions=provisions,
            )
        )
    return tuple(sorted(out, key=lambda p: p.key))
