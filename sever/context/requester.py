"""Who made the request, and whether a span is about them.

The requester is configuration, not inference. A public body knows who asked, and asking
a model to guess would be both unnecessary and the most dangerous possible place to guess:
mistaking the requester for a third party redacts a person's own file from them, and
mistaking a third party for the requester releases someone else's information to a
stranger. Neither error is acceptable and neither is a modelling problem.

The matching here is deliberately conservative on one side and generous on the other. A
surname-only or forename-only mention is matched to the requester only when the document
contains no other person who could plausibly own that name; where it is ambiguous, the
span goes to escalation rather than to either answer.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class MatchStrength(StrEnum):
    NONE = "none"
    EXACT = "exact"
    # A full name matched after normalisation (case, accents, punctuation, initials).
    NORMALISED = "normalised"
    # Only part of the name matched and nothing else in the document competes for it.
    PARTIAL_UNAMBIGUOUS = "partial_unambiguous"
    # Only part of the name matched and something else could own it. Not a match: this
    # value exists so the rule layer can escalate rather than silently return NONE.
    PARTIAL_AMBIGUOUS = "partial_ambiguous"

    @property
    def is_match(self) -> bool:
        return self in (
            MatchStrength.EXACT,
            MatchStrength.NORMALISED,
            MatchStrength.PARTIAL_UNAMBIGUOUS,
        )


def normalise(text: str) -> str:
    """Casefold, strip accents and collapse punctuation and whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.casefold()).strip()


def normalise_identifier(text: str) -> str:
    """For numbers: keep digits and letters only, so 709-555-0142 matches 7095550142 and
    "MCP 123 456 789 012" matches "123456789012"."""
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


@dataclass(frozen=True, slots=True)
class RequestConfig:
    """The request this run is severing records for.

    `keep_requester_information` exists because the federal position and the provincial
    position genuinely differ (see the K1 note in taxonomy/federal.yaml). Set it false and
    the requester's own information is treated as R1, which is the strict Access to
    Information Act reading.
    """

    request_id: str
    jurisdiction: str = "federal"
    requester_name: str = ""
    # Maiden names, former names, the way the file spells it. Matched exactly as the
    # primary name is.
    aliases: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()
    date_of_birth: str | None = None
    keep_requester_information: bool = True
    # Set when the requester is acting for someone else (a solicitor, a parent). The
    # subject's information is then K1 and the agent's own is not.
    subject_name: str | None = None
    # The records are archival: held by an archives that received them for archival or
    # historical purposes. Turns on the 110-year rule (K7); see sever.context.age. Off by
    # default, because it is a fact about the records a public body states, not one the
    # tool can infer from how old a page looks.
    archival: bool = False
    # The year "110 years ago" is counted from. None is this year; a fixed year makes a
    # published number reproducible next year.
    as_of_year: int | None = None

    @property
    def year(self) -> int:
        import datetime as dt

        return self.as_of_year if self.as_of_year is not None else dt.date.today().year

    @property
    def names(self) -> tuple[str, ...]:
        out = [n for n in (self.requester_name, self.subject_name, *self.aliases) if n]
        return tuple(out)

    @property
    def name_parts(self) -> frozenset[str]:
        parts: set[str] = set()
        for name in self.names:
            parts.update(p for p in normalise(name).split() if len(p) > 1)
        return frozenset(parts)


@dataclass(frozen=True, slots=True)
class RequesterMatch:
    strength: MatchStrength
    matched_on: str | None = None
    detail: str | None = None

    @property
    def is_match(self) -> bool:
        return self.strength.is_match

    @property
    def is_ambiguous(self) -> bool:
        return self.strength is MatchStrength.PARTIAL_AMBIGUOUS


NO_MATCH = RequesterMatch(MatchStrength.NONE)


@dataclass
class RequesterMatcher:
    """Matches spans against the configured requester.

    `other_names` is every other person named in the document, which is what makes a
    partial match decidable: "Byrne" is the requester when the requester is Aaron Byrne
    and nobody else in the record is a Byrne, and it is ambiguous the moment a Siobhan
    Byrne appears.
    """

    config: RequestConfig
    other_names: tuple[str, ...] = ()
    _normalised_names: frozenset[str] = field(init=False)
    _identifiers: frozenset[str] = field(init=False)
    _other_parts: dict[str, set[str]] = field(init=False)

    def __post_init__(self) -> None:
        self._normalised_names = frozenset(normalise(n) for n in self.config.names)
        ids = [
            *self.config.emails,
            *self.config.phones,
            *self.config.identifiers,
            *([self.config.date_of_birth] if self.config.date_of_birth else []),
        ]
        self._identifiers = frozenset(normalise_identifier(i) for i in ids if i)
        self._other_parts = {}
        for other in self.other_names:
            if normalise(other) in self._normalised_names:
                continue
            for part in normalise(other).split():
                if len(part) > 1:
                    self._other_parts.setdefault(part, set()).add(other)

    def match(self, text: str) -> RequesterMatch:
        raw = text.strip()
        if not raw:
            return NO_MATCH

        for name in self.config.names:
            if raw == name:
                return RequesterMatch(MatchStrength.EXACT, matched_on=name)

        n = normalise(raw)
        if n in self._normalised_names:
            return RequesterMatch(MatchStrength.NORMALISED, matched_on=raw)

        ident = normalise_identifier(raw)
        if ident and ident in self._identifiers:
            return RequesterMatch(
                MatchStrength.EXACT, matched_on=raw, detail="matched a configured identifier"
            )
        for address in self.config.addresses:
            if n and n == normalise(address):
                return RequesterMatch(
                    MatchStrength.NORMALISED, matched_on=raw, detail="configured address"
                )

        parts = [p for p in n.split() if len(p) > 1]
        if parts and all(p in self.config.name_parts for p in parts):
            competing = {o for p in parts for o in self._other_parts.get(p, set())}
            if competing:
                return RequesterMatch(
                    MatchStrength.PARTIAL_AMBIGUOUS,
                    matched_on=raw,
                    detail=(
                        f"part of the requester's name, but also part of "
                        f"{sorted(competing)[0]!r} in this record"
                    ),
                )
            return RequesterMatch(
                MatchStrength.PARTIAL_UNAMBIGUOUS,
                matched_on=raw,
                detail="part of the requester's name and unique in this record",
            )
        return NO_MATCH


def matcher_for(
    config: RequestConfig, person_mentions: Sequence[str] = ()
) -> RequesterMatcher:
    return RequesterMatcher(config=config, other_names=tuple(person_mentions))
