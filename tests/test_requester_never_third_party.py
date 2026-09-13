"""The requester is never proposed as third-party information.

PLAN.md names this as one of the tests that has to fail meaningfully. It is the error that
makes the tool worse than useless: a person asks for their own file and gets it back with
their own name blacked out. So it is not tested on one hand-built example, it is tested
across the whole generated corpus, on every span the generator labelled K1, through the
full pipeline.

Note what is and is not asserted. R1 and R2 are forbidden outright. Escalation is allowed,
because a genuinely mixed span withholds pending a reviewer's cut and that is correct
behaviour rather than a failure; but the escalation rate on K1 spans is bounded, because a
tool that escalates every one of the requester's own spans has satisfied the letter of this
test and failed its purpose.
"""

from __future__ import annotations

from sever.context.requester import RequestConfig
from sever.corpus.personas import PersonaRole
from sever.decide.pipeline import DecisionEngine
from sever.taxonomy.loader import Decision

# A K1 span may escalate, but not often. Set from the measured rate with headroom; if a
# change pushes past it, that is a regression worth stopping the build for.
MAX_K1_ESCALATION_RATE = 0.35


def _config_for(item) -> RequestConfig:  # type: ignore[no-untyped-def]
    requester = next(
        (p for p in item.rendered.cast.values() if p.role is PersonaRole.REQUESTER), None
    )
    if requester is None:
        return RequestConfig(request_id=item.doc_id)
    return RequestConfig(
        request_id=item.doc_id,
        requester_name=requester.full_name,
        emails=(requester.personal_email,),
        phones=(requester.personal_phone,),
        identifiers=(requester.mcp, requester.file_number, requester.sin),
        addresses=(requester.home_address,),
        date_of_birth=requester.date_of_birth,
    )


def test_no_requester_span_is_ever_proposed_as_third_party(corpus, detector) -> None:  # type: ignore[no-untyped-def]
    offenders: list[str] = []
    k1_spans = 0
    escalated = 0

    for item in corpus:
        doc = item.rendered.document
        engine = DecisionEngine(config=_config_for(item), detector=detector)
        proposals = engine.propose(doc)
        for label in item.rendered.labels:
            if label.code != "K1":
                continue
            k1_spans += 1
            for p in proposals:
                if p.page != label.page:
                    continue
                if p.detection.offsets.intersection(label.offsets) is None:
                    continue
                if p.code in ("R1", "R2"):
                    offenders.append(
                        f"{doc.doc_id} p{label.page} {label.text!r} "
                        f"({label.field_name}) proposed as {p.code}: {p.reason}"
                    )
                if p.decision is Decision.ESCALATE:
                    escalated += 1

    assert not offenders, (
        f"{len(offenders)} of the requester's own spans were proposed as third-party "
        f"information:\n  " + "\n  ".join(offenders[:10])
    )
    assert k1_spans > 0, "the corpus produced no requester spans, so this test proved nothing"

    rate = escalated / k1_spans
    assert rate <= MAX_K1_ESCALATION_RATE, (
        f"{rate:.1%} of the requester's own spans were escalated, above the "
        f"{MAX_K1_ESCALATION_RATE:.0%} ceiling. Withholding is safe but a tool that "
        f"refers the requester's own information back to a human on every page has not "
        f"saved anyone any time."
    )


def test_the_requester_rule_fires_before_anything_else() -> None:
    """Ordering is the design. If K1 stops being first, this fails."""
    from sever.decide.rules import DEFAULT_RULES, requester_ambiguous, requester_own_information

    assert DEFAULT_RULES[0] is requester_ambiguous
    assert DEFAULT_RULES[1] is requester_own_information


def test_an_identifier_configured_to_the_requester_is_theirs(detector) -> None:  # type: ignore[no-untyped-def]
    from sever.ingest.document import BlockKind

    from .conftest import make_document

    doc = make_document([(BlockKind.BODY, "The client's MCP is 123 456 789 012 on file.")])
    config = RequestConfig(
        request_id="r", requester_name="Aaron Byrne", identifiers=("123 456 789 012",)
    )
    proposals = DecisionEngine(config=config, detector=detector).propose(doc)
    match = [p for p in proposals if "123 456 789 012" in p.detection.text]
    assert match, "the health number was not detected at all"
    assert match[0].code == "K1", (
        f"the requester's own health number was proposed as {match[0].code}; the "
        f"requester rule must run before the inherently-sensitive rule"
    )
