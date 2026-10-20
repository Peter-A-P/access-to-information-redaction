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

from dataclasses import dataclass, field, replace
from pathlib import Path

from sever.context.requester import RequestConfig
from sever.decide import rules as rules_mod
from sever.decide.pipeline import DEFAULT_THRESHOLD, DecisionEngine, ModelDecider, Proposal
from sever.detect import recognisers as rec
from sever.detect.engine import SeverDetector
from sever.detect.military import has_name_shaped_token
from sever.detect.types import Detector, EntityType
from sever.eval.confusion import Interval, _rate
from sever.ingest.document import Document, Offsets
from sever.ingest.layout import recover_blocks
from sever.ingest.ocr import paragraph_blocks
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


@dataclass(frozen=True, slots=True)
class Configuration:
    """One row of the ablation: whether the layout is read back, whether the tool knows
    the forces' vocabulary and screens out OCR noise and the release stamp, and whether
    the archival 110-year rule applies."""

    name: str
    recover_layout: bool
    vocabulary: bool
    # The 110-year rule (K7), for packages an archives released. Applied only where the
    # package's institution is Library and Archives Canada.
    archival: bool = False


CONFIGURATIONS: tuple[Configuration, ...] = (
    Configuration("as scored until 2026-10-17: flat text, no military vocabulary", False, False),
    # The signature reader takes a rank under a name as a title in every row, so this one
    # already has that much of the vocabulary; what it lacks is the rest.
    Configuration("layout recovered (a rank under a signature counts as a title)", True, False),
    Configuration("vocabulary and screens: ranks, units, OCR noise, the stamp", False, True),
    Configuration("layout and vocabulary, no archival rule", True, True),
    Configuration("all of it, with the 110-year archival rule (as it now ships)", True, True, True),
)


@dataclass(frozen=True, slots=True)
class FixedSpan:
    """One of the spans the first configuration called possibly personal, held fixed so
    every row is scored over the same text. Withheld when any withholding box in that
    configuration overlaps it: a span another row dropped or re-typed is released, which
    is what a reader of the page would see."""

    doc_id: str
    withheld: bool


@dataclass(frozen=True, slots=True)
class AblationRow:
    configuration: Configuration
    fixed: tuple[FixedSpan, ...]
    boxes: int

    @property
    def rate(self) -> Interval:
        return _rate(list(self.fixed), lambda s: s.withheld, seed=20270816)


@dataclass
class ReleaseResult:
    packages: int = 0
    pages: int = 0
    spans: tuple[VisibleSpan, ...] = ()
    excluded: tuple[str, ...] = ()
    institutions: tuple[str, ...] = ()
    ablation: tuple[AblationRow, ...] = ()
    # Of the shipping configuration's detections: PERSON spans the screen dropped for having
    # no name-shaped token, and spans it re-typed as military vocabulary.
    dropped_as_noise: int = 0
    retyped_military: int = 0
    by_rule: dict[str, int] = field(default_factory=dict)
    # A held-out manifest: packages chosen by a rule written before any was scored, and
    # scored once with no change made in response. Changes only what the page says
    # about blindness; the scoring is the same.
    held_out: bool = False
    # The model that decided the residual of the first table, or "" for rules only.
    model_name: str = ""

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
            *(
                [
                    f"**Decided by:** the rules, then {self.model_name} on what they left, "
                    f"through the 04 gateway on placeholders. The ablation table below is "
                    f"rules only.",
                    "",
                ]
                if self.model_name
                else []
            ),
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
            "was a signature block, and the blocks are read back from the text by "
            "`recover_blocks`, which `results/layout.md` checks where the truth is known. "
            "These are OCR text layers of scanned forms and printed email, so much less "
            "comes back than on a clean page. There is also no configured requester on a "
            "downloaded package, so every span that would have been the requester's own "
            "information is something else here. Both effects push the same way.",
        ]
        if self.ablation:
            first = self.ablation[0]
            lines += [
                "",
                "**What each change is worth, over the same spans**",
                "",
                f"Every row is scored over the {len(first.fixed)} spans the first row called "
                f"possibly personal, so the denominators match. A span is withheld when any "
                f"withholding box in that row overlaps it; a span a later row dropped or "
                f"re-typed counts as released, because on the page it is.",
                "",
                "| Configuration | Of those spans, withheld | Withholding boxes over released "
                "text, any type |",
                "|---|---|---:|",
            ]
            lines += [
                f"| {row.configuration.name} | {row.rate} | {row.boxes} |"
                for row in self.ablation
            ]
            shipping = self.ablation[-1]
            lines += [
                "",
                f"The {shipping.rate.point:.1%} here and the "
                f"{self.over_redaction().point:.1%} in the first table measure the same tool "
                f"over different spans. The first table's denominator is what the tool as it "
                f"ships calls possibly personal, {len(self.personal_candidates)} spans; a span "
                f"it re-typed as a rank or a unit, or dropped as noise, has left it. This "
                f"table holds the spans fixed, which is the only way to compare the rows.",
                "",
                f"In the shipping configuration the screen dropped {self.dropped_as_noise} "
                f"person spans with no name-shaped token in them (\"wu\", \"pour lui\") and "
                f"re-typed {self.retyped_military} as ranks, appointments or units (\"LCol\", "
                f"\"KAF\", \"TFK Comd\").",
                "",
                (
                    "**These packages are held out.** They were chosen by a rule written "
                    "before any was downloaded (docs/data.md), from record groups other than "
                    "Defence, and scored once with the code as it stood; nothing was changed "
                    "in response before this table was published. So the rows below the "
                    "first say how far the changes in them carry to records nobody tuned "
                    "them against."
                    if self.held_out
                    else "**The vocabulary was written after reading these packages.** The "
                    "rank list is the Canadian Armed Forces' own and would be the same had "
                    "they never been read; the list of units and headquarters is not, "
                    "because the ones on it are the ones these packages use. So the rows "
                    "below the first are no longer a blind test. `results/releases-heldout.md` "
                    "is, on packages chosen and scored after these changes were made."
                ),
            ]
        if self.by_rule:
            lines += [
                "",
                "**What the shipping configuration decides, by rule**",
                "",
                "| Rule | Spans that could be personal information |",
                "|---|---:|",
            ]
            lines += [f"| `{rule}` | {n} |" for rule, n in self.by_rule.items()]
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


def _blocks(document: Document, recover_layout: bool) -> Document:
    make = recover_blocks if recover_layout else paragraph_blocks
    return document.with_pages([replace(p, blocks=make(p.text)) for p in document])


def _without_vocabulary(detector: SeverDetector) -> SeverDetector:
    """The same detector as it was before the forces' vocabulary: no rank recogniser and
    no screen."""
    return SeverDetector(
        model=detector.model,
        use_presidio=detector.use_presidio,
        require_presidio=detector.require_presidio,
        pattern_recognisers=tuple(r for r in detector.pattern_recognisers if r is not rec.RANK),
        min_score=detector.min_score,
        sweep_names=detector.sweep_names,
        screen_names=False,
    )


_RULES_WITHOUT_RANK = tuple(r for r in rules_mod.DEFAULT_RULES if r is not rules_mod.military_rank)


def _propose(
    data: Loaded,
    detector: Detector,
    configuration: Configuration,
    model: ModelDecider | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[VisibleSpan]:
    taxonomy = default_taxonomy()
    det = detector
    rules = rules_mod.DEFAULT_RULES
    if not configuration.vocabulary:
        if isinstance(detector, SeverDetector):
            det = _without_vocabulary(detector)
        rules = _RULES_WITHOUT_RANK
    spans: list[VisibleSpan] = []
    for release in data.releases:
        # No requester: nobody knows who asked for a package downloaded from an archive.
        # Stated in the table rather than papered over with a guess.
        config = RequestConfig(
            request_id=release.record.file_name,
            # An archives' release, and counted from the year it was retrieved, so the
            # number does not drift as the calendar does.
            archival=configuration.archival
            and release.record.institution.startswith("Library and Archives Canada"),
            as_of_year=int(release.record.retrieved_on[:4])
            if release.record.retrieved_on
            else None,
        )
        document = _blocks(release.document, configuration.recover_layout)
        proposals = DecisionEngine(
            config=config,
            detector=det,
            taxonomy=taxonomy,
            rules=rules,
            model=model,
            model_confidence_threshold=threshold,
        ).propose(document)
        spans.extend(
            VisibleSpan(doc_id=release.record.file_name, proposal=p) for p in proposals
        )
    return spans


def _withheld_over(spans: list[VisibleSpan], fixed: list[VisibleSpan]) -> tuple[FixedSpan, ...]:
    boxes: dict[tuple[str, int], list[Offsets]] = {}
    for s in spans:
        if s.withheld:
            boxes.setdefault((s.doc_id, s.proposal.page), []).append(s.proposal.detection.offsets)
    return tuple(
        FixedSpan(
            doc_id=f.doc_id,
            withheld=any(
                f.proposal.detection.offsets.overlaps(b)
                for b in boxes.get((f.doc_id, f.proposal.page), ())
            ),
        )
        for f in fixed
    )


def run(
    *,
    manifest: Path = DEFAULT_MANIFEST,
    root: Path = DEFAULT_DIR,
    detector: Detector | None = None,
    loaded: Loaded | None = None,
    ablation: bool = True,
    held_out: bool = False,
    model: ModelDecider | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> ReleaseResult:
    """Propose redactions over every visible span, and count the ones that would land.

    With `ablation`, also score the configurations in `CONFIGURATIONS` over the spans the
    first of them called possibly personal, so what the layout recovery and the military
    vocabulary are each worth is a row rather than a claim.
    """
    data = loaded if loaded is not None else load(manifest, root)
    det = detector or SeverDetector()

    shipping = CONFIGURATIONS[-1]
    # The model, when there is one, decides the shipping configuration's residual only. The
    # ablation rows stay rules-only, so they still measure what layout and vocabulary are
    # worth and nothing else.
    spans = _propose(data, det, shipping, model, threshold)

    rows: list[AblationRow] = []
    dropped = 0
    if ablation and data.releases:
        runs = {c: (spans if c == shipping else _propose(data, det, c)) for c in CONFIGURATIONS}
        fixed = [s for s in runs[CONFIGURATIONS[0]] if s.could_be_personal]
        rows = [
            AblationRow(
                configuration=c,
                fixed=_withheld_over(runs[c], fixed),
                boxes=sum(1 for s in runs[c] if s.withheld),
            )
            for c in CONFIGURATIONS
        ]
        dropped = sum(
            1
            for s in runs[CONFIGURATIONS[1]]
            if s.proposal.detection.entity_type is EntityType.PERSON
            and not has_name_shaped_token(s.proposal.detection.text)
        )

    by_rule: dict[str, int] = {}
    for s in spans:
        if s.could_be_personal:
            rule = s.proposal.rule or s.proposal.source.value
            by_rule[rule] = by_rule.get(rule, 0) + 1

    return ReleaseResult(
        packages=len(data.releases),
        pages=data.pages,
        spans=tuple(spans),
        excluded=tuple(data.excluded),
        institutions=tuple(
            sorted({r.record.institution for r in data.releases if r.record.institution})
        ),
        ablation=tuple(rows),
        dropped_as_noise=dropped,
        retyped_military=sum(
            1 for s in spans if s.proposal.detection.recogniser.startswith("military:")
        ),
        by_rule=dict(sorted(by_rule.items(), key=lambda kv: -kv[1])),
        held_out=held_out,
        model_name=str(getattr(model, "model", "")) if model is not None else "",
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


__all__ = [
    "CONFIGURATIONS",
    "RELEASED_BY_DESIGN",
    "AblationRow",
    "Configuration",
    "ReleaseResult",
    "VisibleSpan",
    "run",
    "write",
]
