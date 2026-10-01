"""The export applies what the reviewer decided, not what the tool proposed.

Before this test existed, `sever export --audit` checked that a person had completed every
page and then redacted the tool's proposals regardless of what that person had said. A
proposal the reviewer rejected was still severed, and a name the reviewer selected and
severed because the tool had missed it went out in clear. Both are tested here against the
PDF itself, because the PDF is what the requester receives.
"""

from __future__ import annotations

from pathlib import Path

from sever.corpus.generate import build
from sever.decide.pipeline import DecisionEngine, Source
from sever.detect.engine import SeverDetector
from sever.eval.report import config_for
from sever.review.audit import Action, AuditLog
from sever.review.decisions import as_released, final_spans
from sever.review.export import apply_redactions, build_schedule, extract_text, render_pdf
from sever.taxonomy.loader import default_taxonomy

REQUEST = "A-EXPORT"


def test_a_rejected_proposal_stays_and_a_reviewer_severance_goes(tmp_path: Path) -> None:
    taxonomy = default_taxonomy()
    item = next(iter(build(documents=6)))
    doc = item.rendered.document
    proposals = tuple(DecisionEngine(config=config_for(item), detector=SeverDetector()).propose(doc))
    page = doc.page(1)
    rejected = next(p for p in proposals if p.withholds and len(p.detection.text) > 4)
    # A word nobody proposed, standing in for a name the detector missed.
    covered = {i for p in proposals for i in range(p.detection.offsets.start, p.detection.offsets.end)}
    start = next(
        i
        for i in range(len(page.text) - 8)
        if page.text[i : i + 8].isalpha() and not covered & set(range(i - 1, i + 9))
    )
    added = page.text[start : start + 8]

    with AuditLog(tmp_path / "audit.duckdb") as log:
        o = rejected.detection.offsets
        log.append(request_id=REQUEST, doc_id=doc.doc_id, page=1, action=Action.REJECT,
                   span_start=o.start, span_end=o.end, proposed_code=rejected.code)
        log.append(request_id=REQUEST, doc_id=doc.doc_id, page=1, action=Action.ADD,
                   span_start=start, span_end=start + 8, final_code="R1")
        rows = log.rows(request_id=REQUEST)

    applied = as_released(
        final_spans(rows, proposals, doc_id=doc.doc_id, taxonomy=taxonomy),
        proposals,
        doc,
        taxonomy=taxonomy,
    )
    assert rejected.key not in {p.key for p in applied}
    assert any(p.source is Source.REVIEWER for p in applied)

    source = render_pdf(doc, tmp_path / "source.pdf")
    result = apply_redactions(source, tmp_path / "released.pdf", doc, applied)
    released = extract_text(result.path)
    assert added not in released
    assert rejected.detection.text in released

    schedule = build_schedule(doc.doc_id, doc, applied)
    assert any("Severed by the reviewer" in row[4] for row in schedule.rows)
