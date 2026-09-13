"""Public registers: the people whose names are already public, and where that was checked.

Three sources, in descending order of strength.

  1. A configured register file: published lists of ministers, deputy heads and officials.
     A match here is K3, because the name is demonstrably published.
  2. The document's own letterhead. A name printed on a department's letterhead is being
     published by the department in the act of writing the letter.
  3. A published organisation chart, loaded the same way as (1).

Every entry carries where it came from and when it was read, for the same reason the
taxonomy provisions do: "publicly available" is a claim, and a claim in a redaction
schedule needs a source. The register is a YAML file so a public body points it at their
own published lists rather than at these.

The register shipped in this repository is small and synthetic by design. It exists to
exercise the rule, not to be an authority on who holds office.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from sever.context.requester import normalise

DEFAULT_REGISTER = Path(__file__).parent / "registers" / "synthetic.yaml"


class RegisterEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    title: str | None = None
    organisation: str | None = None
    # Where this name is published, and when that was checked. A register entry with no
    # source is not evidence that anything is public.
    source: str
    checked_on: dt.date


class RegisterFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str | None = None
    entries: tuple[RegisterEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class RegisterMatch:
    entry: RegisterEntry
    how: str

    @property
    def reason(self) -> str:
        where = f" ({self.entry.title})" if self.entry.title else ""
        return f"{self.entry.name}{where} appears in {self.entry.source}, {self.how}"


@dataclass
class PublicRegister:
    """Names known to be public, plus any picked up from the document's letterhead."""

    entries: tuple[RegisterEntry, ...] = ()
    _by_name: dict[str, RegisterEntry] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._by_name = {normalise(e.name): e for e in self.entries}

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[RegisterEntry]:
        return iter(self.entries)

    def lookup(self, text: str) -> RegisterMatch | None:
        entry = self._by_name.get(normalise(text))
        if entry is None:
            return None
        return RegisterMatch(entry=entry, how="checked against the configured register")

    def extended_with_letterhead(
        self, names: Iterable[str], *, organisation: str | None = None
    ) -> PublicRegister:
        """Add names printed on the record's own letterhead.

        Scoped to one document on purpose. A name on this letter's letterhead is public
        for this letter; carrying it into the register for every other record in the
        request would be an inference, not an observation.
        """
        today = dt.date.today()
        extra = [
            RegisterEntry(
                name=n,
                organisation=organisation,
                source="the letterhead of the record itself",
                checked_on=today,
            )
            for n in names
            if n.strip() and normalise(n) not in self._by_name
        ]
        return PublicRegister(entries=(*self.entries, *tuple(extra)))


def load_register(path: Path = DEFAULT_REGISTER) -> PublicRegister:
    if not path.exists():
        return PublicRegister()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    parsed = RegisterFile.model_validate(data)
    return PublicRegister(entries=parsed.entries)


def load_registers(paths: Sequence[Path]) -> PublicRegister:
    entries: list[RegisterEntry] = []
    for p in paths:
        entries.extend(load_register(p).entries)
    return PublicRegister(entries=tuple(entries))
