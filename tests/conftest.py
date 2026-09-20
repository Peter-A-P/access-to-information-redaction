"""Shared fixtures. Deliberately small: most tests build exactly the document they need."""

from __future__ import annotations

import pytest

from sever.context.record import ContextBuilder, ContextRecord
from sever.context.requester import RequestConfig
from sever.corpus.generate import Corpus, build
from sever.corpus.personas import PersonaFactory, PersonaRole
from sever.detect.engine import SeverDetector
from sever.ingest.document import (
    Block,
    BlockKind,
    Document,
    DocumentType,
    Offsets,
    Page,
)


@pytest.fixture(scope="session")
def detector() -> SeverDetector:
    """One detector for the session: loading the spaCy model is seconds, not milliseconds."""
    return SeverDetector()


@pytest.fixture(scope="session")
def pattern_detector() -> SeverDetector:
    """Patterns only. Fast, deterministic, and available where Presidio is not."""
    return SeverDetector(use_presidio=False)


@pytest.fixture(scope="session")
def corpus() -> Corpus:
    return build(documents=12)


@pytest.fixture
def factory() -> PersonaFactory:
    return PersonaFactory(seed=1234)


def make_document(
    blocks: list[tuple[BlockKind, str]],
    *,
    doc_id: str = "t1",
    doc_type: DocumentType = DocumentType.CORRESPONDENCE,
) -> Document:
    """Build a one-page document from (kind, text) pairs, joined by blank lines."""
    parts: list[str] = []
    built: list[Block] = []
    pos = 0
    for kind, text in blocks:
        if parts:
            parts.append("\n\n")
            pos += 2
        parts.append(text)
        built.append(Block(kind=kind, offsets=Offsets(pos, pos + len(text)), text=text))
        pos += len(text)
    page = Page(number=1, text="".join(parts), blocks=tuple(built))
    return Document(doc_id=doc_id, doc_type=doc_type, pages=(page,))


def context_for(
    document: Document,
    config: RequestConfig,
    detector: SeverDetector,
) -> tuple[ContextRecord, ...]:
    detections = tuple(detector.detect(document))
    return ContextBuilder(config=config).build(document, detections)


def code_covering(document: Document, proposals: object, needle: str) -> str | None:
    """The code of the proposal covering `needle` in the document, by offset overlap.

    Matching on the detection's own text instead looks simpler and is brittle in a way
    that matters: a language model may return "Tulk" for "Odette Tulk", and a test asking
    whether any detection *contains* "Odette Tulk" then reports nothing at all rather than
    reporting the partial box that actually exists. Overlap is what the scorer uses, so
    the tests use it too. How often a box covers only part of a value is measured
    separately, by the coverage column in `sever eval-detector`.
    """
    from sever.ingest.document import Offsets

    for page in document:
        start = page.text.find(needle)
        if start < 0:
            continue
        want = Offsets(start, start + len(needle))
        for proposal in proposals:  # type: ignore[attr-defined]
            if proposal.page == page.number and proposal.detection.offsets.overlaps(want):
                return str(proposal.code)
    return None


def requester_config(name: str, **kwargs: object) -> RequestConfig:
    return RequestConfig(request_id="r1", requester_name=name, **kwargs)  # type: ignore[arg-type]


__all__ = [
    "PersonaRole",
    "code_covering",
    "context_for",
    "make_document",
    "requester_config",
]
