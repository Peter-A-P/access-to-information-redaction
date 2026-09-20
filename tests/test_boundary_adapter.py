"""Detection and the policy through `boundary.redact`, project 04's engine.

Skipped entirely where `boundary` is not installed, because it is an optional extra and
the published rules-only baseline runs in CI without it.

The tests here are of *this project's* behaviour when composed with 04's, not of 04. The
distinction matters for one of them: `test_the_layered_policy_masks_what_the_inner_one
_misses` must keep passing after 04 fixes the Medical Care Plan gap it was written for.
It asserts that the layered policy is clean, not that the inner one is dirty.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from sever.detect.types import EntityType
from sever.ingest.document import BlockKind

from .conftest import make_document

boundary = pytest.importorskip("boundary.redact", reason="the gateway extra is not installed")

from sever.detect.boundary_adapter import (  # noqa: E402
    SEVER_EXTRAS,
    BoundaryDetector,
    LayeredPolicy,
    policy_for,
)


@pytest.fixture(scope="module")
def detector() -> BoundaryDetector:
    """Presidio's engine takes about ten seconds to start; build one."""
    return BoundaryDetector()


LETTER = (
    "Sincerely,\nMarie Doucette\nRegional Director\n"
    "Contact the complainant Aaron Penashue at aaronpenashue@gov.nl.ca.example or "
    "709-555-0142 about file HCS-2024-0881. DOB 1977-12-13, and he lives at "
    "14 Bannerman Street, A1C 3Z9."
)


def test_the_adapter_returns_this_projects_entity_types(detector: BoundaryDetector) -> None:
    doc = make_document([(BlockKind.BODY, LETTER)])
    found = {d.entity_type for d in detector.detect(doc)}
    assert EntityType.EMAIL in found
    assert EntityType.PHONE in found
    assert EntityType.FILE_NUMBER in found
    assert EntityType.DATE_OF_BIRTH in found
    assert EntityType.POSTAL_CODE in found


def test_offsets_index_the_page_they_claim_to(detector: BoundaryDetector) -> None:
    """The contract every downstream box depends on: page_text[start:end] == text."""
    doc = make_document([(BlockKind.BODY, LETTER)])
    for d in detector.detect(doc):
        page = doc.page(d.page)
        assert page.slice(d.offsets) == d.text, f"{d.recogniser} lied about {d.text!r}"


def test_no_detection_crosses_a_line_break(detector: BoundaryDetector) -> None:
    """One of the two defects this project reported, now guaranteed by 04's analyzer."""
    doc = make_document([(BlockKind.BODY, LETTER)])
    for d in detector.detect(doc):
        assert "\n" not in d.text, f"{d.recogniser} returned {d.text!r}"


def test_no_two_detections_overlap(detector: BoundaryDetector) -> None:
    doc = make_document([(BlockKind.BODY, LETTER)])
    spans = sorted(detector.detect(doc), key=lambda d: (d.page, d.offsets.start))
    for a, b in pairwise(spans):
        if a.page == b.page:
            assert not a.offsets.overlaps(b.offsets), f"{a.text!r} overlaps {b.text!r}"


def test_the_multi_label_government_email_is_found(detector: BoundaryDetector) -> None:
    """The other defect reported: Presidio saw only `gov.nl.ca`, as a URL."""
    doc = make_document([(BlockKind.BODY, LETTER)])
    emails = [d for d in detector.detect(doc) if d.entity_type is EntityType.EMAIL]
    assert [d.text for d in emails] == ["aaronpenashue@gov.nl.ca.example"]


def test_this_projects_extras_survive_the_round_trip(detector: BoundaryDetector) -> None:
    """A street address and a job title go in through `extra=` with boundary's nearest
    entity type and have to come back out as this project's own."""
    doc = make_document(
        [(BlockKind.BODY, "Marie Doucette, Regional Director, of 14 Bannerman Street wrote.")]
    )
    by_type = {d.entity_type: d.text for d in detector.detect(doc)}
    assert by_type.get(EntityType.JOB_TITLE) == "Regional Director"
    assert EntityType.ADDRESS in by_type, by_type


def test_the_extras_are_the_two_boundary_has_no_recogniser_for() -> None:
    names = {r.name for r in SEVER_EXTRAS}
    assert names == {"street_address", "job_title"}


# --- the policy ---------------------------------------------------------------


def test_the_layered_policy_masks_what_the_inner_one_misses(
    detector: BoundaryDetector,
) -> None:
    """Defence in depth, asserted on the layered result only.

    Written because 04's policy returned a Medical Care Plan number in its conventional
    spaced form unchanged, and did not refuse. This test must keep passing when that is
    fixed: it says the layered policy is clean, not that the inner one is not.
    """
    text = "The client's MCP is 123 456 789 012 and the file is open."
    doc = make_document([(BlockKind.BODY, text)])
    layered = policy_for(doc, detector)
    out = layered.outbound(text)
    assert "123 456 789 012" not in out, out
    assert "123456789012" not in out.replace(" ", ""), out


@pytest.mark.parametrize(
    "value",
    ["123 456 789 012", "123-456-789-012", "123456789012"],
)
def test_every_health_number_format_is_masked(
    detector: BoundaryDetector, value: str
) -> None:
    """A Medical Care Plan number is written all three ways on real forms."""
    text = f"MCP {value} on the file."
    doc = make_document([(BlockKind.BODY, text)])
    out = policy_for(doc, detector).outbound(text)
    assert value not in out, f"{value!r} survived as {out!r}"


def test_the_scrub_can_be_turned_off_for_the_ablation(detector: BoundaryDetector) -> None:
    """The paired ablation needs to measure what the second pass costs, which means being
    able to run without it."""
    text = "The client's MCP is 123 456 789 012."
    doc = make_document([(BlockKind.BODY, text)])
    bare = LayeredPolicy(policy=policy_for(doc, detector).policy, scrub=False)
    assert bare.outbound(text) == policy_for(doc, detector).policy.outbound(text)


def test_a_substituted_name_rehydrates(detector: BoundaryDetector) -> None:
    text = "Marie Doucette signed the letter and Marie approved it."
    doc = make_document([(BlockKind.BODY, text)])
    layered = policy_for(doc, detector)
    substituted = layered.policy.outbound(text)
    assert "Doucette" not in substituted, substituted
    assert "Doucette" in layered.rehydrate(substituted)


def test_the_layered_policy_never_feeds_boundary_its_own_output() -> None:
    """boundary 0.5.4 makes that an error, and it is right to.

    `Policy.outbound` refuses text carrying a placeholder it minted, because a document
    that already contains the literal string a placeholder looks like used to rehydrate
    into a real name: a name in a released record that was never in the source. 04 shipped
    the guard; this asserts that `LayeredPolicy` is on the correct side of it, since it
    runs one substitution pass and then applies this project's scrub on top rather than
    calling `outbound` twice.
    """
    from boundary.redact import Analyzer, Policy

    source = "Odette Tulk lives at 14 Bannerman Street."
    spans = Analyzer().analyze([source])
    layered = LayeredPolicy(policy=Policy(spans))

    once = layered.outbound(source)
    assert "Odette" not in once and "Tulk" not in once

    # The round trip still works through this project's scrub, which is what would break
    # if the scrub mangled a placeholder.
    assert layered.rehydrate(once) == source

    # And the underlying policy does refuse a second pass, so the guard is real and this
    # test is not asserting against a version that lacks it.
    with pytest.raises(Exception, match=r"(?i)refus|placeholder"):
        layered.policy.outbound(once)


def test_a_rebuilt_policy_carries_span_placeholders_but_not_second_pass_ones() -> None:
    """Which half of a rebuilt policy survives, measured rather than assumed.

    An earlier version of this file claimed the refusal was per-instance, full stop, on the
    strength of the case above. That was half right and the wrong half was stated. Project
    04 corrected it and the correction is worth keeping as an assertion, because the two
    halves behave differently and the difference decides whether a reviewer sees a name or
    a placeholder:

      * A placeholder **derived from a span** is minted identically by any policy over the
        same spans. A rebuilt policy refuses it and rehydrates it. Nothing is lost.
      * A placeholder the **second pass** minted was discovered while redacting and is not
        recoverable from the spans. A rebuilt policy does not refuse it, does not resolve
        it, and returns the text with the placeholder still in it.

    The second case is the quiet one: no exception, no name, just an unresolved token where
    a name should be. `Policy(spans, vault=...)` in 0.5.5 is what closes it.
    """
    from boundary.redact import Analyzer, Policy

    # Entities the analyzer types from the spans themselves.
    derived = "Email aaronpenashue@gov.nl.ca.example or call 709-555-0142."
    spans = Analyzer().analyze([derived])
    first = Policy(spans)
    out = first.outbound(derived)
    assert "<EMAIL_1>" in out, out
    with pytest.raises(Exception, match=r"(?i)refus|placeholder"):
        Policy(spans).outbound(out)
    assert Policy(spans).rehydrate(out) == derived

    # A value only the second pass finds, on a page the analyzer types nothing in.
    second_pass = "Odette Tulk lives at 14 Bannerman Street."
    spans2 = Analyzer().analyze([second_pass])
    original = Policy(spans2)
    masked = original.outbound(second_pass)
    assert "NAME_LIKE" in masked, masked

    rebuilt = Policy(spans2)
    # No refusal, and no resolution: the placeholders come back unchanged.
    assert rebuilt.rehydrate(masked) == masked
    # The vault is what carries them across.
    assert Policy(spans2, vault=original.vault).rehydrate(masked) == second_pass
