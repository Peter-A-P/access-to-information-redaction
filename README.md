# Access-to-Information Redaction

An access-to-information request means staff reading hundreds of pages and deciding, line
by line, which personal information must be withheld and which must be released. Blunt
PII tools redact all of it and are useless, so it is done by hand. This tool proposes every
redaction with a reason tied to a category of the legislation, lets a reviewer approve or
reject page by page with a full audit log, and publishes how often it redacts what must go
and how often it keeps what must stay. Days of reading become hours of review.

**The tool proposes; a person decides.** There is no path from a proposal to a released
document without a reviewer action on every page.

## Result

Measured on a 210-page synthetic corpus whose labels are known by construction. Every
number below is produced by `sever report` and spliced in by it; none is typed by hand.

<!-- BEGIN RESULTS -->

**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Generated 2026-09-19 by `sever report`.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 9.1% (7.8% to 10.4%), n=980 | 9.1% (7.8% to 10.4%), n=980 |
| `K2` | 2345 | n/a | 36.6% (34.7% to 38.5%), n=2345 | 36.6% (34.7% to 38.5%), n=2345 |
| `K3` | 280 | n/a | 12.1% (8.2% to 16.4%), n=280 | 12.1% (8.2% to 16.4%), n=280 |
| `K4` | 70 | n/a | 40.0% (32.9% to 45.7%), n=70 | 40.0% (32.9% to 45.7%), n=70 |
| `K6` | 280 | n/a | 25.0% (21.3% to 28.6%), n=280 | 25.0% (21.3% to 28.6%), n=280 |
| `R1` | 1400 | 14.6% (12.3% to 16.8%), n=1400 | n/a | 80.4% (78.0% to 82.9%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules over the full document context | 14.6% (12.3% to 16.8%), n=1400 | 27.3% (26.2% to 28.4%), n=3955 | 41.2% (40.1% to 42.2%), n=5355 | 91.7% (90.9% to 92.5%), n=5355 |
| blunt redact-all-PII | 8.1% (6.6% to 9.6%), n=1400 | 91.6% (90.7% to 92.5%), n=3955 | 0.0% (0.0% to 0.0%), n=5355 | 91.7% (90.9% to 92.5%), n=5355 |
| sentence-only, no document context | 14.5% (12.2% to 16.7%), n=1400 | 50.9% (49.0% to 52.9%), n=3955 | 58.7% (57.2% to 60.2%), n=5355 | 91.7% (90.9% to 92.5%), n=5355 |

**Where the leaks come from**

| System | Leaks | The detector never found the span | The decision was wrong |
|---|---:|---:|---:|
| sever, rules over the full document context | 205 | 113 | 92 |
| blunt redact-all-PII | 113 | 113 | 0 |
| sentence-only, no document context | 203 | 113 | 90 |

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2588 | 0 | text layer only |

_OCR channel disabled for this run._

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.

<!-- END RESULTS -->

**The number that matters is the second column.** Any tool can get the leak rate down by
redacting everything, and the blunt baseline in the table does exactly that: it withholds
91.6 percent of the information that must be released. A record that comes back with the
signing officer's name, the minister on the letterhead, the department and the requester's
own address blacked out has been answered in form and refused in substance. That column is
what nobody publishes.

## The honest limitation

**This tool currently leaks more than the blunt baseline it replaces, and the model layer
that is meant to close the gap has not been run.**

The rules decide the clear cases and escalate the rest, and an escalated span is withheld,
so nothing is released on a guess. But 92 spans that must be withheld are released by a
wrong decision rather than by a detector miss, and the decision layer that is designed to
catch them (a frontier model, on placeholders, through the gateway) is built and tested but
switched off, because turning it on spends money and no spend cap has been set for this
project yet. What is published here is the rules-only configuration, labelled as such.

**There is no reviewer app yet.** The audit log, the true-redaction export and the
generated schedule are built and tested; the page-by-page web interface that a reviewer
would actually drive is not, and neither is the reviewer time study that would support any
claim about hours saved. The "days of reading become hours of review" line at the top is
the goal of the project, not a measured result.

Three more limitations, none of them small:

- **The corpus is synthetic.** Labels are exact because roles were assigned before the
  documents were written, which is the only affordable way to get 5,355 labelled spans. It
  also means the documents are template-shaped. The real-record test that would check this
  (published federal releases, where everything visible was judged releasable by a human)
  is designed and not built.
- **36.6 percent over-redaction on officials acting in an official capacity** is the
  weakest number in the table and it is mostly escalation, not error: names the rules could
  not pair with a title anywhere in the record.
- **18 of 33 statutory provisions are verified** against the consolidated texts. The rest
  are marked unverified with the reason, in the YAML and on the generated page. Nothing
  defaults to verified.

## What this does not do

- It does not decide non-personal exemptions (advice, legal privilege, law enforcement,
  third-party business). It flags candidates for the reviewer with the provision and makes
  no proposal.
- It does not release anything. Every page needs a reviewer's explicit action.
- It is not legal advice. The taxonomy maps categories to provisions of two acts and is
  configurable; a public body applies its own interpretation.
- It does not read handwriting. Scanned typed documents only, and that track is not built.

[`docs/escalation.md`](docs/escalation.md) is the full list of where the tool declines to
decide, and why.

## How it works

Documents are ingested with layout: headings, letterhead, signature blocks, email headers.
A detector finds candidate spans (Presidio and spaCy, plus recognisers for the identifiers
a general PII engine does not know: medical care plan numbers, departmental file numbers,
employee numbers).

For each span a **context record** is built: which kind of block it sits in, the sentence,
the heading above it, whether a title is paired with this person anywhere in the document,
whether they appear in a public register or on the letterhead, which other mentions in the
record are the same person, and whether they match the configured requester. That record is
the whole argument of the project, and the sentence-only row in the results table is what
it is worth: judging a name from its sentence alone nearly doubles over-redaction, from
27.3 percent to 50.9 percent, because a person's capacity is almost never in the sentence
that names them. It is three inches lower, in the signature block.

**Deterministic rules** decide the clear cases in a fixed order that is itself the design:
the requester's own information first, then inherently sensitive identifiers (a director's
health number is not about being a director), then non-personal entity types, then
capacity, then the public register, then the twenty-year rule. Whatever is left goes to a
**model** through the portfolio's Compliant AI Gateway with the personal data class,
seeing typed placeholders and never a name. When neither is
sure, the proposal is to withhold and escalate. There is no rule that releases a span
because nothing matched.

Every reviewer action is an append-only audit row, hash-chained so a rewritten row is
detectable, and the row stores a hash of the severed text rather than the text, so the log
of what was withheld does not itself contain the personal information. The export removes
the text under every box, and the schedule the requester receives is generated from the
approved rows rather than written by hand.

## Redaction is destructive here

A black rectangle drawn over selectable text is the most common real-world redaction
failure and it has put real names into the public domain. This project refuses to ship it.
Exports use PyMuPDF redaction annotations, which delete the glyphs, and the leak test
extracts the text clipped to **each applied rectangle** and asserts it is empty.

Asking instead whether the redacted string appears anywhere in the output is the wrong
test, and the first version of the checker asked it: it reported ten leaks that were the
word "Minister" appearing, correctly, in an unredacted heading. The test also builds a
deliberately broken export, a box drawn over live text, and asserts that the checker catches
it. A leak test that has never caught a leak is not evidence of anything.

## Try it

```bash
uv venv && uv pip install -e ".[detect]" --group dev
python -m spacy download en_core_web_sm

sever taxonomy check                  # the codes, and how many provisions are verified
sever corpus build --documents 210    # the labelled corpus, from a seed, offline and free
sever propose --documents 3           # proposals with the reason for each one
sever export --documents 3            # truly redacted PDFs, schedules, and the leak test
sever report --readme README.md       # every number above
```

`sever report` is the one command behind every published figure. It takes about ninety
seconds and spends nothing: the model layer is off by default, because a corpus run is
thousands of calls and the safe default is the one that cannot spend money by accident.

## Repository

| Path | What is in it |
|---|---|
| `sever/taxonomy/` | The codes and their provisions, in YAML. `docs/taxonomy.md` is generated from it |
| `sever/corpus/` | Personas with roles assigned first, six document templates, the renderer that emits labels with the text |
| `sever/detect/` | Presidio plus the access-to-information recognisers, and within-document coreference |
| `sever/context/` | Signature blocks, letterheads, public registers, requester matching, the context record |
| `sever/decide/` | The rules in precedence order, the placeholder policy, the model layer |
| `sever/review/` | True-redaction export, the generated schedule, the append-only audit log |
| `sever/eval/` | Confusion matrices with bootstrap intervals, the baselines, the PDF leak test |

Docs: [taxonomy](docs/taxonomy.md) (generated) · [escalation](docs/escalation.md) ·
[data](docs/data.md) · [what did not work](docs/rejected.md) · [plan](PLAN.md)

## Engineering

Python 3.13, typed throughout, `ruff` and `mypy --strict` clean. The tests that matter are
the ones that can fail meaningfully:

- no redaction box in any export has recoverable text, and the checker is proved against a
  deliberately broken one;
- no span belonging to the requester is ever proposed as third-party information, checked
  across the whole corpus rather than on one example, with a ceiling on how often it may
  escalate instead;
- no raw entity leaves the boundary, checked against the personas rather than against the
  detector's own output, because a name the detector missed is exactly the one that would
  slip through;
- the audit log has no method that can change a row, and a hand-edited row breaks the hash
  chain;
- the taxonomy refuses a provision that is neither verified nor explicitly marked
  unverified with a reason;
- the rule fixtures include the traps: an official named as a complainant, a requester
  mentioned as a witness, an official's health number, a death inside twenty years.

That third test is the one that earned its keep. It found 74 real values leaving the
boundary, from three separate causes, none of which was visible any other way.
[`docs/rejected.md`](docs/rejected.md) has the account.

## What is built, and what is not

| Built and measured | Built, not yet run | Not built |
|---|---|---|
| Taxonomy, two jurisdictions, generated docs | The model layer, through the gateway on placeholders | Reviewer web app |
| 210-page labelled corpus, labels by construction | | Reviewer time study |
| Detection, context record, rules, escalation | | Scanned track and OCR error rate |
| Blunt and sentence-only baselines, with intervals | | Published-federal-releases track |
| True-redaction export, schedule, PDF leak test | | Model-only and rules-only baselines |
| Append-only hash-chained audit log | | Cost per page, hosted demo |

## Part of a portfolio

One of fifteen projects. It is built on the Compliant AI Gateway and measured with the AI
Release Gate. It is the clearest demonstration of what the gateway is for: a
frontier model used on access-to-information records without personal data leaving the
boundary, measured.

## How this was built

Design, methodology, evaluation choices and judgement are Peter Parker's, including eight
years inside a public body that answers access-to-information requests. AI coding
assistants (Claude Code) were used for implementation and drafting, the way a senior
engineer uses them in 2026. Every number in the results tables is reproducible from this
repository with one command, and that reproducibility is the evidence that matters.
