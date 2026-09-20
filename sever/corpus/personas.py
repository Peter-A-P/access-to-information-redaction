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
import re
import unicodedata
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

# The surnames above are Newfoundland and Labrador surnames and every one of them is
# plain ASCII, single-token, no apostrophe, no Mac or Mc, no accent. That was not a
# decision, it was an oversight, and it made the corpus easier than the province.
#
# It was found from the outside. Project 04 shipped a second pass that had been blind to
# accented names, to Mac and Mc surnames, and to the part of O'Brien after the apostrophe,
# fixed it, and told 07 that re-running the evaluation would not show the difference
# because the corpus is ASCII. It did not: `boundary.redact` 0.5.4 measures identically to
# 0.5.1 here, to the decimal, on 5,355 values.
#
# A benchmark that cannot see a real bug being fixed cannot see it being introduced
# either. So the shapes below exist as a second, harder profile rather than a replacement:
# the published numbers stay on `PLAIN` and `results/names.md` reports what the same
# detector does on `NL`, which is the honest way to state the cost of the assumption.
#
# Why these shapes, for this province specifically:
#
#   * The apostrophe names are not decoration. O'Brien, O'Keefe, O'Reilly and O'Dea are
#     among the commonest surnames on the Avalon, and an apostrophe is a token boundary to
#     most tokenisers, so "O'Brien" is where a name detector splits and a redaction box
#     covers "O'" and releases "Brien".
#   * Mac and Mc prefixes carry an internal capital, which is the other place a
#     capitalisation heuristic breaks.
#   * The accented names are the French shore and Labrador: Bélanger, Benoît, Gaudet.
#     Accents also test the normalisation path in the requester matcher.
#   * Hyphenated surnames are ordinary and span a token boundary the other way.
#   * Two-token surnames (St. Croix, Le Drew) are real here and look like two names.
NL_SURNAMES = (
    "O'Brien", "O'Keefe", "O'Reilly", "O'Dea", "O'Neill", "D'Arcy",
    "MacDonald", "MacKenzie", "McCarthy", "McGrath", "McNeil", "MacInnis",
    "B\u00e9langer", "Beno\u00eet", "Gaudet", "Th\u00e9riault", "Cr\u00e9peau", "Duh\u00e9",
    "Coady-Vokey", "Snook-Hearn", "Pardy-Mercer",
    "St. Croix", "Le Drew", "St. George",
    "Doucette", "Byrne", "Gushue", "Penashue", "Noseworthy", "Ivany", "Tulk", "Rideout",
)

NL_GIVEN_NAMES = (
    "Se\u00e1n", "Sin\u00e9ad", "Ren\u00e9e", "Andr\u00e9", "No\u00ebl", "Ch\u00e9rie",
    "Mary-Kate", "Anne-Marie", "Jean-Guy",
    "Marie", "Aaron", "Siobhan", "Terrence", "Gerald", "Bernadette", "Colm",
    "Wallace", "Odette", "Hugh", "Desmond", "Fiona", "Loretta", "Malcolm",
    "Barry", "Nathaniel", "Perpetua", "Roland", "Emmett", "Josephine", "Maeve", "Ronan",
)


# One shape at a time, because `NL` mixes five of them and a mixed pool says only that
# something got harder. Project 04 asked the sharper question: which of apostrophes, Mac
# prefixes and accents dominates the drop, since the answer decides whether the next move
# is another recogniser or a better model.
#
# Each pool below varies the surname only and holds the forenames at the plain pool, so
# that one variable moves at a time. That understates each shape's effect a little, since
# a real cast has shaped forenames too, and it is the right trade: an isolated cause is
# worth more here than a maximal number.
#
# Eight of each, which is enough for the factory to fill a cast of six without repeating
# inside a document.
APOSTROPHE_SURNAMES = (
    "O'Brien", "O'Keefe", "O'Reilly", "O'Dea", "O'Neill", "D'Arcy", "O'Leary", "O'Driscoll",
)

MAC_SURNAMES = (
    "MacDonald", "MacKenzie", "McCarthy", "McGrath", "McNeil", "MacInnis", "McDonald",
    "MacLeod",
)

ACCENTED_SURNAMES = (
    "B\u00e9langer", "Beno\u00eet", "Th\u00e9riault", "Cr\u00e9peau", "Duh\u00e9",
    "L\u00e9garr\u00e9", "Ga\u00e9tan", "Bouch\u00e9",
)

HYPHENATED_SURNAMES = (
    "Coady-Vokey", "Snook-Hearn", "Pardy-Mercer", "Tulk-Rideout", "Byrne-Osmond",
    "Ivany-Whelan", "Gushue-Bonnell", "Hearn-Delaney",
)

PARTICLE_SURNAMES = (
    "St. Croix", "Le Drew", "St. George", "Le Blanc", "St. Pierre", "De Lacey",
    "Van Zeeland", "Le Feuvre",
)


class NameProfile(StrEnum):
    """Which name pool a corpus is built from.

    `PLAIN` is the published default and every committed result is measured on it. `NL`
    swaps in all five shapes at once and is the honest comparison. The five single-shape
    profiles exist to attribute the difference rather than only report it.

    Nothing else about the corpus changes between profiles, so every column is comparable
    span for span: same templates, same seed, same roles, same cast sizes.
    """

    PLAIN = "plain"
    NL = "nl"
    APOSTROPHE = "apostrophe"
    MAC = "mac"
    ACCENT = "accent"
    HYPHEN = "hyphen"
    PARTICLE = "particle"

    @property
    def pools(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        surnames = {
            NameProfile.APOSTROPHE: APOSTROPHE_SURNAMES,
            NameProfile.MAC: MAC_SURNAMES,
            NameProfile.ACCENT: ACCENTED_SURNAMES,
            NameProfile.HYPHEN: HYPHENATED_SURNAMES,
            NameProfile.PARTICLE: PARTICLE_SURNAMES,
        }.get(self)
        if surnames is not None:
            return GIVEN_NAMES, surnames
        if self is NameProfile.NL:
            return NL_GIVEN_NAMES, NL_SURNAMES
        return GIVEN_NAMES, SURNAMES

    @property
    def is_single_shape(self) -> bool:
        return self not in (NameProfile.PLAIN, NameProfile.NL)


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
    """A name as a government mail system would write it in an address.

    Transliterated to ASCII, because that is what directories do: Duhe with an acute
    accent gets an address reading `duhe`, not one carrying the accent. Getting this
    wrong in the generator would have been a corpus bug dressed up as a detector result,
    since an address with an accent in its local part is not a thing this tool will meet.

    It also makes the harder question askable. When the name on the page is accented and
    the address is not, a placeholder policy that substitutes only the exact surface form
    replaces the name and ships the surname inside the address. That is the same class of
    gap as a full name not licensing its parts, and it is why the persona ground-truth test
    normalises accents before it looks.

    Separators collapse rather than accumulate, so the two-token surname St. Croix gives
    `st.croix` and not the invalid `st..croix`.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Both apostrophes, the typewriter one and the typographic one, named by codepoint so
    # that the file stays plain ASCII and a re-encoding cannot quietly change what it means.
    lowered = ascii_only.lower()
    for apostrophe in ("'", chr(0x2019)):
        lowered = lowered.replace(apostrophe, "")
    collapsed = re.sub(r"[^a-z0-9]+", ".", lowered)
    return collapsed.strip(".")


@dataclass
class PersonaFactory:
    """Draws personas without repeating a name inside one corpus."""

    seed: int = 20270802
    profile: NameProfile = NameProfile.PLAIN
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
        given_pool, surname_pool = self.profile.pools
        for _ in range(500):
            pair = (self._rng.choice(given_pool), self._rng.choice(surname_pool))
            if pair not in self._used:
                self._used.add(pair)
                return pair
        raise RuntimeError("exhausted the name pool; widen the pools for this profile")

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
