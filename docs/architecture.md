# Architecture

Four figures: the system as a whole, one span through the decision layer, the reviewer's
workflow and the export it feeds, and how each published number is produced. Each names the
module that implements what it shows; [PLAN.md](../PLAN.md) says why and
[taxonomy.md](taxonomy.md) gives the categories.

## The system

![Documents are ingested with their layout, a detector finds candidate spans, a context record is built for each, deterministic rules decide the clear cases in a fixed order and a model on placeholders decides the rest or escalates; a reviewer approves page by page into an append-only audit log from which the true-redaction export and the schedule are generated, and the evaluation scores every proposal against labels.](architecture/system.svg)

Two kinds of document come in: the 210-page generated corpus whose labels are built in
(`sever.corpus`, six templates and personas) and 82 pages of published federal releases
(`sever.ingest.releases`). Ingestion keeps the layout, headings, letterhead, signature blocks
and email headers, from PDF, scans through OCR, Word and email (`sever.ingest`). The detector
(`sever.detect`) finds candidate spans with Presidio, spaCy and recognisers for the
identifiers a general engine does not know, with coreference. For each span a context record
is built (`sever.context`): the block it sits in, the heading above it, whether a title is
paired with this person anywhere, whether they appear in a public register or on the
letterhead, and whether they match the requester. The decision pipeline (`sever.decide`)
applies the deterministic rules in a fixed order, sends whatever is left to a model through
the portfolio gateway with typed placeholders and never a name, and withholds and escalates
when neither is sure; the taxonomy (`sever.taxonomy`) is eleven codes mapped to the federal
acts and NL's ATIPPA 2015. Proposals go to the reviewer application (`sever.review`), every
action becomes an append-only hash-chained audit row holding a hash of the severed text, and
the export and the schedule are generated from the approved rows. The evaluation
(`sever.eval`) scores every proposal against the labels, runs the baselines on the same pages,
and writes `results/`; the 03 gate decides whether the model layer ships.

## One span through the decision layer

![A candidate span gets a context record, the deterministic rules decide the clear cases in a fixed order, whatever is left goes to a model that sees typed placeholders and never a name, and an answer below the measured confidence threshold is escalated with the model's reasoning; there is no rule that releases a span because nothing matched.](architecture/decision-layer.svg)

A span found by the detector gets its context record: the kind of block, the sentence, the
heading, whether a title is paired with the person, the register, the letterhead,
coreference and the requester. The rules (`sever.decide.rules`) run in an order that is itself
the design: the requester's own information first, then inherently sensitive identifiers,
then non-personal entity types, then capacity, then the public register, then the
twenty-year rule. A clear case becomes a proposal at once. Whatever is left goes to the model
(`sever.decide.model`) through the gateway with the personal data class, seeing typed
placeholders and never a name, which the gateway's own ledger makes checkable rather than
asserted. The model's answer is taken only above a measured confidence threshold
(`results/thresholds.md`); below it the span is escalated with the model's reasoning attached
and withheld meanwhile. Every proposal carries the exemption code it rests on, and there is no
rule that releases a span because nothing matched.

## The reviewer decides

![The reviewer sees one page at a time with every proposed severance highlighted, withholds, releases or escalates each one or severs text the tool missed, and every action is an append-only hash-chained audit row; a page cannot be completed with a span undecided, a record cannot be released with a page incomplete, and the export applies only what the log says.](architecture/review.svg)

`sever review` opens on loopback and fetches nothing from anywhere: one page at a time, the
record rendered as the characters the redaction will be applied to, every proposal
highlighted with its reason in words. The reviewer withholds, releases or escalates each span
(W, R, E), or selects text the tool never proposed and severs it, because a reviewer who can
only answer the tool's list inherits its misses; a button at the foot of the page releases
everything still undecided after asking and naming what the tool would have withheld. Every
action is an append-only hash-chained audit row (`sever.review.audit`) storing a hash of the
severed text rather than the text; a change of mind is a second row. Two rules are enforced
in code: a page cannot be completed while a span on it is undecided, and
`Session.release_gate` raises rather than returning false while a page is incomplete
(`sever.review.session`). `sever export --audit` applies the decisions the reviewer made, not
the tool's proposals (`sever.review.export`), removes the text under every box, generates the
schedule from the approved rows and runs the PDF leak test (`sever.eval.pdf_leak`); without
`--audit` the same PDFs are named `-proposed`, because a document nobody has reviewed is not a
release.

## How the published numbers are produced

![Each number comes from a stated input through the evaluation into a stored result; the baselines run on the same pages, the placeholders ablation and the scanned track are paired, the cost comes from the gateway ledger, and the 03 gate decides whether the model layer ships.](architecture/measurement.svg)

The headline, over-redaction and leak rate with must-keep precision per category, comes from
the proposals against the 210 labelled pages (`sever.eval.confusion`, `results/results.md`).
The four baselines, blunt redact-all-PII, rules-only, sentence-only and model-only, run the
same evaluation on the same pages, which is where the model layer's exchange rate comes from
(`results/detectors.md`). Over-redaction on real records comes from 82 pages of published
federal releases against what was actually released (`sever.eval.coverage`,
`results/releases.md`). The placeholders ablation runs the same spans twice through a local 7B
model, on placeholders and on the raw record (`results/placeholders.md`). The scanned track
runs four degradation profiles through OCR with the character error rate measured
(`results/scanned.md`). Cost per page comes from the gateway ledger (`sever.eval.cost`,
`results/cost.json`). The reviewer study (`sever.review.study`) has one of the three reviewers
it needs and is built rather than a result. The 03 gate compares rules-only with
rules-then-model (`gate/spec.yaml`, `gate/decision.md`). Every table carries 95% intervals.
