"""The taxonomy is a claim about the law. These tests are what stop it drifting."""

from __future__ import annotations

import datetime as dt

import pytest
import yaml
from pydantic import ValidationError

from sever.taxonomy.loader import (
    Decision,
    Jurisdiction,
    Provision,
    load_taxonomy,
)
from sever.taxonomy.render_docs import DOCS_TAXONOMY, render


def test_every_code_is_answered_in_every_jurisdiction() -> None:
    t = load_taxonomy()
    codes = {c.code for c in t.categories}
    assert codes, "the taxonomy has no codes"
    for key, j in t.jurisdictions.items():
        answered = set(j.mappings) | set(j.unmapped)
        assert answered == codes, (
            f"{key} answers {sorted(answered)} but the taxonomy has {sorted(codes)}"
        )


def test_a_provision_is_verified_or_says_why_not() -> None:
    """The rule the whole format exists for."""
    with pytest.raises(ValidationError, match="not verified and gives no reason"):
        Provision(statute="atia", section="19(1)", heading="Personal information")


def test_a_provision_cannot_claim_both() -> None:
    with pytest.raises(ValidationError, match="one or the other"):
        Provision(
            statute="atia",
            section="19(1)",
            heading="Personal information",
            quote="something",
            checked_on=dt.date(2026, 9, 13),
            checked_against="https://example.invalid",
            unverified="and also not checked",
        )


def test_an_unverified_reason_must_say_something() -> None:
    with pytest.raises(ValidationError, match="must say why"):
        Provision(statute="atia", section="16", heading="Law enforcement", unverified="   ")


def test_verified_provisions_carry_the_evidence() -> None:
    t = load_taxonomy()
    for key, j in t.jurisdictions.items():
        for code, mapping in j.mappings.items():
            for p in mapping.provisions:
                if p.is_verified:
                    assert p.quote and p.quote.strip(), f"{key}/{code} verified with no quote"
                    assert p.checked_on is not None
                    assert p.checked_against and p.checked_against.startswith("http")


def test_a_jurisdiction_cannot_cite_an_undeclared_statute() -> None:
    bad = {
        "jurisdiction": "test",
        "name": "Test",
        "version": 1,
        "updated": "2026-09-13",
        "statutes": {
            "a": {
                "title": "A",
                "citation": "c. 1",
                "url": "https://example.invalid",
                "consolidated_to": "unknown",
            }
        },
        "mappings": {
            "R1": {
                "provisions": [
                    {"statute": "nope", "section": "1", "heading": "H", "unverified": "x"}
                ]
            }
        },
    }
    with pytest.raises(ValidationError, match="not declared in this file"):
        Jurisdiction.model_validate(bad)


def test_decisions_in_yaml_match_the_enum() -> None:
    """The YAML and the code cannot drift apart independently."""
    t = load_taxonomy()
    assert set(t.categories.decisions) == {d.value for d in Decision}


def test_escalation_withholds() -> None:
    """The safety property the whole tool rests on."""
    assert Decision.ESCALATE.withholds
    assert Decision.REDACT.withholds
    assert not Decision.KEEP.withholds
    assert not Decision.FLAG.withholds


def test_every_escalate_code_withholds() -> None:
    t = load_taxonomy()
    for code in t.categories.codes_by_decision[Decision.ESCALATE]:
        assert t.decision(code).withholds, f"{code} escalates but does not withhold"


def test_generated_docs_are_current() -> None:
    """docs/taxonomy.md is generated. If this fails, run `sever taxonomy render`."""
    if not DOCS_TAXONOMY.exists():
        pytest.skip("docs/taxonomy.md has not been generated yet")
    t = load_taxonomy()
    on_disk = DOCS_TAXONOMY.read_text(encoding="utf-8")
    # The generated file records the day it was written, so compare everything else.
    expected = render(t, generated_on=_generated_date(on_disk))
    assert on_disk == expected, (
        "docs/taxonomy.md is out of date with the YAML. Run `sever taxonomy render` and "
        "commit the result in the same commit as the YAML change."
    )


def _generated_date(text: str) -> dt.date:
    for line in text.splitlines():
        if line.startswith("Generated "):
            return dt.date.fromisoformat(line.split()[1])
    return dt.date.today()


def test_yaml_files_have_no_typographic_dashes() -> None:
    """House style, and it matters here: a schedule quoting a provision is published."""
    from sever.taxonomy.loader import TAXONOMY_DIR

    for path in sorted(TAXONOMY_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        # Named by codepoint rather than pasted, so this file itself stays clean:
        # em dash, en dash, figure dash, minus sign.
        for bad in ("\u2014", "\u2013", "\u2012", "\u2212"):
            assert bad not in text, f"{path.name} contains {bad!r}"
        # And the YAML must still parse, which the loader tests cover, but a syntax error
        # here gives a much clearer message than a pydantic failure downstream.
        yaml.safe_load(text)
