"""Over-redaction on records a public body actually released.

Every other number in this repository is measured against labels this project wrote. This
one is measured against decisions a public body's reviewer made, on real records, before
this tool existed. A span still visible in a completed release was looked at by a person and
judged releasable, so a box over it is an over-redaction against a human decision.

It is the only track here whose ground truth nobody in this project chose.

## One rate, and the refusal to report the other

Over-redaction only. What sat under the existing black boxes was removed before publication
and cannot be recovered, so there is no must-redact denominator, and a leak rate computed on
this track would be a number with nothing behind it. `Scored.leak_rate` raises on an
observed-label track for exactly this reason, and this module never asks it.

## What the denominator is, and the argument for it

The denominator is every span the detector finds in visible text that could be personal
information, and the numerator is the ones the tool would withhold. Spans the detector types
as an organisation, a place or a job title are counted separately rather than folded in:
those are the shapes the tool releases by design, and a corpus full of department names
would flatter the rate without saying anything about the decisions that matter. The table
prints both denominators so a reader can see the effect of the choice rather than trust it.

## The handicaps this track carries, all of them stated

A released PDF is a flat text layer. There is no signature block, no letterhead, no email
header, because nothing in the file says which paragraph was which, so `to_document` marks
every block BODY. The scanned track measures what that costs on synthetic records where the
truth is known: **twenty points of over-redaction**. This track pays the same price and has
no way to separate it out, so its figure should be read as the tool's performance on an
unstructured record rather than as its performance on a real one.

There is also no requester. The pipeline's strongest single rule is "this is the person who
asked, so their own information stays", and on a downloaded package nobody knows who asked.
Every span that would have been K1 is therefore something else here. Both effects push the
same way, and neither is a reason to discount the number: they are reasons to read it as a
floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sever.context.requester import RequestConfig
from sever.decide.pipeline import DecisionEngine, Proposal
from sever.detect.engine import SeverDetector
from sever.detect.types import Detector, EntityType
from sever.eval.confusion import Interval, _rate
from sever.ingest.releases import DEFAULT_DIR, DEFAULT_MANIFEST, Loaded, load
from sever.taxonomy.loader import default_taxonomy

# Types the tool releases by design. Counted, reported, and kept out of the headline
# denominator, because a release package full of department names would move the rate
# without saying anything about a decision anybody would argue with.
RELEASED_BY_DESIGN = frozenset(
    {EntityType.ORGANISATION, EntityType.LOCATION, EntityType.JOB_TITLE, EntityType.DATE}
)


@dataclass(frozen=True, slots=True)
class VisibleSpan:
    """One span the detector found in text a reviewer released. Clustered by document so
    the interval resamples over packages rather than over spans."""

    doc_id: str
    proposal: Proposal

    @property
    def withheld(self) -> bool:
        return self.proposal.withholds

    @property
    def could_be_personal(self) -> bool:
        return self.proposal.detection.entity_type not in RELEASED_BY_DESIGN


@dataclass
class ReleaseResult:
    packages: int = 0
    pages: int = 0
    spans: tuple[VisibleSpan, ...] = ()
    excluded: tuple[str, ...] = ()
    institutions: tuple[str, ...] = ()

    @property
    def personal_candidates(self) -> list[VisibleSpan]:
        return [s for s in self.spans if s.could_be_personal]

    def over_redaction(self, *, all_types: bool = False) -> Interval:
        pool = list(self.spans) if all_types else self.personal_candidates
        return _rate(pool, lambda s: s.withheld, seed=20270816)

    def by_code(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.personal_candidates:
            if s.withheld:
                out[s.proposal.code] = out.get(s.proposal.code, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def to_markdown(self) -> str:
        if not self.packages:
            lines = [
                "No release packages have been added yet.",
                "",
                "This is the only track whose ground truth nobody in this project chose: a "
                "span still visible in a completed access-to-information release was judged "
                "releasable by a public body's reviewer, so a box over it is an "
                "over-redaction against a real decision.",
                "",
                "There is no fetcher, deliberately. Library and Archives Canada serves "
                "completed release packages free of charge at "
                "<https://telechargerdemandesaicompletees-downloadcompletedatirequests.bac-lac.gc.ca>, "
                "behind an undocumented search endpoint. Reverse-engineering it was tried "
                "and abandoned: a track that depends on an undocumented endpoint staying "
                "stable is not reproducible in the way the rest of this repository is.",
                "",
                "So: download packages, run `sever releases add <file> --source-url <url>` "
                "for each, and run `sever eval-releases`. The manifest with its checksums is "
                "committed and the PDFs are not, so anyone can obtain the same bytes from "
                "the same URLs and reproduce the number, or get a checksum failure naming "
                "the file that differs.",
            ]
            if self.excluded:
                lines += ["", "**Packages excluded from this run**", ""]
                lines += [f"- {reason}" for reason in self.excluded]
            return "\n".join(lines)

        personal = self.personal_candidates
        lines = [
            f"**Corpus:** {self.packages} published release packages, {self.pages} pages "
            f"with visible text"
            + (f", from {', '.join(self.institutions)}" if self.institutions else "")
            + ". Track: real releases.",
            "",
            "| Denominator | Spans | Over-redaction |",
            "|---|---:|---|",
            f"| Spans that could be personal information | {len(personal)} | "
            f"{self.over_redaction()} |",
            f"| Every detected span, including the types the tool releases by design | "
            f"{len(self.spans)} | {self.over_redaction(all_types=True)} |",
            "",
            "**Leak rate is not reported and cannot be.** What sat under the existing black "
            "boxes was removed before publication, so there is no must-redact denominator "
            "on this track. `Scored.leak_rate` raises on an observed-label track rather than "
            "returning a number with nothing behind it.",
            "",
            "**Read this as a floor rather than as the tool's performance on a real record.** "
            "A released PDF is a flat text layer: nothing in the file says which paragraph "
            "was a signature block, so every block is body text and the rules lose the "
            "evidence they lean on hardest. `results/scanned.md` measures what that costs "
            "where the truth is known, and it is about twenty points. There is also no "
            "configured requester on a downloaded package, so every span that would have "
            "been the requester's own information is something else here. Both effects push "
            "the same way.",
        ]
        codes = self.by_code()
        if codes:
            lines += [
                "",
                "**What the tool would have withheld, by category**",
                "",
                "| Category | Spans withheld over text a reviewer released |",
                "|---|---:|",
            ]
            lines += [f"| `{code}` | {n} |" for code, n in codes.items()]
        if self.excluded:
            lines += [
                "",
                "**Packages excluded from this run**",
                "",
                *[f"- {reason}" for reason in self.excluded],
                "",
                "A package whose boxes still have text under them is excluded rather than "
                "scored, because its visible text carries values a reviewer withheld and "
                "counting those as must-keep labels would mark this tool down for agreeing "
                "with the reviewer.",
            ]
        return "\n".join(lines)


def run(
    *,
    manifest: Path = DEFAULT_MANIFEST,
    root: Path = DEFAULT_DIR,
    detector: Detector | None = None,
    loaded: Loaded | None = None,
) -> ReleaseResult:
    """Propose redactions over every visible span, and count the ones that would land."""
    data = loaded if loaded is not None else load(manifest, root)
    det = detector or SeverDetector()
    taxonomy = default_taxonomy()

    spans: list[VisibleSpan] = []
    for release in data.releases:
        # No requester: nobody knows who asked for a package downloaded from an archive.
        # Stated in the table rather than papered over with a guess.
        config = RequestConfig(request_id=release.record.file_name)
        proposals = DecisionEngine(config=config, detector=det, taxonomy=taxonomy).propose(
            release.document
        )
        spans.extend(
            VisibleSpan(doc_id=release.record.file_name, proposal=p) for p in proposals
        )

    return ReleaseResult(
        packages=len(data.releases),
        pages=data.pages,
        spans=tuple(spans),
        excluded=tuple(data.excluded),
        institutions=tuple(
            sorted({r.record.institution for r in data.releases if r.record.institution})
        ),
    )


def write(result: ReleaseResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!-- Generated by `sever eval-releases`. Do not hand-edit. -->\n\n"
        "# Over-redaction on records a public body actually released\n\n"
        + result.to_markdown()
        + "\n",
        encoding="utf-8",
    )
    return path


__all__ = ["RELEASED_BY_DESIGN", "ReleaseResult", "VisibleSpan", "run", "write"]
