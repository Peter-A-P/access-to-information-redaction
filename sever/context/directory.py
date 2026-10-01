"""A published staff directory: who works for the public body, in what job, at what address.

The weakest number in the README is over-redaction of officials acting in their official
capacity, and most of it is escalation: a name, a work email or a work telephone number
that the record never pairs with a title. A person reading the record would look the name
up. Public bodies publish their staff directories (the Government of Newfoundland and
Labrador's is searchable online), and "this person is listed as a Regional Director of
this department" is the same kind of evidence as a title in a signature block, observed
somewhere other than the record.

This is project 04's allow list, adapted. 04 lets a jurisdiction's list release a span
its detector would otherwise mask; here a directory lets the rules settle a span they
would otherwise escalate. The same caution applies: a list is evidence about a name, not
about the sentence the name is in.

**What a directory match does not prove.** That the person is acting in an official
capacity *in this record*. An employee who files a grievance is in the directory and is a
third party in their own complaint; the corpus has that trap on purpose (the HR memorandum),
and `sever eval-directory` measures what the rule does to it. A match is also a match on a
string: a third party who shares a name with an employee is matched too, and with a pool of
names the size of this province's, that happens.

So the rule that reads this runs after everything that can see personal capacity (the
requester, inherently sensitive identifiers, the mixed span), never decides a span the
record already decided, and is off unless a directory is configured.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from sever.context.requester import normalise, normalise_identifier


class DirectoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    title: str
    organisation: str
    work_email: str | None = None
    work_phone: str | None = None
    # Where the directory was published and when it was read. A directory entry is a claim
    # that ends up in a redaction schedule, so it needs a source a reader can check.
    source: str
    checked_on: dt.date


class DirectoryFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str | None = None
    entries: tuple[DirectoryEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class DirectoryMatch:
    entry: DirectoryEntry
    on: str

    @property
    def reason(self) -> str:
        return (
            f"{self.entry.name} is listed in {self.entry.source} as {self.entry.title}, "
            f"{self.entry.organisation} (matched on {self.on})"
        )


@dataclass
class StaffDirectory:
    entries: tuple[DirectoryEntry, ...] = ()
    # What a match may be made on. A name is evidence about a string that strangers share;
    # a work email address on the body's own domain is not shared with anybody, which is
    # why the measured configuration is email only. See results/directory.md.
    match_on: frozenset[str] = frozenset({"email"})
    _by_name: dict[str, DirectoryEntry] = field(default_factory=dict, init=False)
    _by_contact: dict[str, DirectoryEntry] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        unknown = self.match_on - {"name", "email", "phone"}
        if unknown:
            raise ValueError(f"a directory matches on name, email or phone, not {unknown}")
        for e in self.entries:
            if "name" in self.match_on:
                self._by_name.setdefault(normalise(e.name), e)
            if "email" in self.match_on and e.work_email:
                self._by_contact.setdefault(normalise_identifier(e.work_email), e)
            if "phone" in self.match_on and e.work_phone:
                self._by_contact.setdefault(normalise_identifier(e.work_phone), e)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[DirectoryEntry]:
        return iter(self.entries)

    def lookup_name(self, text: str) -> DirectoryMatch | None:
        """A full name only. A bare forename or surname matches too many people to be
        evidence of who is meant; the cluster's fullest form is what callers pass."""
        key = normalise(text)
        if len(key.split()) < 2:
            return None
        entry = self._by_name.get(key)
        return DirectoryMatch(entry=entry, on="name") if entry is not None else None

    def lookup_contact(self, text: str) -> DirectoryMatch | None:
        entry = self._by_contact.get(normalise_identifier(text))
        return DirectoryMatch(entry=entry, on="work contact") if entry is not None else None


def load_directory(path: Path, *, match_on: frozenset[str] = frozenset({"email"})) -> StaffDirectory:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return StaffDirectory(entries=DirectoryFile.model_validate(data).entries, match_on=match_on)
