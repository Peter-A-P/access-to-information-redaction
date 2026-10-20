"""The context record: everything known about one candidate span before a decision.

This is the object the whole project turns on. The rules read it, the model is shown a
redacted view of it, the sentence-only baseline is defined as the same pipeline with most
of it blanked, and the explanation a reviewer reads is generated from the fields that
fired. Keeping it one explicit dataclass, rather than passing a document around and
letting each rule dig, is what makes that ablation honest: blanking a field is a one-line
change and it provably removes the information.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from sever.context.age import ARCHIVAL_YEARS, birth_year_beside, death_year_after, page_year
from sever.context.complaint import ComplaintParties, is_party_sentence
from sever.context.directory import DirectoryMatch, StaffDirectory
from sever.context.own_affairs import own_affairs_messages
from sever.context.register import PublicRegister, RegisterMatch
from sever.context.requester import RequestConfig, RequesterMatch, RequesterMatcher
from sever.context.roles import RoleIndex, RoleMention
from sever.detect import coref
from sever.detect.military import is_military_record, rank_beside
from sever.detect.recognisers import JOB_TITLE
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
    # A Canadian Armed Forces rank written beside this person, or beside another mention
    # of them, in a record the forces produced. Evidence that they are a member, which is
    # weaker than a title in a signature block; see `rules.military_rank`.
    rank: str | None = None

    # The archival rule (K7). Set only when the request says the records are archival:
    # the latest birth year that is 110 years ago, the latest year on this page, and the
    # latest year this person can have been born by what the record says beside their
    # name or any other mention of them. See sever.context.age.
    archival_cutoff: int | None = None
    page_year: int | None = None
    birth_year: int | None = None
    # The year of death the record states for this person, read across line breaks to the
    # end of the sentence and carried to their other mentions; see `death_year_after`.
    death_year: int | None = None

    cluster_id: str | None = None
    cluster_canonical: str | None = None
    cluster_surface_forms: tuple[str, ...] = ()
    cluster_pages: tuple[int, ...] = ()
    cluster_ambiguous: bool = False

    # Other people named in the same sentence. A span with a third party beside it in one
    # sentence is the R2 case, and this is how the rule sees it.
    co_mentions_in_sentence: tuple[str, ...] = ()

    # Set when the record is a confidential workplace complaint and this span is one of its
    # parties, or a job title in a sentence about one. Says which; see
    # sever.context.complaint.
    complaint_party: str | None = None

    # Set when the span sits in an email message about its writer's or recipient's own
    # leave, health, discipline or grievance. The rules that release an official stand
    # aside there; see sever.context.own_affairs.
    own_affairs_message: bool = False

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
            "rank": None,
            "birth_year": None,
            "death_year": None,
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
            "complaint_party": None,
            "own_affairs_message": False,
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
                "register_match", "directory_match", "title", "title_source", "rank",
                "archival_cutoff", "page_year", "birth_year", "role_mentions", "cluster_id", "cluster_canonical", "cluster_surface_forms",
                "cluster_pages", "cluster_ambiguous", "co_mentions_in_sentence",
                "complaint_party",
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
    "rank",
    "birth_year",
    "death_year",
    "role_mentions",
    "register_match",
    "cluster_id",
    "cluster_canonical",
    "cluster_surface_forms",
    "cluster_pages",
    "cluster_ambiguous",
    "message_index",
    "complaint_party",
    "own_affairs_message",
)


def _sentence_up_to(page: Page, start: int, end: int) -> str:
    """The text from the last full stop before `start` to `end`.

    The page's sentence splitter breaks at a line end, so "employed in this Department
    as / Director of Operations." comes back as "Director of Operations." alone. For the
    question "is this title in a sentence about a complaint party", reading back to the
    previous full stop is the sentence a person would read.
    """
    origin = max(0, start - 300)
    window = page.text[origin:end]
    at = start - origin
    cut = max(window.rfind(". ", 0, at), window.rfind(".\n", 0, at))
    return window[cut + 1 :] if cut >= 0 else window


def _completes_a_title(page: Page, start: int) -> bool:
    """True for the unit in "Manager, Corporate Services": an organisation written straight
    after a job title and a comma is part of the title, and withholding "Manager" while
    releasing "Corporate Services" releases most of what identifies the person."""
    before = page.text[max(0, start - 60) : start]
    return bool(_TITLE_THEN_COMMA.search(before))


_TITLE_THEN_COMMA = re.compile(rf"(?:{JOB_TITLE.pattern.pattern}),\s*$", JOB_TITLE.pattern.flags)


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

        # The archival rule's evidence: each page's latest year, and a birth stated beside a
        # person, carried to every mention of them as ranks are below.
        cutoff: int | None = None
        page_years: dict[int, int | None] = {}
        births: dict[tuple[int, int, int], int] = {}
        if self.config.archival:
            as_of = self.config.year
            cutoff = as_of - ARCHIVAL_YEARS
            page_years = {p.number: page_year(p.text, as_of=as_of) for p in document}
            births_by_cluster: dict[str, int] = {}
            for d in detections:
                if d.entity_type is not EntityType.PERSON:
                    continue
                born = birth_year_beside(
                    by_page[d.page].text, d.offsets, page_year=page_years[d.page]
                )
                if born is None:
                    continue
                births[d.key] = born
                c = clusters.cluster_for(d)
                if c is not None and not c.ambiguous:
                    # The latest of the births stated, which is the careful one.
                    births_by_cluster[c.cluster_id] = max(
                        born, births_by_cluster.get(c.cluster_id, born)
                    )
            for d in detections:
                c = clusters.cluster_for(d)
                if c is not None and c.cluster_id in births_by_cluster:
                    births[d.key] = births_by_cluster[c.cluster_id]

        # Ranks, per mention and then per person: "LCol Kromrey" on page two says the bare
        # "Kromrey" on page five is a member too. Only in a military record, where a rank
        # is the forces' own; elsewhere "Capt" is as likely a ship's master.
        ranks: dict[tuple[int, int, int], str] = {}
        if is_military_record(document):
            by_cluster: dict[str, str] = {}
            for d in detections:
                if d.entity_type is not EntityType.PERSON:
                    continue
                found = rank_beside(by_page[d.page].text, d.offsets)
                if found is None:
                    continue
                ranks[d.key] = found
                c = clusters.cluster_for(d)
                if c is not None and not c.ambiguous:
                    by_cluster.setdefault(c.cluster_id, found)
            for d in detections:
                c = clusters.cluster_for(d)
                if d.key not in ranks and c is not None and c.cluster_id in by_cluster:
                    ranks[d.key] = by_cluster[c.cluster_id]

        def sentence_of(det: Detection) -> str:
            page = by_page[det.page]
            return page.slice(page.sentence_at(det.offsets)).strip()

        parties = ComplaintParties.find(
            document,
            [
                (sentence_of(d), c.cluster_id if (c := clusters.cluster_for(d)) else None)
                for d in detections
                if d.entity_type is EntityType.PERSON
            ],
        )
        own_affairs = {p.number: own_affairs_messages(p) for p in document}

        # Deaths, per mention and then per person, as births are above.
        persons_on = {
            p.number: tuple(
                d.offsets for d in detections
                if d.page == p.number and d.entity_type is EntityType.PERSON
            )
            for p in document
        }
        deaths: dict[tuple[int, int, int], int] = {}
        deaths_by_cluster: dict[str, int] = {}
        for d in detections:
            if d.entity_type is not EntityType.PERSON:
                continue
            died = death_year_after(
                by_page[d.page].text,
                d.offsets,
                others=tuple(o for o in persons_on[d.page] if o != d.offsets),
            )
            if died is None:
                continue
            deaths[d.key] = died
            c = clusters.cluster_for(d)
            if c is not None and not c.ambiguous:
                deaths_by_cluster.setdefault(c.cluster_id, died)
        for d in detections:
            c = clusters.cluster_for(d)
            if d.key not in deaths and c is not None and c.cluster_id in deaths_by_cluster:
                deaths[d.key] = deaths_by_cluster[c.cluster_id]
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

            complaint_party = None
            if parties.clusters:
                if cluster is not None and cluster.cluster_id in parties.clusters:
                    complaint_party = "a party to the complaint"
                elif (
                    det.entity_type is EntityType.JOB_TITLE
                    or (
                        det.entity_type is EntityType.ORGANISATION
                        and _completes_a_title(page, det.offsets.start)
                    )
                ) and is_party_sentence(_sentence_up_to(page, det.offsets.start, det.offsets.end)):
                    complaint_party = "the job title of a party to the complaint"

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
                    rank=ranks.get(det.key),
                    archival_cutoff=cutoff,
                    page_year=page_years.get(det.page),
                    birth_year=births.get(det.key),
                    death_year=deaths.get(det.key),
                    role_mentions=roles.for_name(name_for_role) or roles.for_name(det.text),
                    cluster_id=cluster.cluster_id if cluster else None,
                    cluster_canonical=cluster.canonical if cluster else None,
                    cluster_surface_forms=cluster.surface_forms if cluster else (),
                    cluster_pages=cluster.pages if cluster else (),
                    cluster_ambiguous=cluster.ambiguous if cluster else False,
                    co_mentions_in_sentence=co_mentions,
                    complaint_party=complaint_party,
                    own_affairs_message=any(
                        m.contains(det.offsets) for m in own_affairs[det.page]
                    ),
                )
            )
        return tuple(out)
