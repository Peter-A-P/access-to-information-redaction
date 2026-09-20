"""Run every system over the corpus and write the tables the README publishes.

One command produces every number in the README, and the README says so. That is the
portfolio's rule: a stranger clones the repository, runs `sever report`, and gets the same
tables. Hand-editing a results table is how a project stops being evidence.

The systems compared here are the ones PLAN.md section 9 names as the Rule C candidates,
plus the tool itself:

  * **sever**: rules over the full document context, then the model on the residual. With
    the model off (the default, because it spends money) the residual stays escalated,
    which is a real configuration and is labelled as such rather than passed off as the
    finished system.
  * **blunt**: every detected span redacted. Safe, useless, and the thing every off-the-
    shelf PII tool does.
  * **sentence-only**: the same rules with the document context blanked, so a name is
    judged from its sentence alone. This is the ablation that says what the context record
    is worth.

Two numbers deserve a warning label and get one in the output. Leak rate counts a span the
detector never found as a leak, because from the requester's point of view it is in the
released record either way. And over-redaction counts escalations, because an escalated
span is withheld until a human clears it.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from sever.context.requester import RequestConfig
from sever.corpus.generate import Corpus, CorpusItem, build
from sever.corpus.personas import PersonaRole
from sever.decide.pipeline import (
    DEFAULT_THRESHOLD,
    DecisionEngine,
    ModelDecider,
    blunt_baseline,
)
from sever.detect.engine import SeverDetector
from sever.detect.types import Detection, Detector
from sever.eval.confusion import Interval, Scored, score
from sever.eval.pdf_leak import LeakChecker, LeakReport
from sever.ingest.document import Document
from sever.review.export import apply_redactions, render_pdf
from sever.taxonomy.loader import default_taxonomy


@dataclass
class CachingDetector:
    """Detect each document once, however many systems ask.

    The report runs four passes over every page (the tool, the sentence-only ablation, the
    blunt baseline, and the export), and detection is by far the slowest step. Caching by
    document id makes the comparison cheaper without changing a single number: every system
    sees exactly the same detections, which is what a baseline comparison requires anyway.
    """

    inner: Detector
    # A plain attribute rather than a property: the Detector protocol declares `name` as a
    # settable variable, and a read-only property does not satisfy it.
    name: str = ""
    _cache: dict[str, tuple[Detection, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = getattr(self.inner, "name", type(self.inner).__name__)

    def detect(self, document: Document) -> tuple[Detection, ...]:
        hit = self._cache.get(document.doc_id)
        if hit is None:
            hit = tuple(self.inner.detect(document))
            self._cache[document.doc_id] = hit
        return hit


def config_for(item: CorpusItem) -> RequestConfig:
    """The request configuration for a generated document.

    The requester is configuration in the real product too: a public body knows who asked.
    Here it comes from the persona the generator cast as the requester, which is the same
    information a real intake form would carry.
    """
    requester = next(
        (p for p in item.rendered.cast.values() if p.role is PersonaRole.REQUESTER), None
    )
    if requester is None:
        return RequestConfig(request_id=item.doc_id)
    return RequestConfig(
        request_id=item.doc_id,
        requester_name=requester.full_name,
        emails=(requester.personal_email,),
        phones=(requester.personal_phone,),
        identifiers=(requester.mcp, requester.file_number, requester.sin),
        addresses=(requester.home_address,),
        date_of_birth=requester.date_of_birth,
    )


@dataclass(frozen=True, slots=True)
class SystemResult:
    name: str
    note: str
    scored: Scored

    @property
    def leak(self) -> Interval:
        return self.scored.leak_rate()

    @property
    def over(self) -> Interval:
        return self.scored.over_redaction_rate()

    @property
    def escalation(self) -> Interval:
        return self.scored.escalation_rate()


@dataclass
class Report:
    generated_on: dt.date
    corpus: Corpus
    systems: list[SystemResult] = field(default_factory=list)
    leak_report: LeakReport | None = None
    detector_name: str = ""
    # Empty when the model layer was off, which is the default and the CI configuration.
    model_name: str = ""
    model_note: str = ""

    @property
    def primary(self) -> SystemResult:
        return self.systems[0]

    def to_json(self) -> dict[str, object]:
        return {
            "generated_on": self.generated_on.isoformat(),
            "corpus": {
                "documents": len(self.corpus),
                "pages": self.corpus.page_count,
                "seed": self.corpus.seed,
                "labels_by_code": self.corpus.label_counts(),
            },
            "detector": self.detector_name,
            "model": self.model_name or None,
            "model_run": self.model_note or None,
            "systems": [
                {
                    "name": s.name,
                    "note": s.note,
                    **{k: v for k, v in s.scored.summary().items()},
                    "per_code_over_redaction": {
                        c: str(s.scored.over_redaction_rate(c))
                        for c in s.scored.codes_present()
                        if c.startswith("K")
                    },
                    "documents_resampled": len(self.corpus),
                    "per_code_leak": {
                        c: str(s.scored.leak_rate(c))
                        for c in s.scored.codes_present()
                        if c.startswith("R")
                    },
                }
                for s in self.systems
            ],
            "pdf_leak_test": (
                {
                    "boxes_tested": self.leak_report.boxes_tested,
                    "recoverable": self.leak_report.recoverable,
                    "documents": self.leak_report.documents,
                    "ocr_channel_ran": self.leak_report.ocr_ran,
                    "note": self.leak_report.ocr_note,
                }
                if self.leak_report
                else None
            ),
        }


def run(
    *,
    documents: int = 210,
    seed: int = 20270802,
    detector: Detector | None = None,
    corpus: Corpus | None = None,
    with_pdf_leak: bool = True,
    tmp_dir: Path | None = None,
    model: ModelDecider | None = None,
    model_confidence_threshold: float = DEFAULT_THRESHOLD,
) -> Report:
    """Every system over the corpus.

    `model` adds a system rather than replacing one. The rules-only configuration stays in
    the table because it is the row a stranger can reproduce for nothing, and because the
    difference between the two rows is the only honest statement of what the model layer
    buys. The PDF export and the leak test run on the model's proposals when there are
    any, because that is what would actually be released.
    """
    det = CachingDetector(inner=detector or SeverDetector())
    c = corpus or build(documents=documents, seed=seed)
    taxonomy = default_taxonomy()

    ours: dict[str, tuple[object, object]] = {}
    blunt: dict[str, tuple[object, object]] = {}
    sentence: dict[str, tuple[object, object]] = {}
    modelled: dict[str, tuple[object, object]] = {}
    leak = LeakChecker(use_ocr=False) if with_pdf_leak else None

    for item in c:
        doc = item.rendered.document
        labels = item.rendered.labels
        config = config_for(item)

        full = DecisionEngine(config=config, detector=det, taxonomy=taxonomy).propose(doc)
        ours[doc.doc_id] = (full, labels)
        blunt[doc.doc_id] = (blunt_baseline(doc, det, taxonomy), labels)
        sentence[doc.doc_id] = (
            DecisionEngine(
                config=config, detector=det, taxonomy=taxonomy, sentence_only=True
            ).propose(doc),
            labels,
        )
        released = full
        if model is not None:
            released = DecisionEngine(
                config=config,
                detector=det,
                taxonomy=taxonomy,
                model=model,
                model_confidence_threshold=model_confidence_threshold,
            ).propose(doc)
            modelled[doc.doc_id] = (released, labels)

        if leak is not None and tmp_dir is not None:
            src = render_pdf(doc, tmp_dir / f"{doc.doc_id}.pdf")
            out = apply_redactions(
                src, tmp_dir / f"{doc.doc_id}-released.pdf", doc, released
            )
            leak.check(out.path, out.regions, document=doc.doc_id)

    report = Report(
        generated_on=dt.date.today(),
        corpus=c,
        detector_name=getattr(det, "name", type(det).__name__),
        leak_report=leak.report() if leak is not None else None,
        model_name=str(getattr(model, "model", "")) if model is not None else "",
        model_note=_spend_summary(model),
    )
    report.systems = []
    if modelled:
        report.systems.append(
            SystemResult(
                name="sever, rules then the model on the residual",
                note=(
                    "The full configuration. The rules decide what they can; what is left "
                    "goes to the model on typed placeholders through the 04 gateway, and "
                    "an answer below the confidence threshold is escalated rather than "
                    "used."
                ),
                scored=score(modelled, taxonomy=taxonomy),  # type: ignore[arg-type]
            )
        )
    report.systems += [
        SystemResult(
            name="sever, rules only",
            note=(
                "The model layer is off, so the residual the rules could not decide stays "
                "escalated rather than being decided. Escalations withhold, so they are "
                "counted in over-redaction. This row costs nothing to reproduce."
            ),
            scored=score(ours, taxonomy=taxonomy),  # type: ignore[arg-type]
        ),
        SystemResult(
            name="blunt redact-all-PII",
            note="Every detected span redacted. What an off-the-shelf PII tool does.",
            scored=score(blunt, taxonomy=taxonomy),  # type: ignore[arg-type]
        ),
        SystemResult(
            name="sentence-only, no document context",
            note=(
                "The same rules with the context record blanked: no block kind, no "
                "signature-block title, no register, no coreference."
            ),
            scored=score(sentence, taxonomy=taxonomy),  # type: ignore[arg-type]
        ),
    ]
    return report


def _spend_summary(model: ModelDecider | None) -> str:
    """What the run cost, when the implementation keeps track. The protocol does not
    require it, so this asks rather than assumes."""
    if model is None:
        return ""
    summary = getattr(model, "spend_summary", None)
    return str(summary()) if callable(summary) else ""


def _cell(i: Interval) -> str:
    return "n/a" if not i.is_defined else str(i)


def to_markdown(report: Report) -> str:
    """The README's result tables, generated. Never hand-edited."""
    c = report.corpus
    lines: list[str] = []
    lines += [
        f"**Corpus:** {len(c)} synthetic documents, {c.page_count} pages, "
        f"{sum(c.label_counts().values())} labelled spans, seed {c.seed}. "
        f"Labels known by construction. Detector: {report.detector_name}. "
        f"Generated {report.generated_on.isoformat()} by `sever report`.",
        "",
        *(
            [
                f"**Model layer:** {report.model_name}, through the 04 gateway with data "
                f"class `personal`. {report.model_note}.",
                "",
            ]
            if report.model_note
            else []
        ),
        "**Per category, this tool**",
        "",
        "| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |",
        "|---|---:|---|---|---|",
    ]
    primary = report.primary.scored
    for code in primary.codes_present():
        n = len(primary.filtered(code))
        leak = _cell(primary.leak_rate(code)) if code.startswith("R") else "n/a"
        over = _cell(primary.over_redaction_rate(code)) if code.startswith("K") else "n/a"
        lines.append(
            f"| `{code}` | {n} | {leak} | {over} | {_cell(primary.escalation_rate(code))} |"
        )
    lines += [
        "",
        "**Against the baselines**",
        "",
        "| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |",
        "|---|---|---|---|---|",
    ]
    for s in report.systems:
        lines.append(
            f"| {s.name} | {_cell(s.leak)} | {_cell(s.over)} | {_cell(s.escalation)} | "
            f"{_cell(s.scored.detector_recall())} |"
        )
    lines += [
        "",
        "**Where the leaks come from**",
        "",
        "| System | Leaks | The detector never found the span | The decision was wrong |",
        "|---|---:|---:|---:|",
    ]
    for s in report.systems:
        d = s.scored.decomposition()
        lines.append(
            f"| {s.name} | {d['leaks']} | {d['detector_missed']} | {d['decision_wrong']} |"
        )
    if report.leak_report is not None:
        lines += [
            "",
            "**PDF leak test**",
            "",
            "| Redaction boxes applied | Boxes with recoverable text | Channels checked |",
            "|---:|---:|---|",
            f"| {report.leak_report.boxes_tested} | {report.leak_report.recoverable} | "
            f"{'text layer and OCR' if report.leak_report.ocr_ran else 'text layer only'} |",
        ]
        if not report.leak_report.ocr_ran and report.leak_report.ocr_note:
            lines += ["", f"_{report.leak_report.ocr_note}._"]
    lines += [
        "",
        f"Intervals are 95 percent bootstrap percentile intervals resampled over the "
        f"{len(c)} documents,",
        "not over the spans, because spans within a document are not independent: one",
        "persona generates many of them, and resampling spans would report one fact as",
        "many. Project 03 implemented the same estimator independently and the two agree",
        "to within Monte Carlo noise; `tests/test_confusion.py` pins that.",
        "",
    ]
    return "\n".join(lines)


def write(report: Report, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    md = directory / "results.md"
    js = directory / "results.json"
    md.write_text(to_markdown(report), encoding="utf-8")
    js.write_text(json.dumps(report.to_json(), indent=1), encoding="utf-8")
    return md, js


def splice_into_readme(readme: Path, markdown: str) -> bool:
    """Replace the block between the result markers. Returns True if the file changed."""
    start = "<!-- BEGIN RESULTS -->"
    end = "<!-- END RESULTS -->"
    text = readme.read_text(encoding="utf-8")
    if start not in text or end not in text:
        raise ValueError(
            f"{readme} has no result markers. Add {start} and {end} around the tables so "
            f"`sever report` knows where to write, rather than hand-editing them."
        )
    head, _, rest = text.partition(start)
    _, _, tail = rest.partition(end)
    new = f"{head}{start}\n\n{markdown.strip()}\n\n{end}{tail}"
    if new == text:
        return False
    readme.write_text(new, encoding="utf-8")
    return True

