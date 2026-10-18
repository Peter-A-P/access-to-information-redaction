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

**Corpus:** 210 synthetic documents, 210 pages, 5460 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: federal. Generated 2026-10-10 by `sever report`.

**Model layer:** anthropic/claude-haiku-4-5-20251001, through the 04 gateway with data class `personal`. 246 model calls, US$0.2737, US$0.00111 per call, 189330 in / 16868 out tokens, 9383 replayed from the answer cache, free, of which 2002 were the tool's own residual and 7627 the model-only baseline.

**Cost:** US$0.00456 per page (CA$0.00615 at 1.35 CAD/USD), from project 04's gateway ledger: US$0.9571 over 871 paid calls and 210 pages. The pipeline asked 2002 times and paid 871 of them, because 56% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.01048 each, which is the figure to read if your documents are not generated from templates. A further US$1.4754 bought the model-only baseline, which asks about every span rather than the residual. That is a cost of measuring the tool and not of running it, so it is named here rather than divided into the figure above.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 6.9% (5.6% to 8.3%), n=980 | 5.3% (3.9% to 6.8%), n=980 |
| `K2` | 2170 | n/a | 29.5% (27.1% to 32.0%), n=2170 | 19.1% (17.3% to 21.1%), n=2170 |
| `K3` | 280 | n/a | 0.0% (0.0% to 3.4%), n=280 | 0.0% (0.0% to 3.4%), n=280 |
| `K4` | 70 | n/a | 48.6% (45.7% to 50.0%), n=70 | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 1.4%), n=280 | 0.0% (0.0% to 1.4%), n=280 |
| `R1` | 1680 | 4.6% (3.6% to 5.7%), n=1680 | n/a | 43.9% (41.4% to 46.3%), n=1680 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 4.6% (3.6% to 5.7%), n=1680 | 19.7% (18.1% to 21.2%), n=3780 | 22.7% (21.6% to 23.7%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| model-only, no rules | 15.4% (13.8% to 17.0%), n=1680 | 41.0% (38.4% to 43.6%), n=3780 | 40.8% (39.7% to 41.9%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sever, rules only | 2.5% (1.7% to 3.5%), n=1680 | 22.4% (20.9% to 23.9%), n=3780 | 37.3% (35.8% to 38.7%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| blunt redact-all-PII | 1.1% (0.6% to 1.6%), n=1680 | 98.4% (97.9% to 99.0%), n=3780 | 0.0% (0.0% to 1.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sentence-only, no document context | 8.8% (6.9% to 10.8%), n=1680 | 49.3% (47.1% to 51.4%), n=3780 | 59.0% (57.4% to 60.6%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | Box too short | The decision was wrong |
|---|---:|---:|---:|---:|---:|
| sever, rules then the model on the residual | 77 | 17 | 24 | 1 | 35 |
| model-only, no rules | 259 | 17 | 101 | 1 | 140 |
| sever, rules only | 42 | 17 | 24 | 1 | 0 |
| blunt redact-all-PII | 18 | 17 | 0 | 1 | 0 |
| sentence-only, no document context | 147 | 17 | 129 | 1 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it. "Box too short" is a span the tool withheld only part of, where what shows still identifies someone; a remainder that identifies nobody (a long number with four or fewer digits showing, a job title with its role word withheld) is not a leak. See `sever/eval/coverage.py`.

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2361 | 0 | text layer and OCR |

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

With the rules alone the tool leaks 2.5 percent and withholds 22.4 percent of what must be
released. With the model deciding what the rules could not, at the confidence threshold
measured in [`results/thresholds.md`](results/thresholds.md), it leaks 4.6 percent and
withholds 19.7 percent. In counts, over 5,460 labelled spans: turning the model on
correctly releases **105 spans the rules had withheld** and wrongly releases **35 that had
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
2.7 points of over-redaction against 2.1 points of leak. Which to run is a public body's
decision and this repository does not make it.

**Project 03's release gate, asked the same question, blocks the model layer.** Its
paired non-inferiority test, with the document as the item and a three-point margin, finds
turning the model on worse on documents with no leak: 84.3 percent of documents clean with
the rules alone against 67.6 with the model, **35 documents worse and none better**. It
passes the model on the requester's own information (+7.6 points) and on what is not
personal information (+40.0), and cannot decide the publicly-available category on 70
documents. One block is enough for the gate, and it is the right one: the gains are a
requester receiving their own record sooner, the loss is a stranger's information that
cannot be recalled. [`gate/decision.md`](gate/decision.md) is the gate's own output and
`sever gate-export` writes what it was run on, for nothing.

**Read the leak decomposition above before deciding the rules are the weak part.** Every
one of the 39 leaks in the rules-only row is the detector's fault: 16 spans it never found
and 23 it found and called a place or an organisation, which is not personal information,
so the rule released them and said so. The deterministic rules contribute **zero**, and
that stayed true through the job-title change, which is the check that mattered: releasing
a category that used to be withheld is exactly how a leak class gets introduced. That
column only exists because a two-bucket decomposition filed those 23 under "the decision
was wrong" and pointed the next fix at the wrong module.

**Every leak rate on this page now counts a partial box the way a reader would.** Until
2026-10-10 the tables asked whether the box that overlapped a span most was a withholding
one, so a box over nine digits of a twelve-digit number counted as the whole number
withheld. Now a must-redact span is withheld only when every letter and digit of it is
under a box, or when what shows identifies nobody: a long number with four or fewer digits
showing, or a job title with its role word withheld ([`sever/eval/coverage.py`](sever/eval/coverage.py)).
The reviewer study uses the same rule. It moved every leak rate by one span, the same one in
every row: "Desmond Ivany of Happy Valley" detected as one name, which leaves "Goose Bay"
showing, and that names the town. It is in the decomposition as "Box too short".

**And the leak rate is still above the blunt baseline's 1.1 percent.** That gap is
what releasing anything at all costs. A tool that never released a span would have no leak
rate and no reason to exist.

**Three reviewers have done the study, and with proposals every one of them was more than
twice as fast.** Each reviewed twenty test records, ten unaided and then ten with
proposals, after a practice page in each half, with the halves swapped between reviewers
so every record was reviewed in both arms ([results/reviewer.md](results/reviewer.md)).
Unaided and then with proposals, in minutes a page: reviewer 1, eight years in
access-to-information work, 2.2 and 1.1 (2026-10-10); reviewer 2, 2.1 and 0.9
(2026-10-17); reviewer 3, 2.2 and 0.8 (2026-10-18). **Holding the records fixed, unaided
review took 2.3 times as long as review with proposals (2.0 to 2.6)**: 130 seconds a page
against 56. That is the time claim at the top of this page: a reviewer reads a page in
under a minute instead of over two. Three people, all doing the proposals half second, so
some of the gain is familiarity with the templates, and the interval resamples records
rather than people.

The reviewer disagreed with the labels once, consistently, and the labels changed. In all
four workplace-complaint memoranda they withheld the respondent's name and title and the
complainant's title, which the corpus labelled as officials acting in their role. Their
ruling: an internal, confidential complaint is about the people in it, not their positions,
it has nothing to do with the requester, and a title released beside a severed name
identifies the person in a division with one holder of that title. The corpus now labels
both parties and their titles R1, and a `complaint_party` rule withholds them. Every table
on this page carries the change.

Scored against those labels, over all three reviewers, **the proposals half was also the
more accurate: leaks 2.4 percent with proposals against 6.8 unaided** (0.8 to 4.4 against
4.4 to 9.2, the first pair of intervals in the study that do not overlap), and 0.4 against
6.4 without the partials that identify nobody. Over-redaction 0.6 and 0.7, against 10.6
and 23.2 for the unreviewed proposals on the same records. Reviewer 3's nine unaided misses
were the hand-made kind again: a complaint party's or a correspondent's first name standing
alone later in the text ("Maeve", "Loretta"), a delegate's full name the second time it
appears, an employee number, a "sibling", a complaint party's title, and two selections
one character short of an email address and a street number. Their two leaks with proposals
were both the tool's box approved as drawn: the frozen MCP defect, and "Happy Valley-Goose
Bay" left outside a delegate's name. Like reviewer 2, they withheld the client's own MCP
number in the case notes, in both arms; the label stands by Peter's ruling, but two of three
reviewers now read it the other way. Reviewer 2's unaided misses were the kind a person makes by hand: two employee
numbers in an official's signature block, a "sibling" the first reviewer's ruling withholds,
a complaint party's first name, and two hand selections one character short of an email
address and a telephone number. Their one leak with proposals was the frozen MCP defect
below, approved as drawn.

Reviewer 2 also departed from the labels twice, consistently, and Peter ruled on both on
2026-10-18 that the labels stand. They withheld the client's own MCP number, which a
physician's letter repeats, in every case note in both arms (three scored pages and the
practice page); the client is the requester, and a requester's own health number goes back
to them. And they released an official's employee number in a signature block every time it
came up unaided (two scored pages and the practice page); an employee number is an
identifying number assigned to the person, not information about the position. Both count
against the reviewer in the tables. The tool's proposals got the outcome right both times,
releasing the MCP number as the requester's own and withholding the employee number (as an
escalation, not as a decided R1), and in the one case note they saw with proposals the
reviewer overrode the release to withhold the number anyway.

**Reviewer 1's half, in detail.** No over-redaction in either arm; leaks 3.5 percent with
proposals and 1.3 unaided. **Every leak in their proposals half was the tool's box,
approved.** Two were
twelve-digit MCP numbers whose first nine digits the SIN recogniser claimed, leaving the
last three proposed for release; the third was a complainant's title, "Access and Privacy
Coordinator", where the tool's box covered "Coordinator" and the reviewer withheld the box
as drawn. None of the three identifies anyone: three digits of twelve do not, and "Access
and Privacy" names a function several people share, where the whole position names its one
holder. So the study also reports a leak rate that does not count those two kinds of
partial, a long number with four or fewer digits showing and a title with its role word
withheld: **0 percent with proposals** and 1.3 unaided (a delegate's first name, missed),
against 8.7 for the tool alone. Both rules were written after the run they change, at the
reviewer's prompting, so the strict rate stays first. The MCP defect is fixed. The
study's proposals are frozen in `data/study/proposals.jsonl`, so these pages stay scored
against what was on the screen and every later reviewer sees the same tool.

The first run, on 2026-10-08, was a trial: the reviewer was learning the rules and the
application while it was still being changed at their request. It is discarded and is in
no table. `sever study --trial` now exists so that learning happens outside the study, and
[docs/reviewer-study.md](docs/reviewer-study.md) is how to run it.

The trial did settle two rules, and both changed the labels behind every number here.
First, a family relationship that points at a third party ("the client's sibling") is
withheld with the name, because with the name gone it still identifies the person to a
requester who knows their own family. The corpus now labels it R1 and the tool withholds
it. Every table above carries the change, and it reversed a finding: see "What the
deterministic rules are worth". Second, the exclusion for officials covers the public body's own employees and
contractors and nobody else: a physician writing about a client is a third party even in
their professional role. That was always the label; the reference card and the category
text now say so.

Three more limitations, none of them small:

- **The corpus is synthetic.** Labels are exact because roles were assigned before the
  documents were written, which is the only affordable way to get 5,355 labelled spans. It
  also means the documents are template-shaped. The real-record test that checks this
  (published federal releases, where everything visible was judged releasable by a human)
  has now run, on six Library and Archives Canada packages, 82 pages of scanned Defence
  records from 2001 to 2010, and it was unflattering: **the tool withheld every one of the
  538 spans that could be personal information**, all of them escalated rather than
  decided. The spans said why. The detector called OCR fragments, ranks and units people
  ("wu", "LCol", "KAF"), the flat text layer had no signature blocks, and the rules did
  not know a rank is a title.

  **On 2026-10-17 the tool learned the forces' vocabulary and to read layout back from
  text, and over the same 538 spans it now withholds 41.8 percent** (32.8 to 63.4, six
  packages, so the interval is wide), 225 boxes where there were 538
  ([`results/releases.md`](results/releases.md)). Almost all of that is the vocabulary:
  ranks as titles in a Defence record, units and headquarters re-typed, spans with no
  name-shaped word in them dropped. Layout recovery alone moves it from 100 to 95.7
  percent, because these text layers are scanned forms and printed email with no blank
  lines to find paragraphs by. **This is no longer a blind test**: the unit list and some
  of the layout rules were written after reading what these packages withheld, so the
  number says how far the changes go on the records they were written against. More
  packages, scored once before anything changes, are the held-out check. What is still
  withheld is mostly a unit's postal code and telephone numbers, "Kandahar", "Canadian",
  and names in sentences about a member's own complaint or leave, which
  [`docs/escalation.md`](docs/escalation.md) case 7 escalates on purpose.

  **The held-out check says the gain does not travel.** Three packages from two other
  departments, chosen by a rule written before any was downloaded and scored once with the
  code unchanged: External Affairs on East Germany, 1969 to 1990, and two Chinese
  immigration case files from 1913 to 1962, 83 pages
  ([`results/releases-heldout.md`](results/releases-heldout.md)). **The tool withholds 95.2
  percent of the 727 spans a reviewer released there** (93.8 to 97.0). The only change that
  helped was dropping spans with no name-shaped word in them; the military vocabulary had
  nothing to act on and layout recovery found nothing in these text layers. What it
  withheld says why. Ulbricht, Stalin and Honecker are heads of state, which the public
  register does not know. "Son", "wife" and "father" are 116 of the boxes, withheld by
  reviewer 1's family rule, in case files about people most likely released because they
  died more than twenty years ago or were born more than 110 years ago, which is how Library
  and Archives Canada opens personal information in old records; the tool knows only the
  first, and only when the sentence states a date of death. And "Soviet", "German" and "Chinese"
  are escalated as nationality. So the Defence number is a result about Defence records,
  and archival records need the archive's own age rules before anything else.

  **The archive's age rule was then built, and on a fresh set it decided nothing.** K7
  releases what an archival record shows is about someone born more than 110 years ago
  (Privacy Regulations s. 6(c)), from the page's own latest year or a birth stated beside a
  name; a screen drops the release stamp the institution printed. Six more packages were
  chosen by a rule, downloaded and committed before either was written, then scored once:
  Immigration, Health, Justice and an Indian Affairs audit, 1920s to 1990s, 123 pages
  ([`results/releases-fresh.md`](results/releases-fresh.md)). **The tool withholds 88.0
  percent of the 483 spans a reviewer released** (81.2 to 94.4), down from 99.8, and all of
  that drop is the noise screen from 2026-10-17. The commit before today's work scores the
  same 88.0 on them. No page in the six is dated 1916 or earlier, so the 110-year rule had
  nothing to read; and LAC's longer stamp ("Bibliothèque et Archives Canada" on a line of its
  own) was a person 26 times, a form of the stamp the screen was not written for. Both are
  findings about the fresh set, so neither is fixed against it.
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
- **29.5 percent over-redaction on officials acting in an official capacity** is the
  weakest number in the table, and 19.1 of those 29.5 points are escalation rather than a
  wrong answer: names and work addresses the rules could not pair with a title anywhere in
  the record, which the model was also unwilling to place. A published staff directory is
  the remedy a person would use, and [results/directory.md](results/directory.md) measures
  it: matched on the work email address alone it takes the rules-only figure from 30.1 to
  18.8 percent with no leak at all, and matched on names it multiplies the leak rate by
  nine, because an employee who files a grievance is in the directory too.
  [docs/rejected.md](docs/rejected.md) entry 6 has the account. The headline tables use no
  directory, because a directory is something a public body supplies.
- **All 39 statutory provisions are verified** against the consolidated texts, federal
  current to 2026-07-21 (2026-09-30 for the three added on 2026-10-18 for the archival
  rule, K7) and ATIPPA to 2026-09-20: each carries the quote, the date it was
  checked and the URL it was checked against. Nothing defaults to verified, and the format
  refuses a provision that is neither verified nor explicitly excused with a reason.
  Reading them changed three mappings; [docs/escalation.md](docs/escalation.md) says which
  and why.

## What the deterministic rules are worth

The results table has a `model-only, no rules` row: the same model, the same context record,
the same threshold, with the rules removed so every span is sent rather than only the
residual. The difference between it and the full configuration is the deterministic layer
and nothing else.

It leaks more than three times as much, **15.4% against 4.6%**, and over-redacts twice as
much, **41.0% against 19.7%**.

The leak half of that is new, and it comes from two rulings by a reviewer. The first is a
single word. Until 2026-10-08 the two leaked about the same (4.8% against 5.3%), and this section said the rules were not the
safety net under the model. Then a reviewer ruled that "the client's sibling" identifies
the sibling and must be withheld with the name. A rule withholds it every time. Asked on
its own, the model releases it almost every time, because a family word with no name
beside it reads as harmless: 140 of the model-only row's leaks are its decisions,
against 35 when it only sees what the rules leave. The second ruling, on 2026-10-10, widened
the gap again: the parties to a confidential workplace complaint are withheld with their job
titles, and asked about "Regional Director" on its own, the model calls it a position and
releases it, which is 101 of the model-only row's 259 leaks. So the rules *are* a safety
net, for exactly the kind of judgement a public body writes down once and expects applied
every time. They also earn their place by being decisive: they settle the cases that have a settled answer, the model is asked only
the genuinely ambiguous ones, and a model asked only hard questions escalates far less than
a model asked everything.

Read that against the `sentence-only` row, which is the same rules with the document context
blanked, at 49.3%. Neither half is carrying the tool, and each ablation costs about what the
other does. Since the complaint ruling the sentence-only row leaks too, 8.8 percent: whether
a record is a confidential complaint is a fact about the document, not the sentence.

## What this does not do

- It does not decide non-personal exemptions (advice, legal privilege, law enforcement,
  third-party business). It flags candidates for the reviewer with the provision and makes
  no proposal.
- It does not release anything. Every page needs a reviewer's explicit action.
- It is not legal advice. The taxonomy maps categories to provisions of two acts and is
  configurable; a public body applies its own interpretation.
- It does not read handwriting. The scanned track covers typed documents only.

[`docs/escalation.md`](docs/escalation.md) is the full list of where the tool declines to
decide, and why.

## How it works

Documents are ingested with layout: headings, letterhead, signature blocks, email headers.
A scan or a released PDF has no layout in the file, so it is read back from the text
([`sever/ingest/layout.py`](sever/ingest/layout.py)): a closing word or a name with a title
or rank under it starts a signature block, From, Sent and Subject lines are an email header
even when OCR has put each value on a line of its own, and a short first paragraph opening
with a public body's name is a letterhead. On the corpus's own text it recovers every
signature and header label, and takes over-redaction from 41.7 percent with every block
read as a paragraph to 22.4, the same as the native layout
([`results/layout.md`](results/layout.md)); that is on the six layouts it was written
against, so it is an upper bound.
A detector finds candidate spans (Presidio and spaCy, plus recognisers for the identifiers
a general PII engine does not know: medical care plan numbers, departmental file numbers,
employee numbers).

For each span a **context record** is built: which kind of block it sits in, the sentence,
the heading above it, whether a title is paired with this person anywhere in the document,
whether they appear in a public register or on the letterhead, which other mentions in the
record are the same person, and whether they match the configured requester. That record is
the whole argument of the project, and the sentence-only row in the results table is what
it is worth: judging a name from its sentence alone more than doubles over-redaction, from
22.4 percent to 49.3 percent with the same rules, because a person's capacity is almost
never in the sentence
that names them. It is three inches lower, in the signature block.

**Deterministic rules** decide the clear cases in a fixed order that is itself the design:
the requester's own information first, then inherently sensitive identifiers (a director's
health number is not about being a director), then non-personal entity types, then
capacity, then the public register, then the twenty-year rule. Whatever is left goes to a
**model** through the portfolio's gateway (project 04, `boundary`) with the personal data class,
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

Four architecture diagrams, the system, one span through the decision layer, the reviewer's workflow
and how the numbers are produced, are in [docs/architecture.md](docs/architecture.md).

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

| Input | Character error rate | Labels that survived | Detector recall | Leak rate | Over-redaction, read as paragraphs | Over-redaction, layout read back |
|---|---:|---:|---|---|---|---|
| native (no OCR) | 0.0% | 100.0% | 98.1% | 3.0% | | **22.1%** |
| office scanner | 0.6% | 100.0% | 97.4% | 3.8% | 39.9% | **23.1%** |
| photocopy | 0.7% | 100.0% | 97.2% | 6.0% | 39.6% | **23.0%** |
| fax, 100 dpi | 65.2% | 46.9% | 54.8% | 78.7% | 40.1% | 40.1% |

The worry about OCR is that a misread name gets released. That barely happens until the page
falls apart entirely. What happened first, on 50 scanned records, was that **the requester
got a blacker page**: a near-perfect scan cost a fifth of a point of recall and eighteen
points of over-redaction.

The characters survived; the layout did not. Every block came back as body text, so nothing
was role-bearing, and the rules lost the signature block and the letterhead, which is how
they tell an official signing a letter from a third party named in it. **Reading the layout
back from the OCR text closes almost all of that gap** (2026-10-17): the three working
profiles are within two points of the native row, and the leak rate does not move, because
the blocks change and the text does not. The fax row does not recover, because at 100 dpi
there is not enough text left to find a signature in. The recovery was written against the
corpus's six layouts, so these rows are the most it can do, not what it does on a layout it
has never seen; `results/releases.md` is that test, and it recovers much less there.

## The reviewer decides, and here is where they do it

`sever review` opens the reviewer's screen on loopback: one page at a time, the record
rendered as the characters the redaction will actually be applied to, every proposed
severance highlighted. Clicking a highlighted name opens the decision beside it, in words
rather than codes ("The tool proposes: Release, as an official of a public body acting in
that capacity"), with the reason, what the category means, and Withhold, Release and
Escalate, which the keys W, R and E also do; the page does not move. Selecting any other text offers to withhold
it in the same way.

The first person to use it found that none of that had ever worked in a browser: every
decision answered "Method Not Allowed", because the script posted to `form.action`, which
on a form with an input named "action" is that input rather than the URL. Every test passed,
because the tests post forms without a browser. One now checks the script itself, and the fixed screen
was checked by hand in a browser on 2026-10-02. An automated browser check is not in CI.

At the foot of each page, **Release everything still undecided** releases every span the
reviewer has not acted on, in one action. It asks first, and names any of those spans the
tool had proposed to withhold. Each span still gets its own row in the audit log, marked as
released in bulk, and the page still has to be marked complete separately.

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
server-rendered HTML, form posts, and about a hundred lines of hand-written JavaScript. A tool
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
sever demo --insecure-cookie          # the public demonstration, locally; docs/deploy.md
sever study report                    # score it: minutes per page and accuracy, per arm
sever report --readme README.md       # every number above
sever report --jurisdiction nl        # the same corpus under the NL statute
sever eval-scanned --documents 50     # render, scan, read back, and score it (needs Tesseract)
sever eval-layout                     # what the layout is worth, and how much reads back from text
sever gate-export                     # the files project 03's release gate decides on
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
project 04's library, `boundary`, which is public at
[Peter-A-P/compliant-ai-gateway](https://github.com/Peter-A-P/compliant-ai-gateway) but not
on PyPI, so it is not a declared dependency here and cannot be: the `boundary` package on
PyPI is an unrelated project. Clone it beside this repository and install it by path with
`uv pip install -e ../04-compliant-ai-gateway`; the version this project needs, and why, is
in `sever/gateway.py`. Neither it nor the spaCy model is in `uv.lock`, and `uv sync` removes
whatever the lock does not list, so re-sync with `uv sync --inexact` once they are installed.

## Repository

| Path | What is in it |
|---|---|
| `sever/taxonomy/` | The codes and their provisions, in YAML. `docs/taxonomy.md` is generated from it |
| `sever/corpus/` | Personas with roles assigned first, six document templates, the renderer that emits labels with the text |
| `sever/ingest/` | The document model, OCR for the scanned track, released packages, and layout read back from text |
| `sever/detect/` | Presidio plus the access-to-information recognisers, within-document coreference, the name sweep, and the military vocabulary |
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
[layout read back from text](results/layout.md) ·
[real released records](results/releases.md) ·
[held-out releases](results/releases-heldout.md) ·
[fresh releases](results/releases-fresh.md) · [plan](PLAN.md)

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
at 98.6 and 96.3 percent recall over the same 5,355 labelled values, the first with the
document-wide name sweep. Rerun on `boundary` 0.32.0 on 2026-10-01, 04's figure did not
move: its fixes since 0.6.4 (initials, name particles, a file number's glued tail) are for
shapes this corpus does not contain.
`results/detectors.md` has the comparison per entity type, regenerated by
`sever eval-detector`.

**The headline tables use the in-repo detector.** It is the better of the two on this
corpus, and it keeps the headline reproducible from this repository alone: 04 is public,
but a number that needs a second repository checked out beside the first is a step harder
for a stranger to check than one that does not.

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
| Taxonomy, two jurisdictions, all 39 provisions verified | | |
| Reviewer time study, three reviewers: 2.3 times faster with proposals, records held fixed | | |
| 210-page labelled corpus, labels by construction | Hosted demo: `sever demo` and its image are built and tested; not deployed | |
| Over-redaction on published federal releases: 6 packages, 82 pages | | |
| Detection, context record, rules, escalation | | |
| The model layer, through the gateway on placeholders | | |
| All four baselines (blunt, rules-only, sentence-only, model-only), with intervals | | |
| The placeholders ablation, and the threshold sweep | | |
| The scanned track, four degradation profiles, CER measured | |
| Layout read back from text, scored against the native blocks | |
| Canadian Armed Forces ranks, units and OCR noise, on the real-record track | |
| True-redaction export, schedule, PDF leak test | |
| Append-only hash-chained audit log | |
| The reviewer application, with the release gate | |
| Cost per page, from the gateway ledger | |

## Part of a portfolio

One of fifteen projects. It is built on project 04's gateway,
[Inside the Boundary, On the Record](https://github.com/Peter-A-P/compliant-ai-gateway),
and measured with project 03's
[AI Release Gate](https://github.com/Peter-A-P/ai-release-gate). It is the clearest
demonstration of what the gateway is for: a
frontier model used on access-to-information records without personal data leaving the
boundary, measured.

## How this was built

Design, methodology, evaluation choices and judgement are Peter Parker's, including eight
years inside a public body that answers access-to-information requests. AI coding
assistants (Claude Code) were used for implementation and drafting, the way a senior
engineer uses them in 2026. Every number in the results tables is reproducible from this
repository with one command, and that reproducibility is the evidence that matters.
