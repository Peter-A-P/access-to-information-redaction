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

**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Generated 2026-09-20 by `sever report`.

**Model layer:** anthropic/claude-haiku-4-5-20251001, through the 04 gateway with data class `personal`. 2550 answers replayed from the cache, nothing spent.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 6.3% (5.2% to 7.5%), n=980 | 4.7% (3.5% to 6.0%), n=980 |
| `K2` | 2345 | n/a | 33.3% (31.3% to 35.4%), n=2345 | 23.8% (21.8% to 25.9%), n=2345 |
| `K3` | 280 | n/a | 7.1% (4.3% to 10.4%), n=280 | 7.1% (4.3% to 10.4%), n=280 |
| `K4` | 70 | n/a | 48.6% (45.7% to 50.0%), n=70 | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 0.0%), n=280 | 0.0% (0.0% to 0.0%), n=280 |
| `R1` | 1400 | 7.9% (6.3% to 9.5%), n=1400 | n/a | 56.1% (53.3% to 59.1%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 7.9% (6.3% to 9.5%), n=1400 | 22.7% (21.4% to 24.0%), n=3955 | 26.9% (25.7% to 28.3%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |
| sever, rules only | 5.4% (3.9% to 7.0%), n=1400 | 29.7% (28.5% to 30.8%), n=3955 | 45.4% (44.3% to 46.3%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |
| blunt redact-all-PII | 1.8% (1.1% to 2.5%), n=1400 | 97.2% (96.5% to 97.9%), n=3955 | 0.0% (0.0% to 0.0%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |
| sentence-only, no document context | 5.4% (3.9% to 7.0%), n=1400 | 56.4% (54.4% to 58.3%), n=3955 | 65.1% (63.6% to 66.5%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |

**Where the leaks come from**

| System | Leaks | The detector never found the span | The decision was wrong |
|---|---:|---:|---:|
| sever, rules then the model on the residual | 110 | 25 | 85 |
| sever, rules only | 75 | 25 | 50 |
| blunt redact-all-PII | 25 | 25 | 0 |
| sentence-only, no document context | 75 | 25 | 50 |

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2224 | 0 | text layer only |

_OCR channel disabled for this run._

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.

<!-- END RESULTS -->

**The number that matters is the second column.** Any tool can get the leak rate down by
redacting everything, and the blunt baseline in the table does exactly that: it withholds
97.2 percent of the information that must be released. A record that comes back with the
signing officer's name, the minister on the letterhead, the department and the requester's
own address blacked out has been answered in form and refused in substance. That column is
what nobody publishes.

## The honest limitation

**The model layer buys usefulness with leaks, and this is what the exchange rate is.**

With the rules alone the tool leaks 5.4 percent and withholds 29.7 percent of what must be
released. With the model deciding what the rules could not, at the confidence threshold
measured in [`results/thresholds.md`](results/thresholds.md), it leaks 7.9 percent and
withholds 22.7 percent. In counts, over 5,355 labelled spans: turning the model on
correctly releases **277 spans the rules had withheld** and wrongly releases **35 that had
to go**. Both rows are in the table above and neither is hidden behind the other.

Eight to one is a reason to run the model, not a reason to trust it. The eight are a
requester receiving their own record; the one is a third party's personal information in a
stranger's hands, and it cannot be recalled. Which configuration to run is a public body's
decision and this repository does not make it: the rules-only row is the safer one, costs
nothing to reproduce and needs no gateway.

**And the leak rate is still well above the blunt baseline's 1.8 percent.** That gap is
what releasing anything at all costs. A tool that never released a span would have no leak
rate and no reason to exist.

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
- **The published corpus is easier than the province.** Every one of its 5,355 spans is
  plain ASCII: no apostrophe, no Mac or Mc, no accent, in a tool named after Newfoundland
  and Labrador, where O'Brien and MacDonald are ordinary. On a corpus identical in every
  other respect but drawn from those shapes, **person recall falls from 96.2 to 93.4
  percent**, and project 04's engine falls from 96.5 to 94.2.

  One corpus per shape says where it goes, and it is not where either project expected.
  Apostrophes and Mac prefixes cost almost nothing (0.0 points for 04's engine). The two
  expensive shapes are **a bare accented forename, at 7.4 points**, and **a two-token
  surname like St. Croix or Le Drew, at 6.4**. An accented *surname* costs 0.9, so it is
  the position that matters and not the character: the detector is not confused by the
  accent, it is short of evidence when an unfamiliar token stands alone. A forename, an
  honorific or ordinary prose beside it rescues every shape tested, in prose, in a
  signature block and in a distribution list.

  So the remedy is lexical, not orthographic, and no character-class fix reaches it. The
  comparison is [`results/names.md`](results/names.md), `sever eval-names --profiles all`
  regenerates it, and `tests/test_name_shapes_detected.py` pins the diagnosis. The
  published tables stay on the plain corpus so they remain comparable with what came
  before; the harder numbers are published beside them rather than instead of them.
- **33.3 percent over-redaction on officials acting in an official capacity** is the
  weakest number in the table, and 23.8 of those 33.3 points are escalation rather than a
  wrong answer: names the rules could not pair with a title anywhere in the record, which
  the model was also unwilling to place. It rose once when detection improved, because
  finding more of a record's people means more of them reaching the escalation path.
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
29.7 percent to 56.4 percent with the same rules, because a person's capacity is almost
never in the sentence
that names them. It is three inches lower, in the signature block.

**Deterministic rules** decide the clear cases in a fixed order that is itself the design:
the requester's own information first, then inherently sensitive identifiers (a director's
health number is not about being a director), then non-personal entity types, then
capacity, then the public register, then the twenty-year rule. Whatever is left goes to a
**model** through the portfolio's Compliant AI Gateway with the personal data class,
seeing typed placeholders and never a name. Its answer is taken only above a measured
confidence threshold; below it the span is escalated with the model's reasoning attached.
When neither is sure, the proposal is to withhold and escalate. There is no rule that
releases a span because nothing matched.

That the class is actually recorded is checkable rather than asserted: the gateway keeps
its own ledger, and as of 2026-09-20 all 999 rows this project has written carry
`data_class = personal`, across 999 calls costing US$1.10 in total.

The boundary is not built on the detector. A name the detector missed is exactly the one
that would slip through a guard made of detections, so a second pass masks anything
proper-noun-shaped or identifier-shaped regardless of whether anything detected it, and the
test that polices this checks finished requests against the **personas**, which are ground
truth. It found 74 real values the first time it ran.

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
python -m spacy download en_core_web_lg

sever taxonomy check                  # the codes, and how many provisions are verified
sever corpus build --documents 210    # the labelled corpus, from a seed, offline and free
sever propose --documents 3           # proposals with the reason for each one
sever export --documents 3            # truly redacted PDFs, schedules, and the leak test
sever report --readme README.md       # every number above
```

`sever report` is the one command behind every published figure. With no flags it runs
the rules-only configuration, spends nothing and needs no gateway: the model layer is off
by default because a corpus run is thousands of calls, and the safe default is the one
that cannot spend money by accident.

The model row reproduces for nothing too. Every answer the model gave is committed in
`results/model-answers.jsonl`, and `--replay-only` reads it instead of calling out:

```bash
sever report --model --replay-only --answer-cache results/model-answers.jsonl
sever eval-thresholds                 # the confidence threshold, swept, also from the cache
```

The cache is publishable for the same reason the requests are: it holds what the model
said about typed placeholders, and a test asserts that no persona value appears in it.
Reproducing the paid run itself needs the gateway and costs about US$0.51. The gateway is
project 04's library, `boundary`, a private repository that is not on PyPI, so it is not a
declared dependency here and cannot be: the `boundary` package on PyPI is an unrelated
project. Where you have project 04, install it by path with
`uv pip install -e ../04-compliant-ai-gateway`; the version this project needs, and why, is
in `sever/gateway.py`.

## Repository

| Path | What is in it |
|---|---|
| `sever/taxonomy/` | The codes and their provisions, in YAML. `docs/taxonomy.md` is generated from it |
| `sever/corpus/` | Personas with roles assigned first, six document templates, the renderer that emits labels with the text |
| `sever/detect/` | Presidio plus the access-to-information recognisers, and within-document coreference |
| `sever/context/` | Signature blocks, letterheads, public registers, requester matching, the context record |
| `sever/decide/` | The rules in precedence order, the placeholder policy, the model layer |
| `sever/review/` | True-redaction export, the generated schedule, the append-only audit log |
| `sever/eval/` | Confusion matrices with bootstrap intervals, the baselines, the PDF leak test, the threshold sweep |
| `results/` | The generated tables, and `model-answers.jsonl`: every answer the model gave, so the model row replays without a gateway |

Docs: [taxonomy](docs/taxonomy.md) (generated) · [escalation](docs/escalation.md) ·
[data](docs/data.md) · [what did not work](docs/rejected.md) ·
[detector comparison](results/detectors.md) · [threshold sweep](results/thresholds.md) ·
[plan](PLAN.md)

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

## Which detector the published numbers use, and why

Detection runs behind a protocol with two implementations: the one in this repository,
using Presidio and spaCy directly, and the portfolio's `boundary.redact`. They are close,
at 97.4 and 96.3 percent recall over the same 5,355 labelled values.
`results/detectors.md` has the comparison per entity type, regenerated by
`sever eval-detector`.

**The headline tables use the in-repo detector.** The gateway is a private repository, so
a number produced with it is a number a stranger cannot check, and that is the one property
this repository exists for. It costs nothing to insist on: the in-repo detector is
currently the better of the two.

Both improved by being compared. `boundary.redact` was ahead until the comparison found
three defects in it, the worst returning a Medical Care Plan number unredacted on 57 of 210
pages without refusing; all three are fixed. The comparison also found two here, the worse
being personas generating social insurance numbers that failed the Luhn checksum, so no
correct detector would ever have flagged them and the corpus had never exercised that path.
And it settled the spaCy model: `en_core_web_lg` over `en_core_web_sm` is 97.4 percent
recall against 92.6, which cut the leak rate from 14.1 percent to 5.4.

The comparison was worth running in both directions. It found three defects in the
gateway's engine, all since fixed, the worst of which returned a Medical Care Plan number
unredacted on 57 of 210 pages without refusing. It also found two in this project: personas
were generating social insurance numbers that failed the Luhn checksum, so no correct
detector would ever have flagged them and the corpus had never exercised that path at all.

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
