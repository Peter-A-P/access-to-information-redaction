"""Rule fixtures, one per category, including the traps.

The traps are the point. Any tool gets "redact the complainant's address" right. What
separates a usable tool from a blunt one is an official named as a complainant, a requester
mentioned as a witness, and a deceased person with a date, and those are the cases below.
"""

from __future__ import annotations

import datetime as dt

import pytest

from sever.context.record import ContextBuilder
from sever.context.register import PublicRegister, RegisterEntry
from sever.context.requester import RequestConfig
from sever.decide import rules
from sever.decide.pipeline import DecisionEngine, DocumentProposals
from sever.detect.engine import SeverDetector
from sever.detect.types import EntityType
from sever.ingest.document import BlockKind, Document
from sever.taxonomy.loader import Decision, default_taxonomy

from .conftest import make_document, requester_config


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
    for p in proposals:
        if needle in p.detection.text:
            return p.code
    return None


# --- the straightforward cases ------------------------------------------------


def test_k2_an_official_with_a_title_in_a_signature_block(detector: SeverDetector) -> None:
    doc = make_document(
        [
            (BlockKind.BODY, "The inspection was carried out as scheduled."),
            (BlockKind.SIGNATURE, "Sincerely,\n\nMarie Doucette\nRegional Director"),
        ]
    )
    props = decide(doc, requester_config("Aaron Byrne"), detector)
    assert code_for(props, "Marie Doucette") == "K2"


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
