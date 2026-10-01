"""What the release gate (project 03) is handed: an eval spec and both sides' outcomes.

The README says this project is measured with the AI Release Gate, and until 2026-10-01
that was true only of the estimator: 03 and 07 wrote the same cluster bootstrap and pinned
that they agree. This module is the rest of it. 03 provides the paired non-inferiority
test, the power screen, Holm's adjustment across suites and a ledger record; this project
provides the graded outcomes, through 03's adapter (`docs/gate-adapter.md` there).

**The item is the document, not the span.** The gate treats every item id as an
independent observation and has no notion of clusters. Spans within a document are not
independent, one persona produces many of them, which is the whole reason every interval
in this repository resamples documents. Feeding the gate span ids would hand it 5,355
"independent" items that are really 210, and its test would be four or five times too
confident. So each outcome is a document-level verdict.

**One suite per category the tool decides, and one for leaks.** Each suite asks one
question of every document that contains the category: did the tool decide every span of
it the right way? `no_leak` is true when no must-redact span in the document was released;
`k1_requester` is true when none of the requester's own information was withheld; and so
on. A document with no span of a category is not an item in that suite. Per-category suites
keep the unit the document, give Holm one test per question, and name the category that
blocks, which is what a reader of a verdict wants to know. The cost of the document as the
unit is that a page with one over-redacted official out of eight counts the same as a page
with eight; the span-level rates in the README carry that detail, and this is the decision
layer on top of them.

**Two categories are not gated, and the reason is measured.** K2 (officials) and K4 (the
long dead) were suites in the first export, and under both configurations exactly one
document in 210, and one in 35, had every such span released. A document verdict that is
false almost everywhere on both sides cannot tell the two apart, and the gate would pass it
as non-inferior while saying nothing. Their span-level over-redaction rates, with
intervals over documents, are in the README; that is where those two are measured.

**The comparison is rules only against rules then the model.** That is the one decision a
public body adopting this would actually make, and the honest limitation in the README is
that the evidence for the model layer is thin. The gate's question is the right shape for
it: is turning the model on non-inferior, category by category, to leaving it off? The
model side is replayed from `results/model-answers.jsonl`, so producing these files costs
nothing.

The decision goes to this project's own ledger:

    uv run gate compare --spec gate/spec.json --baseline gate/rules-only.json \\
        --candidate gate/rules-then-model.json --ledger <this repository>/gate/ledger.jsonl
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

from sever.eval.confusion import Scored, SpanOutcome

#: The non-inferiority margin, in points of documents decided correctly, per suite. The
#: gate's default. A tighter one cannot be decided on 210 documents: near 90 percent, a
#: paired standard error is about two points.
DELTA_POINTS: Final = 3.0

SPEC_NAME: Final = "hundreds-of-pages-redacted"

# Suite key, the spans it is about, and what "right" means for one of them.
Check = tuple[str, Callable[[SpanOutcome], bool], Callable[[SpanOutcome], bool]]

SUITES: Final[tuple[Check, ...]] = (
    ("no_leak", lambda o: o.must_redact, lambda o: not o.is_leak),
    ("k1_requester", lambda o: o.true_code == "K1", lambda o: not o.is_over_redaction),
    ("k3_public", lambda o: o.true_code == "K3", lambda o: not o.is_over_redaction),
    ("k6_not_personal", lambda o: o.true_code == "K6", lambda o: not o.is_over_redaction),
)


def outcomes(scored: Scored) -> dict[str, dict[str, bool]]:
    """Per suite, one verdict per document: every relevant span in it decided right."""
    out: dict[str, dict[str, bool]] = {key: {} for key, _, _ in SUITES}
    for o in scored.outcomes:
        for key, relevant, right in SUITES:
            if relevant(o):
                verdicts = out[key]
                verdicts[o.doc_id] = verdicts.get(o.doc_id, True) and right(o)
    return out


def side(
    label: str,
    scored: Scored,
    *,
    source: Mapping[str, str],
    calls: int = 0,
    cost_usd: float = 0.0,
    uncosted_calls: int = 0,
) -> dict[str, Any]:
    """One side of the comparison, in the shape of the gate's `Side`.

    Nothing here is ungradeable: every document is scored against labels known by
    construction, and an undetected span is a released span, which is graded as such
    rather than left out. Latency is zero because the model side is replayed; the paid run's
    cost is the ledger's, and it is printed on every suite because the gate reads it per
    suite, as 06 does.
    """
    suites = {
        key: {
            "suite": key,
            "outcomes": dict(sorted(verdicts.items())),
            "ungradeable_items": 0,
            "calls": calls,
            "latency_p50_ms": 0.0,
            "cost_usd": round(cost_usd, 6),
            "uncosted_calls": uncosted_calls,
        }
        for key, verdicts in outcomes(scored).items()
    }
    return {"label": label, "source": dict(source), "suites": suites}


def spec(*, delta_points: float = DELTA_POINTS) -> dict[str, Any]:
    """The eval spec, in the gate's `EvalSpec` shape: source kind `outcomes_file`."""
    return {
        "version": 1,
        "name": SPEC_NAME,
        "delta_points": delta_points,
        "alpha": 0.05,
        "resamples": 2000,
        "seed": 0,
        "suites": [
            {"key": key, "source": {"kind": "outcomes_file", "block": key}}
            for key, _, _ in SUITES
        ],
    }
