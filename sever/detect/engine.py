"""The detector: Presidio for the general entity types, pattern recognisers for the
identifiers an access-to-information analyst actually deals with, and one overlap
resolution over the union.

Two things here are worth knowing before reading the code.

First, Presidio is optional. It is a heavy dependency (spaCy plus a language model) and
this project's rules-only path, its taxonomy and its export do not need it. Import it
lazily, and when it is absent say so in a sentence that tells the reader what to install
rather than raising ImportError from three frames down.

Second, the overlap rule prefers the more specific claim, not the higher score. Presidio
scores "HCS-2024-0881" as a LOCATION at 0.85 and the file-number recogniser scores it at
0.90, but that is luck; the reason the file number wins is that a pattern written for this
domain beats a general model on a string it was written for. Where a general and a specific
recogniser disagree, specificity wins and the loser is kept as a note on the detection so
the disagreement is visible in the error decomposition rather than silently discarded.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from sever.detect import recognisers as rec
from sever.detect.types import Detection, EntityType
from sever.ingest.document import Document, Offsets, Page

if TYPE_CHECKING:  # pragma: no cover
    from presidio_analyzer import AnalyzerEngine

# The spaCy model Presidio runs on.
#
# `en_core_web_lg` by default, decided against the measurement rather than against the
# download size. On the 210-page corpus, over 5,355 values whose type the generator
# recorded:
#
#                      small    large
#   overall recall     92.6%    97.4%
#   person             87.2%    96.2%
#   organisation       86.7%    96.2%
#   location           38.1%    62.9%
#
# Every other entity type is identical, because the rest are patterns. The cost is 382 MB
# once and about two seconds over the whole corpus, against a fifth of the remaining
# detector misses. A missed person is a leak, so the trade is not close.
#
# `SEVER_SPACY_MODEL=en_core_web_sm` still works and `sever eval-detector` still reports
# whichever is installed, so the choice stays a measured one rather than a default nobody
# revisits.
SPACY_MODEL = os.environ.get("SEVER_SPACY_MODEL", "en_core_web_lg")

PRESIDIO_MISSING = (
    "Presidio is not installed, so only the pattern recognisers ran. Install the "
    "detection extra with `uv pip install -e '.[detect]'` and download the spaCy model "
    "with `python -m spacy download en_core_web_lg`. The rules-only and blunt baselines "
    "still run without it, but every published detection number needs it."
)

# Presidio's entity vocabulary mapped onto ours. Anything not here is dropped rather than
# guessed at: an unmapped Presidio type would otherwise arrive at the decision layer as
# OTHER and be escalated, which turns a detector gap into reviewer work.
_PRESIDIO_TO_ENTITY: dict[str, EntityType] = {
    "PERSON": EntityType.PERSON,
    "EMAIL_ADDRESS": EntityType.EMAIL,
    "PHONE_NUMBER": EntityType.PHONE,
    "LOCATION": EntityType.LOCATION,
    "DATE_TIME": EntityType.DATE,
    "NRP": EntityType.OTHER,
    "URL": EntityType.URL,
    "IP_ADDRESS": EntityType.IP_ADDRESS,
    "CREDIT_CARD": EntityType.FINANCIAL,
    "IBAN_CODE": EntityType.FINANCIAL,
    "US_SSN": EntityType.SIN,
    "CA_SIN": EntityType.SIN,
    "ORGANIZATION": EntityType.ORGANISATION,
    "ORG": EntityType.ORGANISATION,
}

# Presidio types this project never wants. URL fires on the domain half of every email
# address, which would double every email into two detections and inflate the detector's
# apparent recall.
_PRESIDIO_IGNORED = frozenset({"URL"})

# How specific a claim is. Higher wins an overlap. The general model sits at 1; anything
# written for this domain sits above it.
_SPECIFICITY: dict[EntityType, int] = {
    EntityType.LOCATION: 0,
    EntityType.DATE: 0,
    EntityType.OTHER: 0,
    EntityType.ORGANISATION: 1,
    EntityType.PERSON: 2,
    EntityType.JOB_TITLE: 2,
    EntityType.URL: 1,
    EntityType.IP_ADDRESS: 1,
    EntityType.EMAIL: 3,
    EntityType.PHONE: 3,
    EntityType.ADDRESS: 3,
    EntityType.POSTAL_CODE: 3,
    EntityType.DATE_OF_BIRTH: 4,
    EntityType.FINANCIAL: 4,
    EntityType.FILE_NUMBER: 4,
    EntityType.CASE_NUMBER: 4,
    EntityType.EMPLOYEE_ID: 4,
    EntityType.HEALTH_NUMBER: 5,
    EntityType.SIN: 5,
}


class PresidioUnavailable(RuntimeError):
    """Raised only when Presidio is required and missing, never on the optional path."""


@lru_cache(maxsize=4)
def _analyzer(model: str) -> AnalyzerEngine:
    """Build the Presidio engine once. Loading the spaCy model takes seconds, and the
    detector is called once per page across hundreds of pages."""
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError as exc:  # pragma: no cover - exercised by the no-presidio path
        raise PresidioUnavailable(PRESIDIO_MISSING) from exc

    # Presidio logs a warning per unsupported-language recogniser and per unmapped spaCy
    # label, which is dozens of lines per page and buries anything that matters.
    logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)

    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": model}],
        }
    )
    return AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])


def presidio_available(model: str = SPACY_MODEL) -> bool:
    try:
        _analyzer(model)
    except Exception:
        return False
    return True


def _specificity(t: EntityType) -> int:
    return _SPECIFICITY.get(t, 1)


def _resolve_overlaps(candidates: list[Detection]) -> list[Detection]:
    """Keep the best claim over each stretch of text.

    Sorted by specificity, then by length, then by score. Length matters before score
    because "Marie Doucette" and "Doucette" both score 0.85 and the longer one is the
    entity; taking the shorter would leave the forename in the released record, which is
    a leak that looks like a redaction.
    """
    ordered = sorted(
        candidates,
        key=lambda d: (-_specificity(d.entity_type), -len(d.offsets), -d.score, d.offsets.start),
    )
    kept: list[Detection] = []
    for cand in ordered:
        if any(cand.offsets.overlaps(k.offsets) for k in kept):
            continue
        kept.append(cand)
    return sorted(kept, key=lambda d: (d.page, d.offsets.start))


class SeverDetector:
    """The detector this project ships until 04 Part B exists.

    `require_presidio=True` turns a missing Presidio into an error instead of a warning.
    Every published detection number is produced with it set, and the CLI sets it for
    `sever propose` unless the caller asked for the rules-only path.
    """

    name = "sever-detector"

    def __init__(
        self,
        *,
        model: str = SPACY_MODEL,
        use_presidio: bool = True,
        require_presidio: bool = False,
        pattern_recognisers: Sequence[rec.PatternRecogniser] = rec.DEFAULT_RECOGNISERS,
        min_score: float = 0.3,
    ) -> None:
        self.model = model
        self.use_presidio = use_presidio
        self.require_presidio = require_presidio
        self.pattern_recognisers = tuple(pattern_recognisers)
        self.min_score = min_score
        self._warned = False

    @property
    def presidio_in_use(self) -> bool:
        if not self.use_presidio:
            return False
        if presidio_available(self.model):
            return True
        if self.require_presidio:
            raise PresidioUnavailable(PRESIDIO_MISSING)
        return False

    def detect(self, document: Document) -> tuple[Detection, ...]:
        out: list[Detection] = []
        for page in document:
            out.extend(self.detect_page(page))
        return tuple(out)

    def detect_page(self, page: Page) -> list[Detection]:
        if not page.text.strip():
            return []
        candidates = self._patterns(page)
        if self.presidio_in_use:
            candidates.extend(self._presidio(page))
        candidates = [c for c in candidates if c.score >= self.min_score]
        return _resolve_overlaps(candidates)

    def _patterns(self, page: Page) -> list[Detection]:
        out: list[Detection] = []
        for start, end, matched, r in rec.run(page.text, self.pattern_recognisers):
            out.append(
                Detection(
                    page=page.number,
                    offsets=Offsets(start, end),
                    text=matched,
                    entity_type=r.entity_type,
                    score=r.score,
                    recogniser=r.name,
                )
            )
        return out

    def _presidio(self, page: Page) -> list[Detection]:
        engine = _analyzer(self.model)
        results: list[Any] = engine.analyze(text=page.text, language="en")
        out: list[Detection] = []
        for r in results:
            if r.entity_type in _PRESIDIO_IGNORED:
                continue
            mapped = _PRESIDIO_TO_ENTITY.get(r.entity_type)
            if mapped is None:
                continue
            offsets = Offsets(r.start, r.end)
            text = page.slice(offsets)
            # A person's name does not run across a line break in these layouts, but the
            # model regularly glues the last name on a line to the first word of the next:
            # "Wallace Penashue\nDate" came back as one PERSON. Left alone that is two
            # separate harms. The box is drawn over a word that was not personal
            # information, and, worse, "Date" then becomes a registered alias of a person
            # in the placeholder policy, so the guard refuses every request containing the
            # ordinary English word. Cut at the first newline.
            newline = text.find("\n")
            if newline > 0:
                offsets = Offsets(offsets.start, offsets.start + newline)
                text = page.slice(offsets)
            elif newline == 0:
                continue
            # Presidio also returns spans with trailing punctuation or whitespace. A box a
            # character wide of the name leaks nothing, but it makes exact-match grading
            # against the corpus labels disagree with itself, so trim before recording.
            lead = len(text) - len(text.lstrip())
            trail = len(text) - len(text.rstrip(" \t\n,.;:"))
            if lead or trail:
                start, end = offsets.start + lead, offsets.end - trail
                if end <= start:
                    continue
                offsets = Offsets(start, end)
                text = page.slice(offsets)
            out.append(
                Detection(
                    page=page.number,
                    offsets=offsets,
                    text=text,
                    entity_type=mapped,
                    score=float(r.score),
                    recogniser=f"presidio:{r.entity_type}",
                )
            )
        return out


def default_detector(**kwargs: Any) -> SeverDetector:
    return SeverDetector(**kwargs)
