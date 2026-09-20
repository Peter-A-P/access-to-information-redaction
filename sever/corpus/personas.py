"""Personas, with roles assigned before a word of the document is written.

This is the whole trick behind the labelled corpus, and it is worth stating plainly. The
usual way to build an evaluation set for a redaction tool is to write documents and then
have someone label the spans, which is expensive and produces labels that are themselves
a judgement call. Here the causality is reversed: a persona is created as a requester, a
third party, an official, a deceased person or a public figure, and only then is it
rendered into a document. Every span's category follows from the role that was decided
first, so the labels are known by construction and the human's job is verification rather
than annotation.

Nobody here is real. The names are drawn from fixed pools chosen to look plausible for
Newfoundland and Labrador correspondence without matching any actual person; the phone
numbers are all in the 555 exchange reserved for fiction; the addresses are real street
names with invented numbers; the identifiers are generated in the right shape and are not
valid. No persona field is ever derived from a real record.
"""

from __future__ import annotations

import datetime as dt
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PersonaRole(StrEnum):
    """The role decides the category, which is why it is decided first."""

    REQUESTER = "requester"
    THIRD_PARTY = "third_party"
    OFFICIAL = "official"
    DECEASED = "deceased"
    PUBLIC_FIGURE = "public_figure"

    @property
    def default_code(self) -> str:
        """The taxonomy code a span belonging to this persona carries, absent an override
        on the individual placeholder."""
        return {
            PersonaRole.REQUESTER: "K1",
            PersonaRole.THIRD_PARTY: "R1",
            PersonaRole.OFFICIAL: "K2",
            PersonaRole.DECEASED: "K4",
            PersonaRole.PUBLIC_FIGURE: "K3",
        }[self]


# Fields that are about the position rather than the person. An official's span in one of
# these is K2; an official's span in anything else is R1, because a director's home
# address is not about being a director. This distinction is the whole must-keep column.
OFFICIAL_CAPACITY_FIELDS = frozenset(
    {
        "full_name",
        "given_name",
        "surname",
        "title",
        "work_email",
        "work_phone",
        "office_address",
    }
)

# Fields that are never about a person, whatever the persona's role. An employer's name is
# an institution, not personal information, so it is K6 for everyone and is not left to
# fall through the role rules.
NON_PERSONAL_FIELDS = frozenset({"organisation"})

# Deliberately NOT in OFFICIAL_CAPACITY_FIELDS: employee_id. The Privacy Act exclusion for
# officials covers information that "relates to the position or functions", and its
# examples are the title, the business address and telephone number, the classification and
# the salary range. A payroll identifier is an identifying number assigned to the
# individual, which is the definition's own paragraph (c), and releasing bodies redact
# them in practice. An official's employee number is therefore R1, not K2. This is a
# judgement, it moves the K2 column, and it is written down here so that it can be argued
# with rather than discovered in a confusion matrix.

GIVEN_NAMES = (
    "Marie", "Aaron", "Siobhan", "Terrence", "Chidinma", "Gerald", "Bernadette", "Colm",
    "Priya", "Wallace", "Odette", "Hugh", "Annika", "Desmond", "Fiona", "Rashid",
    "Loretta", "Malcolm", "Yolande", "Barry", "Ingrid", "Nathaniel", "Perpetua", "Roland",
    "Cecile", "Emmett", "Josephine", "Padraig", "Maeve", "Ignatius", "Delphine", "Ronan",
)

SURNAMES = (
    "Doucette", "Byrne", "Okonkwo", "Fitzgibbon", "Pardy", "Whelan", "Mercer", "Bursey",
    "Chaulk", "Noseworthy", "Kavanagh", "Hearn", "Ivany", "Tulk", "Rideout", "Snook",
    "Gushue", "Lundrigan", "Penashue", "Quirke", "Bonnell", "Halleran", "Skinner", "Vokey",
    "Marchand", "Delaney", "Osmond", "Pomeroy", "Rowsell", "Tobin", "Wiseman", "Yetman",
)

STREETS = (
    "Bannerman Street", "Duckworth Street", "LeMarchant Road", "Empire Avenue",
    "Kenmount Road", "Torbay Road", "Portugal Cove Road", "Freshwater Road",
    "Newtown Road", "Elizabeth Avenue", "Blackmarsh Road", "Topsail Road",
    "Hamilton Avenue", "Pennywell Road", "Merrymeeting Road", "Craigmillar Avenue",
)

TOWNS = (
    ("St. John's", "A1C"), ("Mount Pearl", "A1N"), ("Corner Brook", "A2H"),
    ("Gander", "A1V"), ("Grand Falls-Windsor", "A2A"), ("Labrador City", "A2V"),
    ("Conception Bay South", "A1W"), ("Paradise", "A1L"), ("Happy Valley-Goose Bay", "A0P"),
)

OFFICIAL_TITLES = (
    "Regional Director", "Manager, Client Services", "Senior Policy Analyst",
    "Program Officer", "Director of Operations", "Assistant Deputy Minister",
    "Access and Privacy Coordinator", "Investigator", "Case Worker",
    "Manager, Corporate Services", "Executive Director", "Policy Analyst",
)

PUBLIC_FIGURE_TITLES = (
    "Minister of Health and Community Services",
    "Deputy Minister of Health and Community Services",
    "Minister of Children, Seniors and Social Development",
    "Deputy Minister of Justice and Public Safety",
    "Information and Privacy Commissioner",
)

ORGANISATIONS = (
    "Department of Health and Community Services",
    "Department of Children, Seniors and Social Development",
    "Department of Justice and Public Safety",
    "Newfoundland and Labrador Health Services",
    "Department of Digital Government and Service NL",
)


@dataclass(frozen=True, slots=True)
class Persona:
    """One invented person, with the role that decides their category."""

    persona_id: str
    role: PersonaRole
    given_name: str
    surname: str
    organisation: str
    title: str | None = None
    work_email: str | None = None
    work_phone: str | None = None
    office_address: str | None = None
    employee_id: str | None = None
    home_address: str = ""
    town: str = ""
    postal_code: str = ""
    personal_email: str = ""
    personal_phone: str = ""
    date_of_birth: str = ""
    mcp: str = ""
    sin: str = ""
    file_number: str = ""
    date_of_death: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.surname}"

    def code_for(self, field_name: str, override: str | None = None) -> str:
        """The taxonomy code for a span of this persona's `field_name`.

        `override` is how a template says "this occurrence is different": an official
        named as the complainant in their own grievance is R1 even though the persona is
        an official. Overrides are how the traps get into the corpus with correct labels.
        """
        if override:
            return override
        if field_name in NON_PERSONAL_FIELDS:
            return "K6"
        if self.role is PersonaRole.OFFICIAL:
            return "K2" if field_name in OFFICIAL_CAPACITY_FIELDS else "R1"
        if self.role is PersonaRole.PUBLIC_FIGURE:
            # A minister's name and portfolio are public; a minister's medical care plan
            # number is not, and never was.
            return "K3" if field_name in OFFICIAL_CAPACITY_FIELDS else "R1"
        return self.role.default_code

    def get(self, field_name: str) -> str:
        value = getattr(self, field_name, None)
        if value is None or value == "":
            raise KeyError(
                f"persona {self.persona_id} ({self.role}) has no {field_name!r}; either the "
                f"template asks for a field this role does not carry, or the generator "
                f"needs to populate it"
            )
        return str(value)


def _phone(rng: random.Random) -> str:
    """709 area code, 555 exchange. The 555 block is reserved for fiction."""
    return f"709-555-{rng.randint(100, 199):03d}{rng.randint(0, 9)}"


def _postal(rng: random.Random, prefix: str) -> str:
    letters = "ABCEGHJKLMNPRSTVXY"
    return f"{prefix} {rng.randint(0, 9)}{rng.choice(letters)}{rng.randint(0, 9)}"


def _mcp(rng: random.Random) -> str:
    return " ".join(f"{rng.randint(0, 999):03d}" for _ in range(4))


def _sin(rng: random.Random) -> str:
    """A structurally valid but invented social insurance number.

    The check digit matters. A real SIN satisfies the Luhn checksum, and a detector worth
    anything uses that to tell a SIN from any other nine digits: project 04's
    `boundary:sin` does exactly that. This generator used to emit nine random digits, so
    roughly nine in ten personas carried a number no correct detector would ever flag, and
    the corpus quietly failed to exercise the SIN path at all. The number is still
    invented and belongs to nobody; it is merely shaped like the real thing, which is the
    whole point of a corpus.
    """
    digits = [rng.randint(0, 9) for _ in range(8)]
    # Luhn over the nine digits: the second, fourth, sixth and eighth are doubled, which
    # are indices 1, 3, 5 and 7 of these eight. Checked against the published example
    # 046 454 286, whose weighted digits sum to 50.
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            doubled = d * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += d
    digits.append((10 - total % 10) % 10)
    text = "".join(str(d) for d in digits)
    return f"{text[0:3]} {text[3:6]} {text[6:9]}"


def _slug(name: str) -> str:
    return name.lower().replace(" ", ".").replace("'", "")


@dataclass
class PersonaFactory:
    """Draws personas without repeating a name inside one corpus."""

    seed: int = 20270802
    _rng: random.Random = field(init=False)
    _used: set[tuple[str, str]] = field(default_factory=set, init=False)
    _n: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def begin_document(self) -> None:
        """Start a new document's cast.

        Names are unique within a document and may repeat across the corpus, which is both
        necessary and right. Necessary because a 210-document corpus needs more casts than
        a pool of thirty-two forenames and thirty-two surnames can make unique. Right
        because a real disclosure package names the same officials over and over, and a
        corpus where every document invents fresh people would quietly test an easier
        problem than the real one.
        """
        self._used.clear()

    def _name(self) -> tuple[str, str]:
        for _ in range(500):
            pair = (self._rng.choice(GIVEN_NAMES), self._rng.choice(SURNAMES))
            if pair not in self._used:
                self._used.add(pair)
                return pair
        raise RuntimeError("exhausted the name pool; widen GIVEN_NAMES or SURNAMES")

    def make(self, role: PersonaRole, *, organisation: str | None = None) -> Persona:
        rng = self._rng
        given, surname = self._name()
        self._n += 1
        pid = f"p{self._n:03d}"
        town, prefix = rng.choice(TOWNS)
        org = organisation or rng.choice(ORGANISATIONS)
        # Annotated because the bundle mixes a PersonaRole in with the strings, and
        # an inferred dict[str, str] makes every ** expansion below a type error.
        common: dict[str, Any] = {
            "persona_id": pid,
            "role": role,
            "given_name": given,
            "surname": surname,
            "organisation": org,
            "home_address": f"{rng.randint(1, 320)} {rng.choice(STREETS)}",
            "town": town,
            "postal_code": _postal(rng, prefix),
            "personal_email": f"{_slug(given)}.{_slug(surname)}@example.com",
            "personal_phone": _phone(rng),
            "date_of_birth": (
                dt.date(rng.randint(1948, 2004), rng.randint(1, 12), rng.randint(1, 28))
            ).isoformat(),
            "mcp": _mcp(rng),
            "sin": _sin(rng),
            "file_number": f"HCS-{rng.randint(2019, 2026)}-{rng.randint(100, 9999):04d}",
        }
        if role in (PersonaRole.OFFICIAL, PersonaRole.PUBLIC_FIGURE):
            titles = (
                PUBLIC_FIGURE_TITLES if role is PersonaRole.PUBLIC_FIGURE else OFFICIAL_TITLES
            )
            domain = "gov.nl.ca.example"
            return Persona(
                title=rng.choice(titles),
                work_email=f"{_slug(given)}{_slug(surname)}@{domain}",
                work_phone=_phone(rng),
                office_address=f"P.O. Box {rng.randint(8000, 8999)}, Confederation Building",
                employee_id=f"EMP-{rng.randint(10000, 99999)}",
                **common,
            )
        if role is PersonaRole.DECEASED:
            # More than twenty years ago, so K4 is correct and checkable. A death inside
            # twenty years belongs in the escalation fixtures, not here.
            year = rng.randint(1955, dt.date.today().year - 21)
            return Persona(
                date_of_death=dt.date(year, rng.randint(1, 12), rng.randint(1, 28)).isoformat(),
                **common,
            )
        return Persona(**common)

    def cast(self, spec: Sequence[tuple[str, PersonaRole]]) -> dict[str, Persona]:
        """Build a named cast for a document: {"requester": Persona, "official": ...}."""
        return {name: self.make(role) for name, role in spec}
