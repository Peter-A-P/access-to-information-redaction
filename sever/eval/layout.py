"""What the layout is worth, and how much of it can be read back from text alone.

The scanned track said the expensive part of a scan is not the characters: a near-perfect
read-back cost a fifth of a point of recall and twenty points of over-redaction, because
every block came back as BODY. `sever.ingest.layout` reads the structure back from the
text. This module measures it without OCR in the way, on all 210 records:

  * **native**: the blocks the renderer emitted, which are the truth.
  * **flattened**: the same text cut into paragraphs, every one BODY. This is what the
    scanned track and the real-record track had until 2026-10-17.
  * **recovered**: the same text with its blocks read back by `recover_blocks`.

The text is identical in all three, so any difference is the blocks and nothing else.
Then, per labelled span, whether the block it was read into is the kind the renderer put
it in. That second table is the one that says whether the recovery is right rather than
merely useful: a recovery that put every name in a signature block would score well on
over-redaction and badly here.

## What this does not show

The recovery was written by someone who had read the six templates, and it is scored on
those six templates. A rule like "a name on its own line with a title under it is a
signature" is general, but it was checked against these layouts and no others, so the
recovered row is an upper bound on what it does for a record it has never seen. The
real-record track is where an unseen layout is measured, with the caveat it carries.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from sever.corpus.generate import Corpus, build
from sever.decide.pipeline import DecisionEngine
from sever.detect.engine import SeverDetector
from sever.detect.types import Detector
from sever.eval.confusion import Scored, score
from sever.eval.report import config_for
from sever.ingest.document import BlockKind, Document
from sever.ingest.layout import recover_blocks
from sever.ingest.ocr import paragraph_blocks
from sever.taxonomy.loader import Decision, default_taxonomy

VARIANTS = ("native", "flattened", "recovered")


def flattened(document: Document) -> Document:
    return document.with_pages(
        [replace(p, blocks=paragraph_blocks(p.text)) for p in document]
    )


def recovered(document: Document) -> Document:
    return document.with_pages([replace(p, blocks=recover_blocks(p.text)) for p in document])


@dataclass
class LayoutResult:
    documents: int = 0
    pages: int = 0
    scored: dict[str, Scored] = field(default_factory=dict)
    # Per native block kind: labelled spans in it, and how many the recovery put in a
    # block of the same kind.
    agreement: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Labelled spans the recovery put in a role-bearing block that the renderer did not:
    # the direction that can release a name.
    promoted: int = 0
    # Of those, the ones that had to be withheld. A promoted span that must be released
    # anyway costs nothing; one that must be withheld is how a leak would start.
    promoted_must_redact: int = 0
    promoted_by: dict[str, int] = field(default_factory=dict)
    labels: int = 0

    def to_markdown(self) -> str:
        lines = [
            f"**Corpus:** {self.documents} synthetic documents, {self.pages} pages, the same "
            f"records as the headline tables. Rules only, no model. Track: native text, so "
            f"no character is misread and the only difference between rows is the blocks.",
            "",
            "| Blocks | Leak rate | Over-redaction | Escalation rate |",
            "|---|---|---|---|",
        ]
        names = {
            "native": "native, as rendered (the truth)",
            "flattened": "flattened, every paragraph BODY (scans and releases until 2026-10-17)",
            "recovered": "recovered from the text by `recover_blocks`",
        }
        for v in VARIANTS:
            s = self.scored[v]
            lines.append(
                f"| {names[v]} | {s.leak_rate()} | {s.over_redaction_rate()} | "
                f"{s.escalation_rate()} |"
            )
        lines += [
            "",
            "**Is each labelled span read into the right kind of block?**",
            "",
            "| Native block | Labelled spans | Recovered as the same kind |",
            "|---|---:|---:|",
        ]
        for kind, (n, same) in sorted(self.agreement.items(), key=lambda kv: -kv[1][0]):
            share = f"{same / n:.1%}" if n else "n/a"
            lines.append(f"| {kind} | {n} | {same} ({share}) |")
        lines += [
            "",
            f"**Promoted into a role-bearing block the renderer did not put it in:** "
            f"{self.promoted} of {self.labels} labelled spans, of which "
            f"{self.promoted_must_redact} had to be withheld. That is the direction that "
            f"can release a name as an official's, so it is counted on its own"
            + (
                " ("
                + "; ".join(f"{k}: {n}" for k, n in sorted(self.promoted_by.items()))
                + ")."
                if self.promoted_by
                else "."
            ),
            "",
            "The `address` row is expected to miss: an inside address and a paragraph are "
            "the same thing to the rules, so the recovery does not try to tell them apart "
            "and reads an address as BODY.",
            "",
            "The recovery was written against these six templates and is scored on them, so "
            "the recovered row is an upper bound for a layout it has not seen. "
            "`results/releases.md` is the unseen-layout check.",
        ]
        return "\n".join(lines)


def run(
    *,
    documents: int = 210,
    seed: int = 20270802,
    detector: Detector | None = None,
    corpus: Corpus | None = None,
) -> LayoutResult:
    det = detector or SeverDetector(require_presidio=True)
    c = corpus or build(documents=documents, seed=seed)
    taxonomy = default_taxonomy()
    pools: dict[str, dict[str, tuple[object, object]]] = {v: {} for v in VARIANTS}
    result = LayoutResult(documents=len(c), pages=c.page_count)
    for item in c:
        native = item.rendered.document
        labels = item.rendered.labels
        config = config_for(item)
        variants = {"native": native, "flattened": flattened(native), "recovered": recovered(native)}
        for name, doc in variants.items():
            engine = DecisionEngine(config=config, detector=det, taxonomy=taxonomy)
            pools[name][doc.doc_id] = (engine.propose(doc), labels)
        back = variants["recovered"]
        for span in labels.spans:
            truth = native.page(span.page).block_at(span.offsets)
            got = back.page(span.page).block_at(span.offsets)
            true_kind = truth.kind if truth else BlockKind.UNKNOWN
            got_kind = got.kind if got else BlockKind.UNKNOWN
            n, same = result.agreement.get(true_kind.value, (0, 0))
            result.agreement[true_kind.value] = (n + 1, same + (got_kind is true_kind))
            result.labels += 1
            if got_kind.is_role_bearing and not true_kind.is_role_bearing:
                result.promoted += 1
                move = f"{true_kind.value} read as {got_kind.value}"
                result.promoted_by[move] = result.promoted_by.get(move, 0) + 1
                if taxonomy[span.code].decision is Decision.REDACT:
                    result.promoted_must_redact += 1
    result.scored = {
        v: score(pools[v], taxonomy=taxonomy)  # type: ignore[arg-type]
        for v in VARIANTS
    }
    return result


def write(result: LayoutResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!-- Generated by `sever eval-layout`. Do not hand-edit. -->\n\n"
        "# Reading the layout back from text\n\n" + result.to_markdown() + "\n",
        encoding="utf-8",
    )
    return path


__all__ = ["LayoutResult", "flattened", "recovered", "run", "write"]
