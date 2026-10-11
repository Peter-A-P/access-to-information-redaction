"""Rule fixtures, one per category, including the traps.

The traps are the point. Any tool gets "redact the complainant's address" right. What
separates a usable tool from a blunt one is an official named as a complainant, a requester
mentioned as a witness, and a deceased person with a date, and those are the cases below.
"""

from __future__ import annotations

import datetime as dt

import pytest

from sever.context.record import ContextBuilder, ContextRecord
from sever.context.register import PublicRegister, RegisterEntry
from sever.context.requester import RequestConfig
from sever.decide import rules
from sever.decide.pipeline import DecisionEngine, DocumentProposals
from sever.detect.engine import SeverDetector
from sever.detect.types import EntityType
from sever.ingest.document import BlockKind, Document
from sever.taxonomy.loader import Decision, default_taxonomy

from .conftest import code_covering, make_document, requester_config


def decide(
    document: Document,
    config: RequestConfig,
    detector: SeverDetector,
    register: PublicRegister | None = None,
) -> DocumentProposals:
    engine = DecisionEngine(
        config=config, detector=detector, register=register or PublicRegister()
    )
    return engine.propose(document)


def code_for(proposals: DocumentProposals, needle: str) -> str | None:
    """By offset overlap; see conftest.code_covering for why not by detection text."""
    return code_covering(proposals.document, proposals, needle)


# --- the straightforward cases ------------------------------------------------


def test_k2_an_official_with_a_title_in_a_signature_block(detector: SeverDetector) -> None:
    doc = make_document(
        [
            (BlockKind.BODY, "The inspection was carried out as scheduled."),
            (BlockKind.SIGNATURE, "Sincerely,\n\nMarie Doucette\nRegional Director"),
        ]
    )
    props = decide(doc, requester_config("Aaron Byrne"), detector)
    assert code_for(props, "Marie Doucette") != "R1"


def test_k1_the_requester_is_kept(detector: SeverDetector) -> None:
    doc = make_document(
        [(BlockKind.BODY, "We wrote to Aaron Byrne on 4 March about the inspection.")]
    )
    props = decide(doc, requester_config("Aaron Byrne"), detector)
    assert code_for(props, "Aaron Byrne") == "K1"


def test_k3_a_name_in_the_public_register(detector: SeverDetector) -> None:
    register = PublicRegister(
        entries=(
            RegisterEntry(
                name="Perpetua Quirke",
                title="Minister of Health and Community Services",
                source="the published ministry list",
                checked_on=dt.date(2026, 9, 13),
            ),
        )
    )
    doc = make_document([(BlockKind.BODY, "The file was referred to Perpetua Quirke for signature.")])
    props = decide(doc, requester_config("Aaron Byrne"), detector, register)
    assert code_for(props, "Perpetua Quirke") == "K3"


def test_k6_an_organisation_is_not_personal_information(detector: SeverDetector) -> None:
    doc = make_document(
        [(BlockKind.BODY, "The Department of Health and Community Services replied on 9 May.")]
    )
    props = decide(doc, requester_config("Aaron Byrne"), detector)
    codes = {p.code for p in props if p.detection.entity_type is EntityType.ORGANISATION}
    assert codes <= {"K6"}, f"an organisation was not treated as non-personal: {codes}"


def test_r1_a_third_party_with_no_capacity_signal(detector: SeverDetector) -> None:
    """With no title and no register entry the tool must not release; here it escalates,
    which withholds, and that is the designed behaviour rather than a silent R1."""
    doc = make_document([(BlockKind.BODY, "The report was made by Odette Tulk of Gander.")])
    props = decide(doc, requester_config("Aaron Byrne"), detector)
    code = code_for(props, "Odette Tulk")
    assert code is not None
    assert default_taxonomy().decision(code).withholds


# --- the traps ----------------------------------------------------------------


def test_trap_an_official_is_still_an_official_for_their_title() -> None:
    """A grievance by an official: the complaint is personal, the title is not. The rules
    see a titled name, so K2 is the rules answer and the model layer is what is expected
    to catch the capacity switch. This test pins the rules behaviour so a change to it is
    deliberate rather than accidental."""
    from sever.context.record import ContextRecord
    from sever.detect.types import Detection
    from sever.ingest.document import DocumentType, Offsets

    ctx = ContextRecord(
        detection=Detection(
            page=1,
            offsets=Offsets(0, 14),
            text="Malcolm Whelan",
            entity_type=EntityType.PERSON,
            score=0.85,
            recogniser="test",
        ),
        doc_id="d",
        doc_type=DocumentType.HR_MEMORANDUM,
        page_number=1,
        pages_in_document=1,
        block_kind=BlockKind.BODY,
        sentence="The complaint was made by Malcolm Whelan, who is employed as Investigator.",
        title="Investigator",
        title_source="attendee_list",
    )
    result = rules.apply(ctx)
    assert result.outcome.code == "K2"
    assert result.decided_by_rule


def test_trap_a_requester_who_is_also_a_witness_stays_kept(detector: SeverDetector) -> None:
    doc = make_document(
        [
            (
                BlockKind.BODY,
                "Aaron Byrne, who was in the waiting area for an unrelated appointment, "
                "saw the fall and assisted.",
            )
        ]
    )
    props = decide(doc, requester_config("Aaron Byrne"), detector)
    code = code_for(props, "Aaron Byrne")
    assert code == "K1", f"the requester as a witness was placed as {code}"


def test_trap_an_officials_health_number_is_not_official_capacity(detector: SeverDetector) -> None:
    doc = make_document(
        [
            (BlockKind.SIGNATURE, "Marie Doucette\nRegional Director"),
            (BlockKind.BODY, "Her MCP is 123 456 789 012 and was recorded in error."),
        ]
    )
    props = decide(doc, requester_config("Aaron Byrne"), detector)
    assert code_for(props, "123 456 789 012") == "R1"


def test_trap_a_death_within_twenty_years_is_not_k4() -> None:
    from sever.context.record import ContextRecord
    from sever.detect.types import Detection
    from sever.ingest.document import DocumentType, Offsets

    ctx = ContextRecord(
        detection=Detection(
            page=1,
            offsets=Offsets(0, 12),
            text="Barry Osmond",
            entity_type=EntityType.PERSON,
            score=0.85,
            recogniser="test",
        ),
        doc_id="d",
        doc_type=DocumentType.INCIDENT_REPORT,
        page_number=1,
        pages_in_document=1,
        block_kind=BlockKind.BODY,
        sentence="The report was prepared by Barry Osmond, who died in 2019.",
    )
    outcome = rules.deceased_over_twenty_years(ctx)
    assert outcome is not None
    assert outcome.code == "E1", "a recent death must not qualify for the twenty-year rule"


def test_trap_a_death_over_twenty_years_ago_is_k4() -> None:
    from sever.context.record import ContextRecord
    from sever.detect.types import Detection
    from sever.ingest.document import DocumentType, Offsets

    ctx = ContextRecord(
        detection=Detection(
            page=1,
            offsets=Offsets(0, 12),
            text="Barry Osmond",
            entity_type=EntityType.PERSON,
            score=0.85,
            recogniser="test",
        ),
        doc_id="d",
        doc_type=DocumentType.INCIDENT_REPORT,
        page_number=1,
        pages_in_document=1,
        block_kind=BlockKind.BODY,
        sentence="The 1994 report was prepared by Barry Osmond, who died in 1998.",
    )
    outcome = rules.deceased_over_twenty_years(ctx)
    assert outcome is not None
    assert outcome.code == "K4"


def test_trap_an_ambiguous_partial_name_escalates(detector: SeverDetector) -> None:
    """Two Byrnes in one record. A bare "Byrne" is the one case where guessing is
    unacceptable in both directions."""
    doc = make_document(
        [
            (
                BlockKind.BODY,
                "Aaron Byrne attended with Siobhan Byrne. Byrne asked for a copy of the file.",
            )
        ]
    )
    contexts = ContextBuilder(config=requester_config("Aaron Byrne")).build(
        doc, tuple(detector.detect(doc))
    )
    bare = [c for c in contexts if c.text == "Byrne"]
    if not bare:
        pytest.skip("the detector did not surface the bare surname as its own span")
    result = rules.apply(bare[0])
    assert result.outcome.code in ("E1", "E2")


# --- the safety property ------------------------------------------------------


def test_no_rule_path_releases_an_undecided_span() -> None:
    """The fallthrough must withhold. This is the property the whole design rests on."""
    from sever.context.record import ContextRecord
    from sever.detect.types import Detection
    from sever.ingest.document import DocumentType, Offsets

    t = default_taxonomy()
    for entity_type in EntityType:
        ctx = ContextRecord(
            detection=Detection(
                page=1,
                offsets=Offsets(0, 7),
                text="unknown",
                entity_type=entity_type,
                score=0.5,
                recogniser="test",
            ),
            doc_id="d",
            doc_type=DocumentType.OTHER,
            page_number=1,
            pages_in_document=1,
            sentence="unknown",
        )
        result = rules.apply(ctx)
        decision = t.decision(result.outcome.code)
        if result.decided_by_rule:
            # Only the non-personal rule may release, and only for non-personal types.
            if decision is Decision.KEEP:
                assert result.outcome.rule == "not_personal_information", (
                    f"{entity_type} was released by {result.outcome.rule}"
                )
        else:
            assert decision.withholds, f"the fallthrough released a {entity_type} span"


@pytest.mark.parametrize("code", ["E1", "E2"])
def test_escalation_codes_withhold(code: str) -> None:
    assert default_taxonomy().decision(code).withholds


# --- a job title is a position, not a person -------------------------------------


def a_title_context(
    text: str, *, sentence: str, title: str | None = None, co_mentions: int = 1
) -> ContextRecord:
    """A detected job title, with a person mentioned in the same sentence."""
    from sever.detect.types import Detection
    from sever.ingest.document import DocumentType, Offsets

    return ContextRecord(
        detection=Detection(
            page=1,
            offsets=Offsets(0, len(text)),
            text=text,
            entity_type=EntityType.JOB_TITLE,
            score=0.85,
            recogniser="test",
        ),
        doc_id="d",
        doc_type=DocumentType.CORRESPONDENCE,
        page_number=1,
        pages_in_document=1,
        block_kind=BlockKind.BODY,
        sentence=sentence,
        title=title,
        co_mentions_in_sentence=tuple(f"person-{i}" for i in range(co_mentions)),
    )


def test_a_bare_job_title_is_released_as_not_personal_information() -> None:
    """The word "Minister" is a public office and putting a box over it helps nobody.

    Until 2026-09-21 a job title with any other person mentioned in the same sentence
    yielded, fell through to E1, and was withheld pending a reviewer. Measuring unlabelled
    detections found that every span this tool withheld that no persona owned was one of
    these: 16 in twenty documents, "Minister", "Deputy Minister", "Manager", "officer",
    about one box over the word "Minister" per page.
    """
    from sever.decide.rules import not_personal_information

    ctx = a_title_context("Minister", sentence="The Minister wrote to Odette Tulk.")
    outcome = not_personal_information(ctx)

    assert outcome is not None
    assert outcome.code == "K6"


def test_the_decision_layer_and_the_privacy_boundary_agree_about_job_titles() -> None:
    """They did not, and that was the argument for the change.

    `placeholders.NOT_SUBSTITUTED` holds JOB_TITLE and says why: a position is not a
    person, and substituting it would delete the evidence the K2 decision rests on. So the
    tool sent titles to a vendor on the grounds that they are not personal information,
    and then withheld them on the grounds that they might be. Both cannot be right.
    """
    from sever.decide.placeholders import NOT_SUBSTITUTED
    from sever.decide.rules import not_personal_information
    from sever.taxonomy.loader import Decision, default_taxonomy

    assert EntityType.JOB_TITLE in NOT_SUBSTITUTED, "the boundary treats it as impersonal"
    ctx = a_title_context("Manager", sentence="The Manager met Marie Chaulk.")
    outcome = not_personal_information(ctx)
    assert outcome is not None
    assert default_taxonomy().decision(outcome.code) is Decision.KEEP, "so must the rules"


def test_a_title_paired_with_this_person_still_yields() -> None:
    """The guard that matters is the one on positive evidence, and it is untouched. A span
    the record has paired with a title is a person, and K6 must not reach it."""
    from sever.decide.rules import not_personal_information

    ctx = a_title_context(
        "Regional Director",
        sentence="Marie Chaulk, Regional Director, signed.",
        title="Regional Director",
    )
    assert not_personal_information(ctx) is None


def test_a_name_mistyped_as_a_job_title_is_re_typed_before_the_rule_can_release_it() -> None:
    """A releasing type needs the sweep's protection the moment it starts releasing.

    JOB_TITLE joined `_RELEASING_TYPES` in the same commit that stopped it yielding, because
    adding the two separately is how a leak class gets introduced by a change that reads as
    a simplification. This is the "Tuglavina typed as a LOCATION" defect, waiting one type
    over.
    """
    from sever.detect.sweep import _RELEASING_TYPES

    assert EntityType.JOB_TITLE in _RELEASING_TYPES


# --- the parties to a confidential workplace complaint (reviewer 1, 2026-10-10) ------

_COMPLAINT = [
    (BlockKind.LETTERHEAD, "Department of Digital Government\nHuman Resources Division - IN CONFIDENCE"),
    (BlockKind.BODY, "Subject: Complaint under the Respectful Workplace Policy"),
    (
        BlockKind.BODY,
        "The complaint was made by Roland Chaulk, who is employed in this Department as\n"
        "Manager, Corporate Services. In the complaint Roland describes a pattern of conduct.",
    ),
    (
        BlockKind.BODY,
        "The complaint names Marie Doucette, Regional Director, as the respondent. The\n"
        "conduct concerns team meetings, all of it within the respondent's duties as "
        "Regional Director. Marie\nresponded in writing on 24 April.",
    ),
    (BlockKind.SIGNATURE, "Bernadette Halleran\nProgram Officer"),
]


def test_both_parties_to_a_confidential_complaint_are_third_parties(
    detector: SeverDetector,
) -> None:
    """A complaint by or against an employee is about them, not their position."""
    props = decide(make_document(_COMPLAINT), requester_config("Aaron Byrne"), detector)
    # The later given-name mentions too, through the coreference cluster.
    for needle in ("Roland Chaulk", "Marie Doucette", "Roland describes", "Marie\nresponded"):
        assert code_for(props, needle) == "R1", needle


def test_a_partys_title_is_withheld_with_the_name(detector: SeverDetector) -> None:
    """In a unit with one Regional Director, the title is the name. The unit after the
    comma is part of the title, and a title that starts on a new line is still in the
    sentence that names the party."""
    props = decide(make_document(_COMPLAINT), requester_config("Aaron Byrne"), detector)
    doc = props.document
    text = doc.page(1).text
    withheld = [
        (p.detection.offsets.start, p.detection.offsets.end) for p in props.proposals if p.withholds
    ]
    for needle in ("Manager, Corporate Services", "Regional Director, as"):
        at = text.index(needle)
        title = needle.removesuffix(", as")
        span = range(at, at + len(title))
        letters = [i for i in span if text[i].isalnum()]
        assert all(any(s <= i < e for s, e in withheld) for i in letters), needle


def test_the_author_of_the_complaint_memo_is_still_an_official(detector: SeverDetector) -> None:
    props = decide(make_document(_COMPLAINT), requester_config("Aaron Byrne"), detector)
    assert code_for(props, "Bernadette Halleran") == "K2"


def test_a_party_who_is_the_requester_keeps_their_own_information(
    detector: SeverDetector,
) -> None:
    props = decide(make_document(_COMPLAINT), requester_config("Roland Chaulk"), detector)
    assert code_for(props, "Roland Chaulk") == "K1"


def test_the_same_sentence_outside_a_confidential_complaint_is_not_a_party(
    detector: SeverDetector,
) -> None:
    """The record has to be a confidential workplace complaint: a service complaint about
    the department names its staff in their roles. (Here the rules escalate her, because a
    title in running text is not one they pair; what matters is that it is not R1.)"""
    doc = make_document(
        [
            (BlockKind.BODY, "Re: your service complaint about the licensing office"),
            (
                BlockKind.BODY,
                "The complaint names Marie Doucette, Regional Director, as the manager "
                "responsible for the licensing office.",
            ),
        ]
    )
    props = decide(doc, requester_config("Aaron Byrne"), detector)
    assert code_for(props, "Marie Doucette") != "R1"
