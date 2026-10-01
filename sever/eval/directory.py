"""What a published staff directory buys, and what it costs: `sever eval-directory`.

The directory is built from the corpus, because the corpus's department is fictional and
so is its directory: every persona cast as an official is an employee and is listed, with
their title, organisation, work email and work telephone. That is the honest analogue of a
public body pointing the tool at its own published directory, and it is also the reason
the measurement has to be careful about what it claims.

**Coverage is swept, not assumed.** A real directory is stale: people leave, move and
join, and a record can name an official of another body. Each run lists a seeded share of
the employees and leaves out the rest, at 50, 80 and 100 percent, beside the rules with no
directory at all.

**The leaks the rule causes are counted by name.** Two are expected and are the reason the
rule runs late and reads only full names: an employee who is the complainant in their own
grievance (the HR memorandum's trap, labelled R1), and a third party who shares a name
with an employee somewhere else in the corpus. Every leak decided by `staff_directory` is
listed with the template field it came from, so a reader can see which of the two it was.

Rules only, nothing spent. The headline tables do not use a directory, and this command
decides whether they should.
"""

from __future__ import annotations

import datetime as dt
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sever.context.directory import DirectoryEntry, StaffDirectory
from sever.corpus.generate import Corpus, build
from sever.corpus.personas import PersonaRole
from sever.decide.pipeline import DecisionEngine
from sever.detect.engine import SeverDetector
from sever.eval.confusion import Interval, Scored, score
from sever.eval.report import CachingDetector, config_for
from sever.taxonomy.loader import default_taxonomy

COVERAGES: tuple[float, ...] = (0.5, 0.8, 1.0)
# Name and every work contact, then the work email address alone. The first is the
# obvious design and the second is what the first one's leaks argue for.
MATCHES: tuple[frozenset[str], ...] = (
    frozenset({"name", "email", "phone"}),
    frozenset({"email"}),
)
DIRECTORY_SEED = 20271002
SOURCE = "the department's published staff directory (synthetic, built from the corpus)"


def directory_for(
    corpus: Corpus,
    coverage: float,
    *,
    match_on: frozenset[str] = frozenset({"email"}),
    seed: int = DIRECTORY_SEED,
) -> tuple[StaffDirectory, frozenset[str]]:
    """Every official in the corpus, then a seeded `coverage` share of them, and the
    persona ids listed, so a leak can be attributed to the listed person or a stranger."""
    officials: dict[str, DirectoryEntry] = {}
    for item in corpus:
        for persona in item.rendered.cast.values():
            if persona.role is not PersonaRole.OFFICIAL or persona.title is None:
                continue
            officials.setdefault(
                persona.persona_id,
                DirectoryEntry(
                    name=persona.full_name,
                    title=persona.title,
                    organisation=persona.organisation,
                    work_email=persona.work_email,
                    work_phone=persona.work_phone,
                    source=SOURCE,
                    checked_on=dt.date(2026, 10, 1),
                ),
            )
    ids = sorted(officials)
    random.Random(seed).shuffle(ids)
    kept = sorted(ids[: round(len(ids) * coverage)])
    return (
        StaffDirectory(entries=tuple(officials[i] for i in kept), match_on=match_on),
        frozenset(kept),
    )


@dataclass(frozen=True, slots=True)
class Row:
    coverage: float | None
    match_on: frozenset[str]
    entries: int
    scored: Scored
    decided: int
    # Leaks the directory rule caused, split by whose information it was: the listed
    # employee themselves (in a personal capacity in this record), or somebody else whose
    # name or number is the same string.
    leaks_listed: Counter[str]
    leaks_stranger: Counter[str]

    @property
    def label(self) -> str:
        if self.coverage is None:
            return "no directory"
        on = " and ".join(sorted(self.match_on))
        return f"{self.coverage:.0%} of employees, matched on {on}"

    def k2_over(self) -> Interval:
        return self.scored.over_redaction_rate("K2")


def _run_one(
    corpus: Corpus,
    detector: CachingDetector,
    directory: StaffDirectory | None,
    listed: frozenset[str],
    coverage: float | None,
    match_on: frozenset[str],
) -> Row:
    taxonomy = default_taxonomy()
    results: dict[str, tuple[object, object]] = {}
    for item in corpus:
        doc = item.rendered.document
        proposals = DecisionEngine(
            config=config_for(item), detector=detector, taxonomy=taxonomy, directory=directory
        ).propose(doc)
        results[doc.doc_id] = (proposals, item.rendered.labels)
    scored = score(results, taxonomy=taxonomy)  # type: ignore[arg-type]
    listed_leaks: Counter[str] = Counter()
    stranger_leaks: Counter[str] = Counter()
    decided = 0
    for o in scored.outcomes:
        if o.proposal is None or o.proposal.rule != "staff_directory":
            continue
        decided += 1
        if o.is_leak:
            bucket = listed_leaks if o.label.persona_id in listed else stranger_leaks
            bucket[o.label.field_name or "unknown"] += 1
    return Row(
        coverage=coverage,
        match_on=match_on,
        entries=len(directory) if directory is not None else 0,
        scored=scored,
        decided=decided,
        leaks_listed=listed_leaks,
        leaks_stranger=stranger_leaks,
    )


def run(*, documents: int = 210, seed: int = 20270802) -> tuple[Row, ...]:
    corpus = build(documents=documents, seed=seed)
    detector = CachingDetector(inner=SeverDetector())
    rows = [_run_one(corpus, detector, None, frozenset(), None, frozenset())]
    for match_on in MATCHES:
        for coverage in COVERAGES:
            directory, listed = directory_for(corpus, coverage, match_on=match_on)
            rows.append(_run_one(corpus, detector, directory, listed, coverage, match_on))
    return tuple(rows)


def to_markdown(rows: tuple[Row, ...]) -> str:
    lines = [
        "| Directory | Leak rate | Over-redaction | K2 over-redaction | Escalation | "
        "Decided by it | Leaks: the listed person | Leaks: a stranger |",
        "|---|---|---|---|---|---:|---:|---:|",
    ]
    for r in rows:
        s = r.scored
        lines.append(
            f"| {r.label} | {s.leak_rate()} | {s.over_redaction_rate()} | {r.k2_over()} | "
            f"{s.escalation_rate()} | {r.decided} | {sum(r.leaks_listed.values())} | "
            f"{sum(r.leaks_stranger.values())} |"
        )
    lines.append("")
    for r in rows[1:]:
        if r.coverage != 1.0:
            continue
        fields = r.leaks_listed + r.leaks_stranger
        if fields:
            lines.append(
                f"Leaks at {r.label}, by template field: "
                + ", ".join(f"`{f}` {n}" for f, n in fields.most_common(12))
                + "."
            )
        else:
            lines.append(f"At {r.label}, the directory rule released nothing that had to go.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write(rows: tuple[Row, ...], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!-- Generated by `sever eval-directory`. Do not hand-edit. -->\n\n"
        "# What a published staff directory buys\n\n"
        "Rules only, over the 210-document corpus. The directory lists the corpus's "
        "officials with title, organisation and work contacts, at the coverage in the "
        "first column; see `sever/eval/directory.py` for why coverage is swept and how the "
        "leaks are attributed. Intervals resample documents.\n\n" + to_markdown(rows),
        encoding="utf-8",
    )
    return path
