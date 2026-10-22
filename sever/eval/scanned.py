"""The scanned track, measured: character error rate, and what it costs the decisions.

Section 10 asks for a labelled corpus on a native *and* a scanned track, and for the
character error rate on the scanned one. The character error rate is the easy half. The
half that matters is what the errors do to the output, because a redaction tool that reads
a page 99 percent correctly can still release a name: the one percent it got wrong is a
whole surname.

## Four profiles, not one

A single figure would be a number about this corpus. The corpus renders in Courier at 9.5
point, which is close to the easiest input a modern OCR engine can be handed, so `clean` is
a floor and is labelled as one. `scanner` is an office multifunction device on its normal
setting; `photocopy` is a generation or two of loss; `fax` is 100 dpi, where 9.5 point text
stops being recoverable at all. The shape across the four is the finding.

## The ceiling that is not the detector's fault

A value the OCR destroyed cannot be found by any detector, so this track reports
**label survival** beside recall. Without it a reader would see recall fall and conclude
the detector got worse on scans, when in fact the text it was asked to search no longer
contains the name. That is the same error as blaming the decision layer for a mislabelled
span, arriving from a different direction, and it is the third time in this project that a
metric needed a companion to stop it pointing at the wrong component.

## What is not claimed

The pages here are renders of synthetic documents put through a simulated scanner, not
photographs of paper. Real scans bring skew that varies down the page, staples, punch
holes, handwriting in the margin and text that was already a photocopy when it was filed.
This track bounds the effect of character-level OCR error on the decisions. It does not
claim to be a scan of a real record.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from sever.corpus.generate import Corpus, build
from sever.decide.pipeline import DecisionEngine, ModelDecider, default_threshold_for
from sever.detect.engine import SeverDetector
from sever.detect.types import Detector
from sever.eval.confusion import Interval, Scored, score
from sever.eval.layout import flattened
from sever.eval.report import config_for
from sever.ingest.ocr import PROFILES, Degradation, TesseractMissing, available, scan
from sever.taxonomy.loader import default_taxonomy

# The plan's split is roughly 150 native pages to 50 scanned. The scan track is slower than
# everything else in this repository by two orders of magnitude, because every page is
# rasterised and read by a separate process, so it runs over a subset and says so.
DEFAULT_DOCUMENTS = 50


@dataclass(frozen=True, slots=True)
class TrackResult:
    profile: str
    degradation: Degradation
    cer: float
    mean_confidence: float
    labels_total: int
    labels_destroyed: int
    scored: Scored
    # The same read-back with every paragraph BODY, which is how this track was scored
    # until 2026-10-17. None when the run did not score it.
    flat: Scored | None = None
    # With a model: the rules alone on the same read-back, so the table can say what the
    # model adds on a scan. None on a rules-only run, where `scored` is the rules alone.
    rules: Scored | None = None

    @property
    def survival(self) -> float:
        if not self.labels_total:
            return 1.0
        return 1.0 - (self.labels_destroyed / self.labels_total)

    @property
    def leak(self) -> Interval:
        return self.scored.leak_rate()

    @property
    def over(self) -> Interval:
        return self.scored.over_redaction_rate()

    @property
    def recall(self) -> Interval:
        return self.scored.detector_recall()


@dataclass
class ScanTrack:
    documents: int = 0
    pages: int = 0
    native: Scored | None = None
    tracks: list[TrackResult] = field(default_factory=list)
    native_rules: Scored | None = None
    model_name: str | None = None
    threshold: float | None = None

    def to_markdown(self) -> str:
        lines = [
            f"**Corpus:** {self.documents} documents, {self.pages} pages, the same generated "
            f"records as the native track, rendered to PDF and read back with Tesseract.",
            "",
        ]
        if self.model_name is not None:
            lines += [
                f"**Decided by:** the rules, then {self.model_name} on what they left at a "
                f"confidence threshold of {self.threshold:.2f}, through the 04 gateway on "
                f"placeholders: the tool as it ships. The rules alone on the same read-back "
                f"are in the second table.",
                "",
            ]
        lines += [
            "| Input | Character error rate | Mean OCR confidence | Labels that survived | "
            "Detector recall | Leak rate | Over-redaction |",
            "|---|---:|---:|---:|---|---|---|",
        ]
        if self.native is not None:
            lines.append(
                f"| native (no OCR) | 0.0% | n/a | 100.0% | "
                f"{self.native.detector_recall()} | {self.native.leak_rate()} | "
                f"{self.native.over_redaction_rate()} |"
            )
        for t in self.tracks:
            lines.append(
                f"| {t.profile} | {t.cer:.1%} | {t.mean_confidence:.1%} | {t.survival:.1%} | "
                f"{t.recall} | {t.leak} | {t.over} |"
            )
        if self.model_name is not None and all(t.rules is not None for t in self.tracks):
            lines += [
                "",
                "**The rules alone, on the same read-back**",
                "",
                "| Input | Leak rate, rules alone | Over-redaction, rules alone |",
                "|---|---|---|",
            ]
            if self.native_rules is not None:
                lines.append(
                    f"| native (no OCR) | {self.native_rules.leak_rate()} | "
                    f"{self.native_rules.over_redaction_rate()} |"
                )
            for t in self.tracks:
                assert t.rules is not None
                lines.append(
                    f"| {t.profile} | {t.rules.leak_rate()} | {t.rules.over_redaction_rate()} |"
                )
        if any(t.flat is not None for t in self.tracks):
            lines += [
                "",
                "**What reading the layout back is worth on a scan**",
                "",
                "The same read-back scored twice: with every paragraph BODY, which is how "
                "this track was scored until 2026-10-17, and with the blocks read back from "
                "the OCR text by `recover_blocks`. The text is identical, so the difference "
                "is the blocks. "
                + ("Both columns are the rules alone, as they were when this was measured."
                   if self.model_name is not None else ""),
                "",
                "| Input | Leak, paragraphs only | Leak, layout recovered | "
                "Over-redaction, paragraphs only | Over-redaction, layout recovered |",
                "|---|---|---|---|---|",
            ]
            for t in self.tracks:
                if t.flat is None:
                    continue
                recovered = t.rules or t.scored
                lines.append(
                    f"| {t.profile} | {t.flat.leak_rate()} | {recovered.leak_rate()} | "
                    f"{t.flat.over_redaction_rate()} | {recovered.over_redaction_rate()} |"
                )
        lines += [
            "",
            "**What each profile is**",
            "",
            "| Profile | Applied to the render |",
            "|---|---|",
        ]
        for t in self.tracks:
            lines.append(f"| {t.profile} | {t.degradation.describe()} |")
        if any(t.profile == "fax" for t in self.tracks):
            lines += [
                "",
                "The `fax` row is 100 dpi, at which 9.5 point text stops being recoverable "
                "at all. It is kept because knowing where the floor falls out is worth more "
                "than a table of rows that all work.",
            ]
        lines += [
            "",
            "**What a scan cost was the layout, and the layout reads back from the text.** "
            "Read as paragraphs, a near-perfect scan cost about a fifth of a point of recall "
            "and some eighteen points of over-redaction: the characters were almost all there "
            "and the structure was not, so nothing was role-bearing, the rules lost the "
            "signature block and the letterhead, and a person they could not place was "
            "escalated and withheld. With the blocks read back from the OCR text by "
            "`recover_blocks`, the three working profiles are within three points of the native"
            " row, and the leak rate does not move. The structure was in the text all along, "
            "in the line breaks and in the words a signature block and an email header are "
            "made of. That is on the six templates the recovery was written against, so it is"
            " the most it can do; `results/releases.md` is a layout it was not written "
            "against, and recovers much less there.",
            "",
            "That is worth stating plainly because the obvious worry about OCR is the "
            "opposite one. The fear is that a misread name gets released. On these numbers "
            "that barely happens until the page falls apart entirely; what happened first, "
            "before the layout was read back, was that the requester got a blacker page.",
            "",
            "**Labels that survived** is the share of labelled values still present in the "
            "OCR output at all. A value the scan destroyed cannot be found by any detector, "
            "so it caps recall for reasons that have nothing to do with detection. Reading "
            "the recall column without this one would blame the detector for text that is "
            "no longer on the page.",
            "",
            "It also moves the denominators, which is what makes the worst row readable. "
            "A label none of whose characters survived is not in the leak pool either: "
            "there is nothing on the page to release. So the `fax` row's leak rate is over "
            "the labels that were still there to leak, which is why its n is smaller than "
            "the rows above it. Reading it as though it were measured on the same "
            "denominator as the rows above would overstate it; reading it as a page "
            "that has been destroyed rather than redacted is closer.",
            "",
            "The corpus renders in Courier at 9.5 point: monospaced, high contrast, one "
            "generation from the original. That is close to the easiest input an OCR engine "
            "can be given, so a row without degradation is a floor rather than a typical "
            "case, and it is not zero even so.",
            "",
            "These are renders of synthetic records put through a simulated scanner, not "
            "photographs of paper. Real scans bring skew that varies down the page, staples, "
            "punch holes, marginalia and documents that were already photocopies when they "
            "were filed. This track bounds what character-level OCR error does to the "
            "decisions; it is not a claim about scanning a real record.",
        ]
        return "\n".join(lines)


def run(
    *,
    documents: int = DEFAULT_DOCUMENTS,
    seed: int = 20270802,
    profiles: tuple[str, ...] = tuple(PROFILES),
    detector: Detector | None = None,
    corpus: Corpus | None = None,
    work_dir: Path | None = None,
    model: ModelDecider | None = None,
) -> ScanTrack:
    """Score the same documents native and scanned, at each degradation profile.

    With `model`, the main table is the tool as it ships, the rules then the model, and the
    rules alone are scored on the same OCR output beside it; the paragraphs-only arm stays
    the rules alone, the comparison it was written for. The OCR runs once per page either
    way."""
    if not available():
        raise TesseractMissing(
            "the scan track needs Tesseract, which is a system binary and not a Python "
            "package. Install it and put it on PATH, or point SEVER_TESSERACT at it."
        )
    det = detector or SeverDetector()
    c = corpus or build(documents=documents, seed=seed)
    taxonomy = default_taxonomy()

    native: dict[str, tuple[object, object]] = {}
    native_rules: dict[str, tuple[object, object]] = {}
    rule_pools: dict[str, dict[str, tuple[object, object]]] = {p: {} for p in profiles}

    def engine(config: object, *, with_model: bool) -> DecisionEngine:
        return DecisionEngine(
            config=config,  # type: ignore[arg-type]
            detector=det,
            taxonomy=taxonomy,
            model=model if with_model else None,
        )
    pools: dict[str, dict[str, tuple[object, object]]] = {p: {} for p in profiles}
    flat_pools: dict[str, dict[str, tuple[object, object]]] = {p: {} for p in profiles}
    destroyed: dict[str, int] = dict.fromkeys(profiles, 0)
    total_labels = 0
    cer_weighted: dict[str, float] = dict.fromkeys(profiles, 0.0)
    conf_weighted: dict[str, float] = dict.fromkeys(profiles, 0.0)
    characters = 0

    with tempfile.TemporaryDirectory() as tmp:
        root = work_dir or Path(tmp)
        root.mkdir(parents=True, exist_ok=True)
        for item in c:
            doc = item.rendered.document
            labels = item.rendered.labels
            config = config_for(item)
            native[doc.doc_id] = (engine(config, with_model=True).propose(doc), labels)
            if model is not None:
                native_rules[doc.doc_id] = (engine(config, with_model=False).propose(doc), labels)
            total_labels += len(labels.spans)
            page_characters = sum(len(p.text) for p in doc)
            characters += page_characters
            for name in profiles:
                scanned = scan(doc, labels, root / f"{doc.doc_id}-{name}.pdf", how=PROFILES[name])
                # A scanned document has no reliable structure, so the detector runs over
                # it fresh rather than reusing the native detections: reusing them would be
                # the whole measurement, answered in advance.
                pools[name][doc.doc_id] = (
                    engine(config, with_model=True).propose(scanned.document),
                    scanned.labels,
                )
                if model is not None:
                    rule_pools[name][doc.doc_id] = (
                        engine(config, with_model=False).propose(scanned.document),
                        scanned.labels,
                    )
                flat_pools[name][doc.doc_id] = (
                    engine(config, with_model=False).propose(flattened(scanned.document)),
                    scanned.labels,
                )
                destroyed[name] += scanned.destroyed
                cer_weighted[name] += scanned.cer * page_characters
                conf_weighted[name] += (
                    sum(p.confidence for p in scanned.pages) / len(scanned.pages)
                ) * page_characters

    return ScanTrack(
        documents=len(c),
        pages=c.page_count,
        native=score(native, taxonomy=taxonomy),  # type: ignore[arg-type]
        native_rules=(
            score(native_rules, taxonomy=taxonomy)  # type: ignore[arg-type]
            if model is not None
            else None
        ),
        model_name=getattr(model, "model", None) if model is not None else None,
        threshold=default_threshold_for(model) if model is not None else None,
        tracks=[
            TrackResult(
                profile=name,
                degradation=PROFILES[name],
                cer=cer_weighted[name] / characters if characters else 0.0,
                mean_confidence=conf_weighted[name] / characters if characters else 0.0,
                labels_total=total_labels,
                labels_destroyed=destroyed[name],
                scored=score(pools[name], taxonomy=taxonomy),  # type: ignore[arg-type]
                flat=score(flat_pools[name], taxonomy=taxonomy),  # type: ignore[arg-type]
                rules=(
                    score(rule_pools[name], taxonomy=taxonomy)  # type: ignore[arg-type]
                    if model is not None
                    else None
                ),
            )
            for name in profiles
        ],
    )


def write(track: ScanTrack, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!-- Generated by `sever eval-scanned`. Do not hand-edit. -->\n\n"
        "# The scanned track: what OCR costs the decisions\n\n" + track.to_markdown() + "\n",
        encoding="utf-8",
    )
    return path
