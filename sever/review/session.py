"""A review session: the documents, the proposals, the log, and the gate.

The README's second paragraph says there is no path from a proposal to a released document
without a reviewer action on every page. Until now that was a property of the code in the
sense that no code did it, which is not the same as a property that is enforced. This module
is where it becomes enforced: `release_gate` is the only thing that says a document may be
exported, and both the web app and the command line ask it.

Two things live here rather than in the web layer, deliberately.

**The gate.** A rule enforced in a request handler is a rule about a web application. Put it
behind the session and any caller has to pass it, including the next one, written by someone
who has not read this docstring.

**The clock.** Section 10 asks for reviewer minutes per page with and without proposals, and
that measurement is only as good as its timestamps. The audit log has timestamps, but the
first action on a page is not the moment the page appeared, and a page that took four minutes
of reading before one click would be recorded as instantaneous. So the session stamps a page
when it is served and measures to the completion action, and writes that to its own file
rather than into the audit log. The audit log is evidence of decisions and it is not the
place for interface telemetry.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from sever.decide.pipeline import Proposal
from sever.ingest.document import Document, Offsets
from sever.review.audit import Action, AuditLog
from sever.review.decisions import FinalSpan, Origin, final_spans
from sever.review.propagate import PROPAGATED_REASON, Occurrence, Spread, plan
from sever.taxonomy.loader import Taxonomy, default_taxonomy


class Mode(StrEnum):
    """Which arm of the time study this session is running.

    `UNAIDED` is a real control rather than a cosmetic one: the reviewer gets the page and
    the category list and nothing else, and every severance in the released record is one
    they marked themselves. Hiding only the suggested code while leaving the spans
    highlighted would measure how long it takes to agree with a highlight, which is not the
    question. Finding the span is most of the work.
    """

    PROPOSALS = "proposals"
    UNAIDED = "unaided"

    @property
    def shows_proposals(self) -> bool:
        return self is Mode.PROPOSALS


@dataclass(frozen=True, slots=True)
class RecordEvent:
    """One row the session just appended, as an observer sees it: the kind of action and the
    codes, never the span's text. What the public demonstration's dashboard counts."""

    doc_id: str
    page: int
    action: Action
    span_start: int | None
    span_end: int | None
    proposed_code: str | None
    final_code: str | None
    reason: str | None


class NotReviewed(RuntimeError):
    """A release was asked for before a person had acted on every page."""


@dataclass(frozen=True, slots=True)
class PageTiming:
    request_id: str
    doc_id: str
    page: int
    mode: Mode
    served_at: dt.datetime
    completed_at: dt.datetime
    spans_on_page: int
    actions: int
    # Who reviewed, as the study's pseudonym rather than a name, and whether the page was
    # the warm-up a study discards before it starts counting.
    reviewer: str | None = None
    practice: bool = False

    @property
    def seconds(self) -> float:
        return (self.completed_at - self.served_at).total_seconds()

    def as_json(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "doc_id": self.doc_id,
            "page": self.page,
            "mode": self.mode.value,
            "served_at": self.served_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "seconds": round(self.seconds, 3),
            "spans_on_page": self.spans_on_page,
            "actions": self.actions,
            "reviewer": self.reviewer,
            "practice": self.practice,
        }


@dataclass(frozen=True, slots=True)
class Item:
    """One document under review, with whatever the tool proposed for it."""

    document: Document
    proposals: tuple[Proposal, ...]
    # Set in the reviewer study, where one session serves both arms: which arm this record
    # is in, and whether it is the warm-up page. Outside the study both are left alone and
    # the session's own mode applies.
    arm: Mode | None = None
    practice: bool = False
    # Who made the request. The tool is configured with it, so a reviewer has to be told it
    # too, or the unaided arm is being asked a question with half the facts.
    requester: str | None = None

    @property
    def doc_id(self) -> str:
        return self.document.doc_id

    def on_page(self, page: int) -> tuple[Proposal, ...]:
        return tuple(
            sorted(
                (p for p in self.proposals if p.page == page),
                key=lambda p: p.detection.offsets.start,
            )
        )


@dataclass
class Session:
    """Everything one reviewer is working through, and the log of what they did."""

    request_id: str
    items: tuple[Item, ...]
    log: AuditLog
    mode: Mode = Mode.PROPOSALS
    taxonomy: Taxonomy = field(default_factory=default_taxonomy)
    timings_path: Path | None = None
    actor: str | None = None
    jurisdiction: str | None = None
    # Withholding a value once withholds every other exact occurrence of it in the record.
    # On, except in the reviewer study, whose three reviewers were timed without it. See
    # sever.review.propagate.
    propagate_withholding: bool = True
    # Told about every row after it is appended. The demonstration counts visitors'
    # decisions this way (sever.review.stats); nothing else sets it.
    observer: Callable[[Session, RecordEvent], None] | None = field(default=None, repr=False)
    # When each page was last served, so a completion can be measured against it. In
    # memory: a restart loses the open pages, which is correct, because a page served
    # before a restart was not being read during it.
    _served: dict[tuple[str, int], dt.datetime] = field(default_factory=dict, repr=False)
    timings: list[PageTiming] = field(default_factory=list)

    def __iter__(self) -> Iterator[Item]:
        return iter(self.items)

    def item(self, doc_id: str) -> Item:
        for i in self.items:
            if i.doc_id == doc_id:
                return i
        raise KeyError(doc_id)

    def mode_of(self, doc_id: str) -> Mode:
        """The arm this record is served in: its own in the study, the session's otherwise."""
        arm = self.item(doc_id).arm
        return arm if arm is not None else self.mode

    def final_spans(self, doc_id: str) -> tuple[FinalSpan, ...]:
        """What the reviewer decided for this record, which is what an export applies."""
        return final_spans(
            self.log.rows(request_id=self.request_id),
            self.item(doc_id).proposals,
            doc_id=doc_id,
            taxonomy=self.taxonomy,
            jurisdiction=self.jurisdiction,
        )

    def added_spans(self, doc_id: str, page: int) -> tuple[FinalSpan, ...]:
        """Severances the reviewer made that the tool never proposed, still standing.

        Shown on the page so a reviewer can see, and undo, what they selected. A reviewer
        who cannot see their own severances cannot check them, and in the unaided arm those
        are all of them.
        """
        return tuple(
            s
            for s in self.final_spans(doc_id)
            if s.page == page and s.origin is Origin.REVIEWER and s.withholds
        )

    # --- what the reviewer has done so far ---------------------------------------

    def acted_spans(self, doc_id: str, page: int) -> dict[tuple[int, int], Action]:
        """The latest action per span on a page. Supersedes rather than overwrites: the
        log keeps every row and this reads the last one."""
        latest: dict[tuple[int, int], Action] = {}
        for row in self.log.rows(request_id=self.request_id):
            if row.doc_id != doc_id or row.page != page:
                continue
            if row.action in (Action.PAGE_COMPLETE, Action.COMMENT):
                continue
            if row.span_start is None or row.span_end is None:
                continue
            latest[(row.span_start, row.span_end)] = row.action
        return latest

    def outstanding(self, doc_id: str, page: int) -> tuple[Proposal, ...]:
        """Proposals on this page that nobody has acted on yet."""
        acted = self.acted_spans(doc_id, page)
        return tuple(
            p
            for p in self.item(doc_id).on_page(page)
            if (p.detection.offsets.start, p.detection.offsets.end) not in acted
        )

    def page_complete(self, doc_id: str, page: int) -> bool:
        return (doc_id, page) in self.log.pages_reviewed(self.request_id)

    def pages_remaining(self, doc_id: str) -> tuple[int, ...]:
        done = self.log.pages_reviewed(self.request_id)
        return tuple(p.number for p in self.item(doc_id).document if (doc_id, p.number) not in done)

    # --- the gate ----------------------------------------------------------------

    def release_gate(self, doc_id: str) -> None:
        """Raise unless a person has completed every page of this document.

        The only function in this project that authorises a release. It is deliberately a
        raise rather than a boolean: a caller that forgets to check a boolean releases the
        document, and a caller that forgets to catch an exception does not.
        """
        remaining = self.pages_remaining(doc_id)
        if remaining:
            total = len(self.item(doc_id).document)
            raise NotReviewed(
                f"{doc_id} has {len(remaining)} of {total} pages with no reviewer action: "
                f"pages {', '.join(str(p) for p in remaining)}. The tool proposes and a "
                f"person decides, so nothing is released until every page has been through "
                f"someone."
            )

    def releasable(self, doc_id: str) -> bool:
        return not self.pages_remaining(doc_id)

    # --- recording ---------------------------------------------------------------

    def serve(self, doc_id: str, page: int, *, at: dt.datetime | None = None) -> None:
        """Stamp the moment a page was put in front of someone."""
        self._served[(doc_id, page)] = at or _now()

    def record(
        self,
        *,
        doc_id: str,
        page: int,
        action: Action,
        span_start: int | None = None,
        span_end: int | None = None,
        span_text: str | None = None,
        proposed_code: str | None = None,
        final_code: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.log.append(
            request_id=self.request_id,
            doc_id=doc_id,
            page=page,
            action=action,
            actor=self.actor,
            span_start=span_start,
            span_end=span_end,
            span_text=span_text,
            proposed_code=proposed_code,
            final_code=final_code,
            reason=reason,
        )
        if self.observer is not None:
            self.observer(
                self,
                RecordEvent(
                    doc_id=doc_id,
                    page=page,
                    action=action,
                    span_start=span_start,
                    span_end=span_end,
                    proposed_code=proposed_code,
                    final_code=final_code,
                    reason=reason,
                ),
            )

    def spread_withholding(
        self, *, doc_id: str, page: int, start: int, end: int, code: str | None
    ) -> tuple[Spread, ...]:
        """Withhold every other occurrence of the value just withheld at `start`-`end`.

        Called by the application after a reviewer withholds a span; never after a spread
        row, so a spread does not spread again. Returns what it withheld, so the screen
        can say so. Does nothing when `propagate_withholding` is off.
        """
        if not self.propagate_withholding:
            return ()
        item = self.item(doc_id)
        document = item.document
        value = document.page(page).text[start:end]
        acted: dict[int, list[Offsets]] = {}
        for row in self.log.rows(request_id=self.request_id):
            if row.doc_id != doc_id or row.span_start is None or row.span_end is None:
                continue
            if row.action in (Action.PAGE_COMPLETE, Action.COMMENT):
                continue
            acted.setdefault(row.page, []).append(Offsets(row.span_start, row.span_end))
        spreads = plan(
            document,
            value,
            source=Occurrence(page, Offsets(start, end)),
            proposals=item.proposals,
            acted=acted,
        )
        reason = f"{PROPAGATED_REASON} on page {page}."
        # The code the spread withholds under. The reviewer's own, where it withholds; R1
        # where it does not, which happens when they pressed Withhold on a span the tool
        # proposed to release and the row carries the tool's keep code. Moving another
        # occurrence to a keep code would release it, which is the one thing a spread
        # must never do.
        withhold_code = (
            code
            if code is not None and self.taxonomy.decision(code, self.jurisdiction).withholds
            else "R1"
        )
        for s in spreads:
            text = document.page(s.page).text[s.offsets.start : s.offsets.end]
            if s.proposal is not None:
                self.record(
                    doc_id=doc_id,
                    page=s.page,
                    action=Action.APPROVE if s.proposal.withholds else Action.CHANGE_CATEGORY,
                    span_start=s.offsets.start,
                    span_end=s.offsets.end,
                    span_text=text,
                    proposed_code=s.proposal.code,
                    final_code=s.proposal.code if s.proposal.withholds else withhold_code,
                    reason=reason,
                )
            else:
                self.record(
                    doc_id=doc_id,
                    page=s.page,
                    action=Action.ADD,
                    span_start=s.offsets.start,
                    span_end=s.offsets.end,
                    span_text=text,
                    final_code=withhold_code,
                    reason=reason,
                )
        return spreads

    def complete_page(
        self, doc_id: str, page: int, *, at: dt.datetime | None = None
    ) -> PageTiming | None:
        """Mark a page done and, if it was served in this process, time it.

        Returns None when there is no served-at stamp, which happens after a restart. A
        missing timing is recorded as missing rather than estimated: the whole point of the
        measurement is that it is a measurement.
        """
        done_at = at or _now()
        self.record(doc_id=doc_id, page=page, action=Action.PAGE_COMPLETE)
        served = self._served.pop((doc_id, page), None)
        if served is None:
            return None
        timing = PageTiming(
            request_id=self.request_id,
            doc_id=doc_id,
            page=page,
            mode=self.mode_of(doc_id),
            served_at=served,
            completed_at=done_at,
            spans_on_page=len(self.item(doc_id).on_page(page)),
            actions=len(self.acted_spans(doc_id, page)),
            reviewer=self.actor,
            practice=self.item(doc_id).practice,
        )
        self.timings.append(timing)
        if self.timings_path is not None:
            self.timings_path.parent.mkdir(parents=True, exist_ok=True)
            with self.timings_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(timing.as_json(), ensure_ascii=False) + "\n")
        return timing


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def build_session(
    *,
    request_id: str,
    items: Sequence[Item],
    log_path: Path,
    mode: Mode = Mode.PROPOSALS,
    timings_path: Path | None = None,
    actor: str | None = None,
    jurisdiction: str | None = None,
) -> Session:
    """A session over a DuckDB log at `log_path`, creating it if it is not there.

    In `UNAIDED` mode the proposals are dropped on the way in rather than hidden in the
    template. A control arm that holds the answers in memory and declines to render them is
    one template edit away from not being a control.
    """
    kept = tuple(
        Item(
            document=i.document,
            proposals=i.proposals if (i.arm or mode).shows_proposals else (),
            arm=i.arm,
            practice=i.practice,
            requester=i.requester,
        )
        for i in items
    )
    return Session(
        request_id=request_id,
        items=kept,
        log=AuditLog(log_path),
        mode=mode,
        timings_path=timings_path,
        actor=actor,
        jurisdiction=jurisdiction,
    )
