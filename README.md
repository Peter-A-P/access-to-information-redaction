# Hundreds of Pages, Redacted in an Afternoon

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

**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: federal. Generated 2026-10-01 by `sever report`.

**Model layer:** anthropic/claude-haiku-4-5-20251001, through the 04 gateway with data class `personal`. 9818 answers replayed from the cache, nothing spent, of which 2173 were the tool's own residual and 7645 the model-only baseline.

**Cost:** US$0.00456 per page (CA$0.00615 at 1.35 CAD/USD), from project 04's gateway ledger: US$0.9571 over 871 paid calls and 210 pages. The pipeline asked 2173 times and paid 871 of them, because 60% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.01137 each, which is the figure to read if your documents are not generated from templates. A further US$1.4616 bought the model-only baseline, which asks about every span rather than the residual. That is a cost of measuring the tool and not of running it, so it is named here rather than divided into the figure above.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 6.9% (5.6% to 8.3%), n=980 | 5.3% (3.9% to 6.8%), n=980 |
| `K2` | 2345 | n/a | 30.3% (28.1% to 32.5%), n=2345 | 20.6% (18.8% to 22.5%), n=2345 |
| `K3` | 280 | n/a | 0.0% (0.0% to 3.4%), n=280 | 0.0% (0.0% to 3.4%), n=280 |
| `K4` | 70 | n/a | 48.6% (45.7% to 50.0%), n=70 | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 1.4%), n=280 | 0.0% (0.0% to 1.4%), n=280 |
| `R1` | 1400 | 5.3% (4.1% to 6.5%), n=1400 | n/a | 57.6% (54.8% to 60.6%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 5.3% (4.1% to 6.5%), n=1400 | 20.5% (19.1% to 21.9%), n=3955 | 25.7% (24.5% to 26.9%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| model-only, no rules | 4.8% (3.8% to 5.8%), n=1400 | 41.9% (39.4% to 44.4%), n=3955 | 42.3% (41.2% to 43.3%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| sever, rules only | 2.8% (1.8% to 4.0%), n=1400 | 23.2% (21.7% to 24.6%), n=3955 | 41.2% (40.0% to 42.4%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| blunt redact-all-PII | 1.1% (0.6% to 1.7%), n=1400 | 98.5% (97.9% to 99.0%), n=3955 | 0.0% (0.0% to 1.1%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| sentence-only, no document context | 2.8% (1.8% to 4.0%), n=1400 | 48.9% (46.7% to 50.8%), n=3955 | 60.2% (58.6% to 61.6%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | The decision was wrong |
|---|---:|---:|---:|---:|
| sever, rules then the model on the residual | 74 | 16 | 23 | 35 |
| model-only, no rules | 67 | 16 | 16 | 35 |
| sever, rules only | 39 | 16 | 23 | 0 |
| blunt redact-all-PII | 16 | 16 | 0 | 0 |
| sentence-only, no document context | 39 | 16 | 23 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it.

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2141 | 0 | text layer and OCR |

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.

<!-- END RESULTS -->

**The number that matters is the second column.** Any tool can get the leak rate down by
redacting everything, and the blunt baseline in the table does exactly that: it withholds
98.5 percent of the information that must be released. A record that comes back with the
signing officer's name, the minister on the letterhead, the department and the requester's
own address blacked out has been answered in form and refused in substance. That column is
what nobody publishes.

## The honest limitation

**The case for the model layer is much weaker than it was, because the rules got better.**

With the rules alone the tool leaks 2.8 percent and withholds 23.2 percent of what must be
released. With the model deciding what the rules could not, at the confidence threshold
measured in [`results/thresholds.md`](results/thresholds.md), it leaks 5.3 percent and
withholds 20.5 percent. In counts, over 5,355 labelled spans: turning the model on
correctly releases **107 spans the rules had withheld** and wrongly releases **35 that had
to go**. Both rows are in the table above and neither is hidden behind the other.

That ratio was **eight to one** a day ago and it is **three to one** now. Nothing about the
model changed. What changed is that the rules stopped escalating bare job titles, which
removed seven points of over-redaction from the rules-only row at no cost in leaks, and a
good part of what the model had been earning its keep on was cleaning up after a
deterministic bug. The measurement that found the bug was not aimed at the model at all.

**That is the general warning and it is worth more than the number.** A model layer measured
on top of an imperfect deterministic layer is partly being paid to fix it, and the payment
is invisible until the deterministic layer improves. Anyone comparing "rules" against
"rules plus a model" is measuring the rules they happen to have, not the architecture.

Three to one is thin. The three are a requester receiving their own record; the one is a
third party's personal information in a stranger's hands, and it cannot be recalled. On
these numbers the rules-only configuration is the defensible default, and it is what the
tool does with no flags: the model layer is opt-in, costs money, and now has to argue for
2.7 points of over-redaction against 2.5 points of leak. Which to run is a public body's
decision and this repository does not make it.

**Read the leak decomposition above before deciding the rules are the weak part.** Every
one of the 39 leaks in the rules-only row is the detector's fault: 16 spans it never found
and 23 it found and called a place or an organisation, which is not personal information,
so the rule released them and said so. The deterministic rules contribute **zero**, and
that stayed true through the job-title change, which is the check that mattered: releasing
a category that used to be withheld is exactly how a leak class gets introduced. That
column only exists because a two-bucket decomposition filed those 23 under "the decision
was wrong" and pointed the next fix at the wrong module.

**And the leak rate is still above the blunt baseline's 1.1 percent.** That gap is
what releasing anything at all costs. A tool that never released a span would have no leak
rate and no reason to exist.

**Nobody has actually reviewed anything.** The page-by-page interface exists and the
release gate is enforced in code, but the reviewer time study has not been run, so there is
no measured support for any claim about hours saved. The "days of reading become hours of
review" line at the top is the goal of the project, not a result. The study itself is one
command, `sever study`, and [docs/reviewer-study.md](docs/reviewer-study.md) is how to run
it; what it is waiting for is people.

Three more limitations, none of them small:

- **The corpus is synthetic.** Labels are exact because roles were assigned before the
  documents were written, which is the only affordable way to get 5,355 labelled spans. It
  also means the documents are template-shaped. The real-record test that would check this
  (published federal releases, where everything visible was judged releasable by a human)
  is built and tested, and has not been run: no release package has been added yet, so
  [`results/releases.md`](results/releases.md) reports no rate rather than a made-up one.
- **The published corpus is easier than the province.** Every one of its 5,355 spans is
  plain ASCII: no apostrophe, no Mac or Mc, no accent, in a tool named after Newfoundland
  and Labrador, where O'Brien and MacDonald are ordinary. On a corpus identical in every
  other respect but drawn from those shapes, **person recall falls from 96.2 to 93.4
  percent**, and project 04's engine falls from 96.5 to 94.2.

  One corpus per shape said where it went, and it was not where either project expected.
  Apostrophes and Mac prefixes cost almost nothing (0.0 points for 04's engine). The two
  expensive shapes were **a bare accented forename, at 7.4 points**, and **a two-token
  surname like St. Croix or Le Drew, at 6.4**. An accented *surname* cost 0.9. The same
  characters, eight times the cost, purely from position: the detector was not confused by
  the accent, it was short of evidence when an unfamiliar token stood alone. A forename, an
  honorific or ordinary prose beside it rescued every shape tested.

  **So the remedy was lexical, and it is now built.** A record that names Bernadette Le
  Drew once has said that "Le Drew" is a person's name in this record, so every person the
  page detectors find licenses the other whole-word occurrences of their name parts across
  the whole document, and a span the detector typed as a *place* is re-typed where the
  document has already called those exact characters a person. Person recall on the hard
  corpus goes **93.4 to 98.0 percent**, the penalty for using this province's names falls
  from 2.8 points to 0.8, and the leak rate falls from 4.7 to **2.8 percent** because a
  surname typed as a LOCATION was being released as "not information about an identifiable
  individual".

  A Labrador profile is what says the mechanism is vocabulary and not spelling: Innu and
  Inuit surnames from Sheshatshiu, Natuashish and the Nunatsiavut communities, every one
  plain ASCII with no accent or apostrophe. Orthographically they are Doucette; to a model
  trained on English news they are nothing, and the sweep recovers 3.1 points on them.
  **23 of the 29 person spans still missed belong to someone the detector never found as a
  person anywhere in that record**, which is the part no document-level inference can reach
  and the case a gazetteer would have to cover. The ablation
  per shape is [`results/sweep.md`](results/sweep.md); the engines side by side are
  [`results/names.md`](results/names.md); `tests/test_name_shapes_detected.py` pins the
  diagnosis and `tests/test_name_sweep.py` pins the fix. The published tables stay on the
  plain corpus so they stay comparable; the harder numbers sit beside them.
- **34.0 percent over-redaction on officials acting in an official capacity** is the
  weakest number in the table, and 24.3 of those 34.0 points are escalation rather than a
  wrong answer: names the rules could not pair with a title anywhere in the record, which
  the model was also unwilling to place. It rose once when detection improved, because
  finding more of a record's people means more of them reaching the escalation path.
- **All 36 statutory provisions are verified** against the consolidated texts, federal
  current to 2026-07-21 and ATIPPA to 2026-09-20: each carries the quote, the date it was
  checked and the URL it was checked against. Nothing defaults to verified, and the format
  refuses a provision that is neither verified nor explicitly excused with a reason.
  Reading them changed three mappings; [docs/escalation.md](docs/escalation.md) says which
  and why.

## What the deterministic rules are worth

The results table has a `model-only, no rules` row: the same model, the same context record,
the same threshold, with the rules removed so every span is sent rather than only the
residual. The difference between it and the full configuration is the deterministic layer
and nothing else.

It leaks about the same, **4.8% against 5.3%, intervals overlapping**. It over-redacts
twice as much, **41.9% against 20.5%**.

So the rules are not the safety net under the model, which is how this architecture is
usually justified. The model is roughly as safe on its own. The rules earn their place by
being decisive: they settle the cases that have a settled answer, the model is asked only
the genuinely ambiguous ones, and a model asked only hard questions escalates far less than
a model asked everything.

Read that against the `sentence-only` row, which is the same rules with the document context
blanked, at 48.9%. Neither half is carrying the tool, and each ablation costs about what the
other does.

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
it is worth: judging a name from its sentence alone more than doubles over-redaction, from
23.2 percent to 48.9 percent with the same rules, because a person's capacity is almost
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

**And the boundary turns out not to cost accuracy.** The paired ablation in
[`results/placeholders.md`](results/placeholders.md) runs the same spans through the same
model twice, on placeholders and on the raw record, and taking the names away **halves the
leak rate**, from 60.2 to 30.1 percent. Shown a plausible name the model becomes willing to
place the person and is wrong more often than not; deprived of it, it reasons from the
structure, which is the evidence that actually decides the question, and escalates when the
structure does not settle it. Both arms run on a model on this machine, because the raw arm
carries names and this repository will not send those to a vendor, so the absolute figures
belong to a 7B model rather than to the pipeline. The direction is the finding, and it
reverses the assumption this project had been publishing.

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

## What a scan costs, and it is not what you would guess

`results/scanned.md` renders each record to PDF, degrades it the way a document scanner
does, reads it back with Tesseract, re-projects every label through a character alignment
and scores the pipeline on what the OCR produced.

| Input | Character error rate | Labels that survived | Detector recall | Leak rate | Over-redaction |
|---|---:|---:|---|---|---|
| native (no OCR) | 0.0% | 100.0% | 98.0% | 3.0% | **28.7%** |
| office scanner | 0.6% | 100.0% | 97.6% | 3.6% | **48.9%** |
| photocopy | 0.9% | 99.9% | 96.8% | 3.9% | **48.1%** |
| fax, 100 dpi | 65.1% | 45.2% | 52.9% | 69.2% | 36.7% |

The worry about OCR is that a misread name gets released. That barely happens until the page
falls apart entirely. What happens first is that **the requester gets a blacker page**: a
near-perfect scan costs a fifth of a point of recall and twenty points of over-redaction.

The characters survive; the layout does not. Every recovered block is body text, so nothing
is role-bearing, and the rules lose the signature block and the letterhead, which is how
they tell an official signing a letter from a third party named in it. Unable to place the
person, they escalate, and escalation withholds. The three working profiles are
indistinguishable from each other, so the effort does not belong in scan quality: it belongs
in recovering structure from the word geometry Tesseract already returns.

## The reviewer decides, and here is where they do it

`sever review` opens the reviewer's screen on loopback: one page at a time, the record
rendered as the characters the redaction will actually be applied to, every proposed
severance highlighted with its category, its provision and the reason the tool gives for it.

Two rules are enforced in code rather than promised in prose, and
[`tests/test_review_app.py`](tests/test_review_app.py) holds both:

- **A page cannot be completed while a span on it is undecided.** The button refuses and
  names the spans.
- **A record cannot be released while a page is incomplete.** `Session.release_gate` raises
  rather than returning false, because a caller who forgets to check a boolean releases the
  document and a caller who forgets to catch an exception does not.

Nothing is ever edited. A reviewer who changes their mind posts a second action and the log
keeps both rows; the screen shows the latest and the log shows the history. And because
detector recall is 98.6 percent rather than 100, a reviewer can select text the tool never
proposed and sever it themselves: a reviewer who can only answer the tool's list inherits
the tool's misses.

The application fetches nothing from anywhere. No CDN, no bundler, no client framework:
server-rendered HTML, form posts, and about thirty lines of hand-written JavaScript. A tool
for reading government records should run with the network cable out.

`sever export --audit review/audit.duckdb` applies the redactions the reviewer decided:
a proposal they rejected stays in the record, a span they moved to a keep category stays,
and a span they selected and severed themselves goes. Until 2026-10-01 it applied the
tool's proposals to any page the log said was complete, so a reviewer's own severance of a
name the tool had missed went out in clear;
[`tests/test_export_reads_decisions.py`](tests/test_export_reads_decisions.py) holds the fix
against the PDF. Without `--audit` the same PDFs are written, the same leak test runs, and
the files are named `-proposed.pdf`, because a document nobody has reviewed is not a release
however good the redactions are.

## Try it

```bash
uv sync --extra detect --group dev    # the versions in uv.lock, the same ones CI runs
source .venv/bin/activate
python -m spacy download en_core_web_lg

sever taxonomy check                  # the codes, and how many provisions are verified
sever corpus build --documents 210    # the labelled corpus, from a seed, offline and free
sever propose --documents 3           # proposals with the reason for each one
sever export --documents 3            # redacted PDFs, schedules, and the leak test
sever review --documents 3            # the reviewer's screen, on 127.0.0.1:8000
sever study                           # the reviewer time study, one person at a time
sever study report                    # score it: minutes per page and accuracy, per arm
sever report --readme README.md       # every number above
sever report --jurisdiction nl        # the same corpus under the NL statute
sever eval-scanned --documents 50     # render, scan, read back, and score it (needs Tesseract)
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
in `sever/gateway.py`. Neither it nor the spaCy model is in `uv.lock`, and `uv sync` removes
whatever the lock does not list, so re-sync with `uv sync --inexact` once they are installed.

## Repository

| Path | What is in it |
|---|---|
| `sever/taxonomy/` | The codes and their provisions, in YAML. `docs/taxonomy.md` is generated from it |
| `sever/corpus/` | Personas with roles assigned first, six document templates, the renderer that emits labels with the text |
| `sever/detect/` | Presidio plus the access-to-information recognisers, and within-document coreference |
| `sever/context/` | Signature blocks, letterheads, public registers, requester matching, the context record |
| `sever/decide/` | The rules in precedence order, the placeholder policy, the model layer |
| `sever/review/` | The reviewer application, true-redaction export, the generated schedule, the append-only audit log |
| `sever/eval/` | Confusion matrices with bootstrap intervals, the baselines, the PDF leak test, the threshold sweep |
| `results/` | The generated tables, and `model-answers.jsonl`: every answer the model gave, so the model row replays without a gateway |

Docs: [taxonomy](docs/taxonomy.md) (generated) · [escalation](docs/escalation.md) ·
[data](docs/data.md) · [what did not work](docs/rejected.md) ·
[detector comparison](results/detectors.md) · [threshold sweep](results/thresholds.md) ·
[name shapes](results/names.md) · [the name sweep, ablated](results/sweep.md) ·
[what the privacy boundary does to accuracy](results/placeholders.md) ·
[reviewer time study](results/reviewer.md) ·
[the same corpus under ATIPPA](results/nl/results.md) ·
[the scanned track](results/scanned.md) ·
[real released records](results/releases.md) · [plan](PLAN.md)

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
recall against 92.6, which cut the leak rate from 14.1 percent to 5.4 at the time.

## What is built, and what is not

| Built and measured | Built, not yet measured | Not built |
|---|---|---|
| Taxonomy, two jurisdictions, all 36 provisions verified | Reviewer time study: `sever study` runs and scores it; nobody has sat down yet | Hosted demo |
| 210-page labelled corpus, labels by construction | Over-redaction on published federal releases: loader, guard and measurement tested; no package added yet | |
| Detection, context record, rules, escalation | | |
| The model layer, through the gateway on placeholders | | |
| All four baselines (blunt, rules-only, sentence-only, model-only), with intervals | | |
| The placeholders ablation, and the threshold sweep | | |
| The scanned track, four degradation profiles, CER measured | |
| True-redaction export, schedule, PDF leak test | |
| Append-only hash-chained audit log | |
| The reviewer application, with the release gate | |
| Cost per page, from the gateway ledger | |

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
