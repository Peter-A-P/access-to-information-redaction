"""Load and validate the taxonomy.

The taxonomy is the one part of this tool that is a claim about the law, so the loader is
deliberately unforgiving. It refuses a file that:

  * uses a decision that is not in the closed set declared in categories.yaml;
  * repeats a code;
  * leaves a code neither mapped nor explicitly declared unmapped for a jurisdiction;
  * cites a statute key that the jurisdiction file does not declare;
  * claims a provision without either the evidence of verification (a quote, the date it
    was checked and the URL it was checked against) or a written reason for not having
    checked it.

That last rule is the point of the whole module. A section number written from memory and
a section number read off the consolidated text look identical in a YAML file and are not
the same thing, so the format makes the difference impossible to leave unstated.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

TAXONOMY_DIR = Path(__file__).parent
CATEGORIES_FILE = TAXONOMY_DIR / "categories.yaml"


class Decision(StrEnum):
    """What a code does to a span. The closed set; categories.yaml declares the same four
    and the loader checks that the two agree, so neither can drift alone."""

    REDACT = "redact"
    KEEP = "keep"
    ESCALATE = "escalate"
    FLAG = "flag"

    @property
    def withholds(self) -> bool:
        """True when a proposal in this decision keeps the span out of the released
        record. Escalation withholds: the default for an undecided span is redaction with
        a flag, never release."""
        return self in (Decision.REDACT, Decision.ESCALATE)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DecisionSpec(_Strict):
    label: str
    description: str


class Category(_Strict):
    """One code: what it decides, what it means, and what a reviewer is being asked."""

    code: str
    decision: Decision
    name: str
    definition: str
    reviewer_question: str | None = None
    examples: tuple[str, ...] = ()
    traps: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _code_shape(self) -> Self:
        if not self.code or not self.code[0].isalpha() or not self.code[1:].isdigit():
            raise ValueError(f"code {self.code!r} must be a letter followed by digits, e.g. R1")
        return self


class Categories(_Strict):
    version: int
    updated: dt.date
    decisions: Mapping[str, DecisionSpec]
    codes: tuple[Category, ...]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        declared = set(self.decisions)
        known = {d.value for d in Decision}
        if declared != known:
            raise ValueError(
                f"categories.yaml declares decisions {sorted(declared)}, "
                f"but sever.taxonomy.Decision has {sorted(known)}; change both together"
            )
        seen: set[str] = set()
        for c in self.codes:
            if c.code in seen:
                raise ValueError(f"duplicate code {c.code}")
            seen.add(c.code)
        return self

    def __getitem__(self, code: str) -> Category:
        for c in self.codes:
            if c.code == code:
                return c
        raise KeyError(code)

    def __iter__(self) -> Iterator[Category]:  # type: ignore[override]
        return iter(self.codes)

    @property
    def codes_by_decision(self) -> dict[Decision, tuple[str, ...]]:
        out: dict[Decision, list[str]] = {d: [] for d in Decision}
        for c in self.codes:
            out[c.decision].append(c.code)
        return {d: tuple(v) for d, v in out.items()}


class Statute(_Strict):
    title: str
    citation: str
    url: str
    # A date when the consolidation page states one, the string "unknown" when the
    # source does not publish it (the NL Assembly page does not).
    consolidated_to: dt.date | str


class Provision(_Strict):
    """One section of one statute, cited for one code.

    Either verified (quote, checked_on, checked_against all present) or explicitly not
    (unverified holds the reason). Never both, never neither.
    """

    statute: str
    section: str
    heading: str
    quote: str | None = None
    checked_on: dt.date | None = None
    checked_against: str | None = None
    unverified: str | None = None

    @model_validator(mode="after")
    def _verified_or_excused(self) -> Self:
        evidence = (self.quote, self.checked_on, self.checked_against)
        has_all = all(e is not None for e in evidence)
        has_any = any(e is not None for e in evidence)
        where = f"{self.statute} s.{self.section}"
        if self.unverified is not None:
            if has_any:
                raise ValueError(
                    f"{where}: carries both verification evidence and an unverified "
                    f"reason; a provision is one or the other"
                )
            if not self.unverified.strip():
                raise ValueError(f"{where}: unverified must say why, not be empty")
            return self
        if not has_all:
            missing = [
                n for n, e in zip(("quote", "checked_on", "checked_against"), evidence, strict=True)
                if e is None
            ]
            raise ValueError(
                f"{where}: not verified and gives no reason; supply {', '.join(missing)} "
                f"or set unverified to the reason it has not been checked"
            )
        return self

    @property
    def is_verified(self) -> bool:
        return self.unverified is None

    @property
    def citation(self) -> str:
        return f"s. {self.section}"


class CodeMapping(_Strict):
    """The provisions cited for one code in one jurisdiction. An empty list is legitimate
    (E1 cites nothing, because an escalation is a question) and is not the same as the
    code being unmapped."""

    provisions: tuple[Provision, ...] = ()
    note: str | None = None
    # What this code does under *this* statute, where that differs from the default in
    # categories.yaml. Almost always absent: a code whose decision changes between
    # jurisdictions is usually two codes wearing one name, and the override exists for the
    # cases where the statutes genuinely disagree about the same question.
    #
    # Added on 2026-09-20 because verifying the provisions found two. ATIPPA 40(5)(j)
    # makes the time since a death a circumstance the head of a public body weighs, with
    # no period stated, where the federal Act excludes a person dead more than twenty
    # years from the definition outright; and ATIPPA has no general publicly-available
    # exception at all, where the federal 19(2)(b) does. Before this field the taxonomy
    # could record that in a note and the code would carry on releasing, which is a
    # documented difference the software does not implement. That is worse than an
    # undocumented one.
    decision: Decision | None = None
    decision_reason: str | None = None

    @model_validator(mode="after")
    def _override_is_explained(self) -> Self:
        if self.decision is not None and not self.decision_reason:
            raise ValueError(
                "a jurisdiction that overrides a code's decision must say why in "
                "decision_reason: the override changes what is released and the reason "
                "is what a reviewer or an auditor reads"
            )
        return self


class Jurisdiction(_Strict):
    jurisdiction: str
    name: str
    version: int
    updated: dt.date
    statutes: Mapping[str, Statute]
    mappings: Mapping[str, CodeMapping]
    unmapped: Mapping[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _statutes_exist(self) -> Self:
        for code, m in self.mappings.items():
            for p in m.provisions:
                if p.statute not in self.statutes:
                    raise ValueError(
                        f"{self.jurisdiction}/{code} cites statute {p.statute!r}, "
                        f"which is not declared in this file"
                    )
        overlap = set(self.mappings) & set(self.unmapped)
        if overlap:
            raise ValueError(
                f"{self.jurisdiction}: {sorted(overlap)} are both mapped and declared unmapped"
            )
        return self


class Taxonomy:
    """The categories plus every jurisdiction configured, checked against each other."""

    def __init__(self, categories: Categories, jurisdictions: Mapping[str, Jurisdiction]) -> None:
        self.categories = categories
        self.jurisdictions = dict(jurisdictions)
        self._check_complete()

    def _check_complete(self) -> None:
        codes = {c.code for c in self.categories}
        for key, j in self.jurisdictions.items():
            covered = set(j.mappings) | set(j.unmapped)
            missing = codes - covered
            if missing:
                raise ValueError(
                    f"jurisdiction {key}: codes {sorted(missing)} are neither mapped nor "
                    f"declared unmapped. Every code is answered for every jurisdiction, "
                    f"even if the answer is that the Act has no equivalent"
                )
            unknown = covered - codes
            if unknown:
                raise ValueError(f"jurisdiction {key}: unknown codes {sorted(unknown)}")

    def __getitem__(self, code: str) -> Category:
        return self.categories[code]

    def provisions(self, code: str, jurisdiction: str) -> tuple[Provision, ...]:
        j = self.jurisdictions[jurisdiction]
        m = j.mappings.get(code)
        return m.provisions if m is not None else ()

    def decision(self, code: str, jurisdiction: str | None = None) -> Decision:
        """What this code does, under this statute.

        The default lives in categories.yaml and is what every published number in this
        repository uses, because every published number is the federal configuration.
        A jurisdiction may override it, and two do: see `CodeMapping.decision`.

        `jurisdiction` is optional so that callers who genuinely have no jurisdiction in
        hand, such as a test asserting that every escalating code withholds, do not have
        to invent one. A caller that is deciding a real span passes it.
        """
        if jurisdiction is not None:
            m = self.jurisdictions[jurisdiction].mappings.get(code)
            if m is not None and m.decision is not None:
                return m.decision
        return self.categories[code].decision

    def overrides(self, jurisdiction: str) -> dict[str, tuple[Decision, str]]:
        """Every code this jurisdiction decides differently, and why. Printed in
        docs/taxonomy.md, because a difference between two configurations of the same tool
        is exactly the thing a reader should not have to find by diffing YAML."""
        out: dict[str, tuple[Decision, str]] = {}
        for code, m in self.jurisdictions[jurisdiction].mappings.items():
            if m.decision is not None and m.decision is not self.categories[code].decision:
                out[code] = (m.decision, m.decision_reason or "")
        return dict(sorted(out.items()))

    def verification_summary(self) -> dict[str, tuple[int, int]]:
        """Per jurisdiction: (verified provisions, total provisions). Reported in
        docs/taxonomy.md so the unchecked rows are visible rather than buried."""
        out: dict[str, tuple[int, int]] = {}
        for key, j in self.jurisdictions.items():
            all_p = [p for m in j.mappings.values() for p in m.provisions]
            out[key] = (sum(1 for p in all_p if p.is_verified), len(all_p))
        return out


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_categories(path: Path = CATEGORIES_FILE) -> Categories:
    return Categories.model_validate(_read_yaml(path))


def load_jurisdiction(path: Path) -> Jurisdiction:
    return Jurisdiction.model_validate(_read_yaml(path))


def load_taxonomy(directory: Path = TAXONOMY_DIR) -> Taxonomy:
    """Load categories.yaml and every other .yaml file in the directory as a jurisdiction.

    Dropping another jurisdiction file into this directory is the whole of adding a
    jurisdiction; nothing here enumerates them.
    """
    categories = load_categories(directory / "categories.yaml")
    jurisdictions: dict[str, Jurisdiction] = {}
    for p in sorted(directory.glob("*.yaml")):
        if p.name == "categories.yaml":
            continue
        j = load_jurisdiction(p)
        jurisdictions[j.jurisdiction] = j
    if not jurisdictions:
        raise ValueError(f"no jurisdiction files found in {directory}")
    return Taxonomy(categories, jurisdictions)


@lru_cache(maxsize=1)
def default_taxonomy() -> Taxonomy:
    """The shipped taxonomy. Cached because every span decision reads it."""
    return load_taxonomy()
