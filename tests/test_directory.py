"""The staff directory: what it may match on, and the trap it must not walk into silently.

The measurement (results/directory.md) found that matching a directory on names leaks the
listed employee's own information wherever they are a third party in the record, which is
why the default matches on the work email address alone. These tests hold that default and
the rule's place in the order.
"""

from __future__ import annotations

import datetime as dt

import pytest

from sever.context.directory import DirectoryEntry, StaffDirectory
from sever.decide import rules

ENTRY = DirectoryEntry(
    name="Loretta Ivany",
    title="Regional Director",
    organisation="Department of Health and Community Services",
    work_email="loretta.ivany@gov.nl.ca.example",
    work_phone="709-555-1234",
    source="a test directory",
    checked_on=dt.date(2026, 10, 1),
)


def test_the_default_matches_the_work_email_and_nothing_else() -> None:
    d = StaffDirectory(entries=(ENTRY,))
    assert d.lookup_contact("Loretta.Ivany@gov.nl.ca.example") is not None
    assert d.lookup_contact("709-555-1234") is None
    assert d.lookup_name("Loretta Ivany") is None


def test_a_name_match_needs_a_full_name_when_names_are_switched_on() -> None:
    d = StaffDirectory(entries=(ENTRY,), match_on=frozenset({"name"}))
    assert d.lookup_name("loretta  IVANY") is not None
    assert d.lookup_name("Loretta") is None


def test_an_unknown_match_kind_is_refused() -> None:
    with pytest.raises(ValueError):
        StaffDirectory(entries=(ENTRY,), match_on=frozenset({"surname"}))


def test_the_directory_rule_runs_after_everything_that_can_see_personal_capacity() -> None:
    order = list(rules.DEFAULT_RULES)
    later = order.index(rules.staff_directory)
    for earlier in (
        rules.requester_own_information,
        rules.inherently_sensitive,
        rules.mixed_span,
        rules.official_capacity,
        rules.public_register,
    ):
        assert order.index(earlier) < later
