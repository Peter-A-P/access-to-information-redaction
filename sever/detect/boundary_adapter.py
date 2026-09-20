"""Detection through `boundary.redact`, which is what PLAN.md always specified.

Project 04 shipped `boundary.redact` in v0.5.0, built to this project's brief, and it now
carries the two Presidio defects this project found as analyzer-level guarantees rather
than as fixes in one consumer: no span crosses a line break, and no two spans overlap.
That is the right place for them, so this module hands detection over.

It composes rather than replaces. `Analyzer` accepts extra recognisers, and two of this
project's own are things a general engine has no reason to carry:

  * **street addresses**, which `boundary.redact` has no recogniser for. A missed home
    address is a leak, so this one is not optional;
  * **job titles**, which are not personal information and are not detected for redaction
    at all. They are detected because a title paired with a name is the single strongest
    K2 signal there is, and the decision layer needs the span to reason about.

Both go in as `extra=`, which is what that argument is for.

`boundary` is an optional extra of this project, so nothing here is imported at module
scope by anything on the rules-only path. The published rules-only baseline runs in CI with
neither `boundary` nor Presidio installed, and `sever.detect.engine.SeverDetector` remains
the implementation that runs there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sever.detect import recognisers as rec
from sever.detect.types import Detection, EntityType
from sever.ingest.document import Document, Offsets

if TYPE_CHECKING:  # pragma: no cover
    from boundary.redact import Span

BOUNDARY_MISSING = (
    "boundary is not installed, so detection through boundary.redact is unavailable. "
    "Install the gateway extra with `uv pip install -e '.[gateway]'`, or use "
    "sever.detect.engine.SeverDetector, which needs nothing from project 04."
)

# boundary's closed vocabulary onto this project's. Nearly one to one, which is what
# happens when one of them was written from the other's brief.
#
# NAME_LIKE and ID_LIKE are the policy's second-pass markers rather than analyzer output,
# so they should never arrive here. They are mapped rather than dropped so that a future
# version of boundary emitting them does not silently lose spans: OTHER reaches the
# decision layer, finds no rule, and escalates, which is the safe direction.
_TYPES: dict[str, EntityType] = {
    "PERSON": EntityType.PERSON,
    "EMAIL": EntityType.EMAIL,
    "PHONE": EntityType.PHONE,
    "SIN": EntityType.SIN,
    "HEALTH_NUMBER": EntityType.HEALTH_NUMBER,
    "POSTAL_CODE": EntityType.POSTAL_CODE,
    "DATE_OF_BIRTH": EntityType.DATE_OF_BIRTH,
    "FILE_NUMBER": EntityType.FILE_NUMBER,
    "EMPLOYEE_ID": EntityType.EMPLOYEE_ID,
    "LOCATION": EntityType.LOCATION,
    "ORGANISATION": EntityType.ORGANISATION,
    "URL": EntityType.URL,
    "NAME_LIKE": EntityType.OTHER,
    "ID_LIKE": EntityType.OTHER,
}

# This project's recognisers that boundary has no equivalent for. Not a criticism of
# boundary: a street address is a local convention and a job title is not personal
# information at all, so neither belongs in a general engine's defaults.
SEVER_EXTRAS: tuple[rec.PatternRecogniser, ...] = (rec.STREET_ADDRESS, rec.JOB_TITLE)

_SEVER_TO_BOUNDARY: dict[EntityType, str] = {
    EntityType.ADDRESS: "LOCATION",
    EntityType.JOB_TITLE: "ORGANISATION",
}


class BoundaryUnavailable(RuntimeError):
    """Raised only where boundary is required and missing."""


@dataclass
class _RecogniserBridge:
    """One of this project's pattern recognisers, as a `boundary.redact.Recogniser`.

    boundary asks for an `id` and `analyze(text, page) -> list[Span]`. The entity type has
    to come from boundary's closed vocabulary, so the two types it does not have are
    carried over as their nearest neighbour and translated back on the way out by
    `recogniser`, which is preserved end to end. Round-tripping through the id rather than
    through the type is deliberate: the vocabulary is closed on purpose and widening it
    from a consumer would defeat the point of it being closed.
    """

    inner: rec.PatternRecogniser

    @property
    def id(self) -> str:
        return f"sever:{self.inner.name}"

    def analyze(self, text: str, page: int) -> list[Any]:
        from boundary.redact import EntityType as BoundaryEntityType
        from boundary.redact import Span

        mapped = _SEVER_TO_BOUNDARY.get(self.inner.entity_type, self.inner.entity_type.name)
        entity_type = BoundaryEntityType(mapped)
        out: list[Any] = []
        for start, end, matched in self.inner.finditer(text):
            out.append(
                Span(
                    page=page,
                    start=start,
                    end=end,
                    text=matched,
                    entity_type=entity_type,
                    score=self.inner.score,
                    recogniser=self.id,
                )
            )
        return out


def _entity_for(span: Span) -> EntityType:
    """Translate a span's type back, preferring the recogniser id where this project put
    the span in itself."""
    for ours in SEVER_EXTRAS:
        if span.recogniser == f"sever:{ours.name}":
            return ours.entity_type
    return _TYPES.get(str(span.entity_type.value), EntityType.OTHER)


@dataclass
class BoundaryDetector:
    """`boundary.redact.Analyzer` behind this project's `Detector` protocol."""

    name: str = "boundary.redact"
    use_presidio: bool = True
    require_presidio: bool = False
    extras: Sequence[rec.PatternRecogniser] = SEVER_EXTRAS
    min_score: float = 0.3
    _analyzer: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            from boundary.redact import Analyzer
        except ImportError as exc:
            raise BoundaryUnavailable(BOUNDARY_MISSING) from exc

        extra: list[Any] = [_RecogniserBridge(inner=r) for r in self.extras]
        if self.use_presidio:
            try:
                from boundary.redact.presidio import PresidioRecogniser

                extra.append(PresidioRecogniser())
            except Exception as exc:
                if self.require_presidio:
                    raise BoundaryUnavailable(
                        f"boundary.redact's Presidio recogniser is unavailable: {exc}. "
                        f"People, places and organisations need a model, so without it "
                        f"only the pattern recognisers run."
                    ) from exc
        self._analyzer = Analyzer(extra=extra)

    def detect(self, document: Document) -> tuple[Detection, ...]:
        pages = [p.text for p in document]
        if not any(t.strip() for t in pages):
            return ()
        spans = self._analyzer.analyze(pages, first_page=document.pages[0].number)
        out: list[Detection] = []
        for span in spans:
            if span.score < self.min_score:
                continue
            out.append(
                Detection(
                    page=span.page,
                    offsets=Offsets(span.start, span.end),
                    text=span.text,
                    entity_type=_entity_for(span),
                    score=float(span.score),
                    recogniser=span.recogniser,
                )
            )
        return tuple(sorted(out, key=lambda d: (d.page, d.offsets.start)))


def available() -> bool:
    try:
        import boundary.redact  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class LayeredPolicy:
    """`boundary.redact.Policy` with this project's second pass kept on top.

    Project 04 said the choice was this project's: drop its own scrub, or keep it layered.
    The evidence says keep it, and the evidence is specific rather than a preference.

    Run against this project's 210-page corpus and its persona ground truth, 57 of 210
    pages came back from `Policy.outbound` with a real Medical Care Plan number still in
    the text, and the policy did not refuse. The cause is one shape:

        MCP 123456789012        -> <HEALTH_NUMBER_1>   detected
        MCP 123-456-789-012     -> <ID_LIKE_1>         caught by the second pass
        MCP 123 456 789 012     -> unchanged           neither

    Space-separated digit groups are how a Medical Care Plan number is actually written on
    a form, and the recogniser wants twelve contiguous digits while the second pass's
    identifier shape does not span the gaps. Reported to 04 on 2026-09-19.

    This class is not a workaround for that one bug, and should outlive it. A privacy
    boundary made of one component is only as good as that component's worst day, and this
    project's own scrub is forty lines with no model behind it. Layering costs a regular
    expression pass over text that is about to cross a network anyway.
    """

    policy: Any
    scrub: bool = True

    def outbound(self, text: str) -> str:
        """Substitute through boundary, then mask anything still identifier-shaped."""
        from sever.decide.placeholders import scrub_unrecognised

        substituted = self.policy.outbound(text)
        return scrub_unrecognised(substituted) if self.scrub else substituted

    def rehydrate(self, text: str) -> str:
        return str(self.policy.rehydrate(text))


def policy_for(document: Document, detector: BoundaryDetector) -> LayeredPolicy:
    """A document-wide policy over every entity boundary's analyzer found in it."""
    from boundary.redact import Policy

    spans = detector._analyzer.analyze(
        [p.text for p in document], first_page=document.pages[0].number
    )
    return LayeredPolicy(policy=Policy(spans))
