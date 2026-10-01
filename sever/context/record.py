"""The context record: everything known about one candidate span before a decision.

This is the object the whole project turns on. The rules read it, the model is shown a
redacted view of it, the sentence-only baseline is defined as the same pipeline with most
of it blanked, and the explanation a reviewer reads is generated from the fields that
fired. Keeping it one explicit dataclass, rather than passing a document around and
letting each rule dig, is what makes that ablation honest: blanking a field is a one-line
change and it provably removes the information.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sever.context.directory import DirectoryMatch, StaffDirectory
from sever.context.register import PublicRegister, RegisterMatch
from sever.context.requester import RequestConfig, RequesterMatch, RequesterMatcher
from sever.context.roles import RoleIndex, RoleMention
from sever.detect import coref
from sever.detect.types import Detection, EntityType
from sever.ingest.document import BlockKind, Document, DocumentType, Page


@dataclass(frozen=True, slots=True)
class ContextRecord:
    """One candidate span, with the document context that decides it."""

    detection: Detection
    doc_id: str
    doc_type: DocumentType
    page_number: int
    pages_in_document: int

    block_kind: BlockKind = BlockKind.UNKNOWN
    sentence: str = ""
    heading: str | None = None
    # Which message of an email chain the span sits in; None outside a chain.
    message_index: int | None = None

    requester_match: RequesterMatch | None = None
    register_match: RegisterMatch | None = None
    # A published staff directory listing this name or this work contact. Evidence about
    # the string, not about its sentence; see sever.context.directory.
    directory_match: DirectoryMatch | None = None
    # A title paired with this name anywhere in the document, and where the pairing was
    # found. This is the K2 signal.
    title: str | None = None
    title_source: str | None = None
    role_mentions: tuple[RoleMention, ...] = ()

    cluster_id: str | None = None
    cluster_canonical: str | None = None
    cluster_surface_forms: tuple[str, ...] = ()
    cluster_pages: tuple[int, ...] = ()
    cluster_ambiguous: bool = False

    # Other people named in the same sentence. A span with a third party beside it in one
    # sentence is the R2 case, and this is how the rule sees it.
    co_mentions_in_sentence: tuple[str, ...] = ()

    @property
    def entity_type(self) -> EntityType:
        return self.detection.entity_type

    @property
    def text(self) -> str:
        return self.detection.text

    @property
    def is_requester(self) -> bool:
        return self.requester_match is not None and self.requester_match.is_match

    @property
    def is_requester_ambiguous(self) -> bool:
        return self.requester_match is not None and self.requester_match.is_ambiguous

    @property
    def has_official_capacity_signal(self) -> bool:
        """A title paired with the name, or a mention in a capacity-bearing position."""
        if self.title is not None:
            return True
        return any(m.is_capacity_bearing for m in self.role_mentions)

    @property
    def in_role_bearing_block(self) -> bool:
        return self.block_kind.is_role_bearing

    def blanked(self, *fields_to_blank: str) -> ContextRecord:
        """A copy with named fields emptied, for the ablations.

        The sentence-only baseline is `blanked("title", "title_source", "role_mentions",
        "register_match", "cluster_id", "cluster_canonical", "cluster_surface_forms",
        "cluster_pages", "heading", "block_kind")`, which is a precise and checkable
        statement of what that baseline is denied.
        """
        empties: dict[str, object] = {
            "block_kind": BlockKind.UNKNOWN,
            "heading": None,
            "title": None,
            "title_source": None,
            "role_mentions": (),
            "register_match": None,
            "directory_match": None,
            "requester_match": None,
            "cluster_id": None,
            "cluster_canonical": None,
            "cluster_surface_forms": (),
            "cluster_pages": (),
            "cluster_ambiguous": False,
            "co_mentions_in_sentence": (),
            "message_index": None,
        }
        changes = {}
        for name in fields_to_blank:
            if name not in empties:
                raise KeyError(f"{name!r} is not a blankable context field")
            changes[name] = empties[name]
        current = {
            f: getattr(self, f)
            for f in (
                "detection", "doc_id", "doc_type", "page_number", "pages_in_document",
                "block_kind", "sentence", "heading", "message_index", "requester_match",
                "register_match", "directory_match", "title", "title_source",
                "role_mentions", "cluster_id", "cluster_canonical", "cluster_surface_forms",
                "cluster_pages", "cluster_ambiguous", "co_mentions_in_sentence",
            )
        }
        current.update(changes)
        return ContextRecord(**current)


# Everything except the span and its sentence. The sentence-only baseline in PLAN.md
# section 9 is defined as this list, applied.
SENTENCE_ONLY_BLANKS: tuple[str, ...] = (
    "block_kind",
    "heading",
    "title",
    "title_source",
    "role_mentions",
    "register_match",
    "cluster_id",
    "cluster_canonical",
    "cluster_surface_forms",
    "cluster_pages",
    "cluster_ambiguous",
    "message_index",
)


def _heading_before(page: Page, offset: int) -> str | None:
    best: str | None = None
    for block in page.blocks:
        if block.kind is BlockKind.HEADING and block.offsets.start <= offset:
            best = block.text.strip()
    return best


@dataclass
class ContextBuilder:
    """Builds a context record per detection for one document."""

    config: RequestConfig
    register: PublicRegister = field(default_factory=PublicRegister)
    directory: StaffDirectory | None = None

    def build(
        self, document: Document, detections: Sequence[Detection]
    ) -> tuple[ContextRecord, ...]:
        roles = RoleIndex.build(document)
        register = self.register.extended_with_letterhead(
            roles.letterhead_names(), organisation=document.metadata.author
        )
        person_names = [
            d.text for d in detections if d.entity_type is EntityType.PERSON
        ] + list(roles.all_names())
        matcher = RequesterMatcher(config=self.config, other_names=tuple(person_names))
        clusters = coref.build(detections, extra_names=roles.all_names())

        by_page = {p.number: p for p in document}
        out: list[ContextRecord] = []
        for det in detections:
            page = by_page[det.page]
            block = page.block_at(det.offsets)
            sentence_offsets = page.sentence_at(det.offsets)
            sentence = page.slice(sentence_offsets).strip()
            cluster = clusters.cluster_for(det)

            # The requester test runs against the cluster's fullest form as well as the
            # surface text, so "Byrne" resolves through "Aaron Byrne" rather than needing
            # the partial-match path.
            match = matcher.match(det.text)
            if not match.is_match and cluster is not None and cluster.canonical != det.text:
                by_canonical = matcher.match(cluster.canonical)
                if by_canonical.is_match and not cluster.ambiguous:
                    match = by_canonical

            name_for_role = cluster.canonical if cluster is not None else det.text
            title = roles.title_for(name_for_role) or roles.title_for(det.text)
            title_source = None
            if title is not None:
                mentions = roles.for_name(name_for_role) or roles.for_name(det.text)
                title_source = next((m.source for m in mentions if m.title), None)

            co_mentions = tuple(
                d.text
                for d in detections
                if d.entity_type is EntityType.PERSON
                and d.page == det.page
                and d.key != det.key
                and sentence_offsets.contains(d.offsets)
            )

            directory_match = None
            if self.directory is not None:
                if det.entity_type is EntityType.PERSON:
                    directory_match = self.directory.lookup_name(name_for_role)
                elif det.entity_type in (EntityType.EMAIL, EntityType.PHONE):
                    directory_match = self.directory.lookup_contact(det.text)

            out.append(
                ContextRecord(
                    detection=det,
                    doc_id=document.doc_id,
                    doc_type=document.doc_type,
                    page_number=det.page,
                    pages_in_document=len(document),
                    block_kind=block.kind if block else BlockKind.UNKNOWN,
                    sentence=sentence,
                    heading=_heading_before(page, det.offsets.start),
                    message_index=block.message_index if block else None,
                    requester_match=match,
                    register_match=register.lookup(name_for_role) or register.lookup(det.text),
                    directory_match=directory_match,
                    title=title,
                    title_source=title_source,
                    role_mentions=roles.for_name(name_for_role) or roles.for_name(det.text),
                    cluster_id=cluster.cluster_id if cluster else None,
                    cluster_canonical=cluster.canonical if cluster else None,
                    cluster_surface_forms=cluster.surface_forms if cluster else (),
                    cluster_pages=cluster.pages if cluster else (),
                    cluster_ambiguous=cluster.ambiguous if cluster else False,
                    co_mentions_in_sentence=co_mentions,
                )
            )
        return tuple(out)
