"""A code can mean the same question and get a different answer, and the tool has to agree.

Verifying the ATIPPA provisions on 2026-09-20 found two places where the statutes disagree
about what to do with the same span:

  * **K3.** Federally, 19(2)(b) releases personal information that is publicly available.
    ATIPPA has no equivalent: 40(2)(m) releases attendance at a public event and receipt of
    an honour, and nothing else.
  * **K4.** Federally, an individual dead more than twenty years is outside the definition
    of personal information. Under ATIPPA 40(5)(j) the time since a death is a circumstance
    the head of a public body weighs, with no period stated.

Before this, `decision` lived only in `categories.yaml` and the taxonomy could record the
difference in a note while the pipeline carried on releasing. A documented difference the
software does not implement is worse than an undocumented one, because the note reads like
a description of behaviour.

The property here is narrow and it matters: **the override changes NL and does not touch
federal.** Every published number in this repository is federal, so a regression in the
wrong direction here would move published figures without anyone editing a result.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sever.taxonomy.loader import CodeMapping, Decision, default_taxonomy

# K7, the federal 110-year archival rule, joined on 2026-10-18: no ATIPPA provision was
# found for it, so under NL it escalates.
OVERRIDDEN = ("K3", "K4", "K7")


def test_the_federal_configuration_overrides_nothing() -> None:
    """The guard on every published figure in the repository."""
    assert default_taxonomy().overrides("federal") == {}


def test_every_code_decides_federally_exactly_as_categories_yaml_says() -> None:
    t = default_taxonomy()
    for c in t.categories:
        assert t.decision(c.code, "federal") is c.decision
        assert t.decision(c.code) is c.decision


@pytest.mark.parametrize("code", OVERRIDDEN)
def test_the_codes_the_statutes_disagree_about_escalate_under_atippa(code: str) -> None:
    t = default_taxonomy()
    assert t.decision(code, "federal") is Decision.KEEP
    assert t.decision(code, "nl") is Decision.ESCALATE


def test_an_escalating_code_withholds_which_is_the_point_of_the_override() -> None:
    """Escalation is not a third state between keep and redact. It withholds, pending a
    person. If it did not, routing K3 and K4 there would have released them anyway."""
    t = default_taxonomy()
    for code in OVERRIDDEN:
        assert t.decision(code, "nl").withholds
        assert not t.decision(code, "federal").withholds


def test_a_code_the_statutes_agree_about_is_not_overridden() -> None:
    t = default_taxonomy()
    for code in ("R1", "K1", "K2"):
        assert t.decision(code, "nl") is t.decision(code, "federal")


def test_the_overrides_are_listed_with_their_reasons() -> None:
    """The generated page prints these, because a difference between two configurations of
    the same tool should not have to be found by diffing YAML."""
    overrides = default_taxonomy().overrides("nl")
    assert set(overrides) == set(OVERRIDDEN)
    for _decision, reason in overrides.values():
        assert len(reason) > 80, "a one-line reason is not a reason"


def test_an_override_with_no_reason_is_refused() -> None:
    """The override changes what is released. The reason is what a reviewer or an auditor
    reads, so it is required by the format rather than by a convention."""
    with pytest.raises(ValidationError, match="decision_reason"):
        CodeMapping(decision=Decision.ESCALATE)


def test_a_mapping_with_a_reason_and_no_override_is_fine() -> None:
    """Most mappings have neither. A reason without an override is harmless prose and the
    validator has no business refusing it."""
    CodeMapping(decision_reason="explaining something else")


# --- the hole the override opened, and the number that fills it ------------------


def test_a_span_the_statute_reserves_for_a_person_is_neither_keep_nor_redact() -> None:
    """The reason this went unnoticed for the whole build.

    `must_redact` is REDACT and `must_keep` is KEEP. Federally no code's true decision is
    ESCALATE, so the third case was empty and every published rate covered every span.
    Overriding two NL codes to escalate put 350 of the corpus's 5,355 spans into a state
    that the leak rate and the over-redaction rate both skip.
    """
    from sever.eval.confusion import SpanOutcome

    o = _outcome(Decision.ESCALATE, withheld=False)
    assert not o.must_redact
    assert not o.must_keep
    assert o.must_be_weighed
    assert not o.is_leak
    assert not o.is_over_redaction
    assert o.is_unweighed_release
    assert isinstance(o, SpanOutcome)


def test_withholding_a_span_the_statute_reserves_is_correct_and_not_over_redaction() -> None:
    """Escalation withholds, pending a person. That is the outcome the Act asks for, so
    counting it as over-redaction would penalise the tool for obeying the statute."""
    o = _outcome(Decision.ESCALATE, withheld=True)
    assert not o.is_unweighed_release
    assert not o.is_over_redaction


def test_the_rate_is_undefined_rather_than_perfect_where_the_act_reserves_nothing() -> None:
    """A column of 0.0% would read as a perfect score. There is no question to score."""
    from sever.corpus.labels import LabelSource
    from sever.eval.confusion import Scored

    federal_only = Scored(
        outcomes=(_outcome(Decision.KEEP, withheld=False), _outcome(Decision.REDACT, withheld=True)),
        label_source=LabelSource.CONSTRUCTED,
    )
    assert not federal_only.unweighed_release_rate().is_defined


def _outcome(true_decision: Decision, *, withheld: bool):  # type: ignore[no-untyped-def]
    from sever.corpus.labels import LabelledSpan
    from sever.decide.pipeline import Proposal, Source
    from sever.detect.types import Detection, EntityType
    from sever.eval.confusion import SpanOutcome
    from sever.ingest.document import Offsets

    detection = Detection(
        page=1,
        offsets=Offsets(0, 5),
        text="Hearn",
        entity_type=EntityType.PERSON,
        score=0.9,
        recogniser="test",
    )
    proposal = Proposal(
        detection=detection,
        code="K3",
        decision=Decision.ESCALATE if withheld else Decision.KEEP,
        confidence=0.9,
        reason="test",
        source=Source.RULE,
    )
    return SpanOutcome(
        doc_id="d1",
        label=LabelledSpan(
            page=1,
            offsets=Offsets(0, 5),
            text="Hearn",
            code="K3",
            persona_id="p1",
            field_name="third_party.surname",
        ),
        proposal=proposal,
        true_decision=true_decision,
        proposed_decision=proposal.decision,
    )
