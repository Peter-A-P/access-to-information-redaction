# What did not work

Rule C of the portfolio: name an approach that was tried and rejected, with the evidence.
Five are recorded here. The first is the approach this project exists to replace, and the
measurement is the argument for the project. The second is a design idea inside the project
that was wrong, caught by a test, and replaced. The third is a number that was guessed and
turned out to be the wrong guess. The fourth is a measurement that was healthy and was
looking at the wrong thing. The fifth is a test that passed for a reason that had nothing to
do with what it was testing.

## 1. Blunt redact-all-PII

**The approach.** Run a general PII detector over the record and redact every span it
finds. This is what an off-the-shelf tool does, it is what most public bodies are offered,
and it takes about twenty lines of code. It is implemented in
`sever/decide/pipeline.py::blunt_baseline` and it is measured on the same corpus, with the
same detections, as the tool itself.

**Why it is tempting.** It is safe in the direction people worry about. On the corpus it
leaks 1.1 percent against this tool's 5.3, and every one of its leaks is a span the
detector never found rather than a decision it got wrong. If leak rate were the only
number, the blunt baseline would win and this project would not need to exist.

**Why it was rejected.**

| System | Leak rate | Over-redaction rate |
|---|---|---|
| Blunt redact-all-PII | 1.1% (0.6 to 1.7) | **98.5% (97.9 to 99.0)** |
| This tool, rules then the model on the residual | 5.3% (4.1 to 6.5) | **23.3% (21.9 to 24.6)** |
| This tool, rules only | 2.8% (1.8 to 4.0) | **30.3% (29.1 to 31.4)** |

It withholds **98.5 percent of everything that must be released**. On the corpus that means
the signing officer's name and title, the minister on the letterhead, the department, the
requester's own address in their own file. What it produces is not a redacted record, it is
a page of black boxes with the prepositions left in, and a requester who receives one has
been answered in form and refused in substance.

The 4.2-point leak gap is the honest cost of releasing anything at all, and it is smaller
than it looks. Of this tool's 74 leaks, 16 are the same detector misses the blunt baseline
has and 23 more are spans the detector found and typed as a place or an organisation, which
released them. The deterministic rules contribute none. The model contributes the remaining
35, which is what entry 4 below is about: the decomposition had to gain a third column
before any of that was visible.

**What that means for anyone choosing a tool.** Ask a vendor for the must-keep column. It
is the number nobody publishes, and it is the one that decides whether the output is
usable.

## 2. Building the outbound privacy boundary out of detections alone

**The approach.** Every model decision goes through the gateway on typed placeholders, so
the vendor sees `[PERSON_3]` and never a name. The obvious way to build that is to take
every span the detector found and substitute it before the request is built. That is what
the first implementation did.

**Why it was rejected.** It leaked, and it took a corpus-wide test to see it. The test
(`tests/test_no_raw_entity_leaves.py`) does not check the detector's output against the
detector's own substitutions, which would be circular. It checks the finished request
against the **personas**, which are ground truth. On twelve documents it found 74 real
values in the outbound requests, including dates of birth and medical care plan numbers.

Three distinct causes, all invisible without that test:

1. **The policy was built from the residual spans only.** The spans sent to the model are
   the ones the rules could not decide, but the *sentence around* each of them is full of
   entities the rules decided perfectly well, and the sentence travels in the payload.
2. **A detected full name did not license its parts.** The detector finds "Marie Chaulk";
   the prose two sentences later says "Marie". Substituting only the exact surface form
   replaces the first and ships the second.
3. **Detector recall is not 100 percent, and a boundary built on it inherits its misses.**
   After fixing (1) and (2), seven persona names still reached the request because Presidio
   had simply not found them. Presidio also missed `aaronpenashue@gov.nl.ca.example`
   outright, classifying only the `gov.nl.ca` inside it as a URL.

**What replaced it.** The policy is now built over every detection in the document, a
detected name licenses substitution of its parts, and then a second pass runs that does not
trust the detector at all: anything shaped like a proper noun or an identifier is masked
unless it is on a 247-word list of terms that carry decision-relevant meaning and cannot
identify anyone (months, job titles, the names of public bodies, the words of the
legislation). `sever/decide/placeholders.py::scrub_unrecognised`.

**The trade, as it was assumed to be.** Over-masking costs the model context and therefore
accuracy; under-masking sends a real person's name to a vendor, which is not measurable and
not reversible. When one side of a trade shows up in a results table and the other shows up
in a breach, the choice makes itself. That argument stood here for weeks and it did not need
the trade to be real, only to be worth paying.

**The trade, as measured.** It is not a trade. `results/placeholders.md` runs the same
spans through the same model twice, once on placeholders and once on the raw record:

| Arm | Leak rate | Over-redaction |
|---|---|---|
| typed placeholders | **30.1% (21.7 to 39.0)** | 19.0% (15.4 to 22.8) |
| raw text | **60.2% (53.7 to 66.7)** | 7.4% (5.2 to 9.7) |

Taking the names away **halved the leak rate**. The two arms agreed on 55.7 percent of the
spans, so the name is doing a great deal of work in the model's reasoning; it is simply
doing harmful work. Shown a plausible name the model becomes willing to place the person,
its escalation rate falls from 30.5 to 14.1 percent, and it is wrong about which side of
the line they are on more often than not. Deprived of the name it has only the structure to
reason from, which is the evidence that actually decides the question, and when the
structure does not settle it the model says so.

Read on this corpus and this model, the privacy boundary is not a cost centre that needs
justifying. It is the reason the model layer withholds when it should.

**A second effect, which is not about accuracy at all.** Asked about the same 244 spans, the
placeholder arm needed 171 distinct requests and the raw arm needed 239. Masked payloads
repeat across documents because once the names are gone the structure is all that is left,
and the structure recurs; raw payloads are unique precisely because the names are. A
redacted corpus is more cacheable than an unredacted one, so the boundary makes the model
layer cheaper as well as more accurate. `results/placeholders.md` reports the two arms
separately rather than blending them, because a single hit rate would average the finding
away.

**What is and is not claimed.** Both arms run on a 7B model on this laptop, because the raw
arm carries names and this repository's rule is that names do not leave the machine. Both
arms therefore leak far more than the production pipeline does on Haiku, and these absolute
numbers are not the pipeline's. What the pairing supports is the direction and the rough
size of the effect, on 20 documents with the intervals shown. The same run on a frontier
model would need the raw arm to reach a vendor, which this project will not do.

**The general lesson.** A privacy boundary whose strength equals a model's recall is not a
boundary. Test it against ground truth, not against the component you are testing.

## 3. A model confidence threshold picked by judgement

**The approach.** The pipeline discards a model answer below a confidence threshold and
escalates the span instead. The threshold was set to 0.7, which is where such numbers
usually get set, with a comment admitting it was a starting value and that a sweep would
replace it. It survived the whole build that way.

**Why it was rejected.** The sweep, once it existed, showed 0.7 does nothing at all.

| Threshold | Answers accepted | Leak rate | Over-redaction |
|---|---:|---|---|
| 0.00 | 100% | 13.4% | 15.6% |
| 0.60 | 99% | 13.4% | 15.6% |
| **0.70** | **66%** | **13.4%** | **15.6%** |
| 0.80 | 63% | 13.1% | 16.4% |
| **0.90** | **43%** | **7.9%** | **22.7%** |
| 0.95 | 43% | 7.9% | 22.8% |
| 1.01 (rules only) | 0% | 5.4% | 29.7% |

At 0.7 a third of the model's answers are being thrown away and **not one published number
changes**. The answers discarded between 0.6 and 0.8 are the ones where the model itself
answered E1, so discarding them for low confidence and honouring them produce the same
decision. The threshold was doing visible work in the logs and no work in the results.

The real boundary is 0.90, and it is a cliff rather than a slope: the leak rate falls by
5.5 points in one step and nothing moves above it. Haiku 4.5 reports confidence in a few
clusters, not on a continuum, so this parameter is a switch with one useful position.

**What replaced it.** `DEFAULT_THRESHOLD = 0.90`, in `sever/decide/pipeline.py`, with the
sweep that chose it in `results/thresholds.md` and the reason it sits at the withholding
end of the switch rather than the releasing end: releasing a third party's information
cannot be undone, and an escalation costs a reviewer a minute.

**What made it cheap to find.** The sweep is only honest if every row is scored against the
*same* model answers, so the run records each answer to `results/model-answers.jsonl` and
the sweep replays it. One paid run of US$0.51 bought all eight rows, and anyone cloning the
repository can reproduce them with `sever eval-thresholds` and no gateway, no key and no
spend. Had each row needed its own run, this table would have cost eight times as much and
measured the model's variance as much as the threshold.

**The general lesson.** A default with a comment promising to measure it later is a
finding waiting to happen. The cheapest version of that measurement is usually to record
the model's raw output once and score it many times, rather than to re-run the model.

## 4. Measuring a detector by recall alone

**The approach.** Report detector quality as recall per entity type: of the values the
generator inserted, how many did the detector find. It is the standard number, this project
published it for months, and `results/detectors.md` is full of it.

**Why it was rejected as sufficient.** Recall asks whether a span was found. It does not
ask what the span was called, and in this tool the label decides whether the text is
released.

Three separate defects hid behind a healthy recall figure, each found by something other
than recall:

| What happened | What recall said | What it cost |
|---|---|---|
| "Bannerman Street" found inside "14 Bannerman Street" | found | the house number released |
| "CASE NOTES" matched by the case-number recogniser | not measured | a box over an ordinary heading |
| "Tuglavina" found and typed as a LOCATION | found | the surname **released** as K6 |

The third is the worst and the last to be found. A LOCATION is not personal information, so
the rule releases it with a reason attached, and the redaction schedule tells the requester
that a third party's surname is "not information about an identifiable individual". A miss
would have been better: the span would have been unredacted but the tool would not have
argued for it.

**What replaced it.** Three columns rather than one, in every generated table: recall,
**fully covered** (the detection spans the whole labelled value, not part of it), and
**typed correctly**. Plus `sweep.retype_known_people`, which re-types a span the document
has already attributed to a person, and `results/sweep.md`, which reports what share of the
remaining misses are people the detector never found anywhere, because that is the part no
amount of document-level inference can reach.

**The general lesson.** For a tool whose output is a decision rather than a list, measure
the decision. A detector metric that cannot distinguish "missed" from "found and labelled
in the category that releases it" is measuring the wrong end of the pipeline.

## 5. Trusting a backstop that had never been asked a question

**The approach.** Entry 2 above ends with a general lesson: "a privacy boundary whose
strength equals a model's recall is not a boundary. Test it against ground truth, not
against the component you are testing." The second pass, `scrub_unrecognised`, is what that
sentence produced. It masks anything name-shaped or identifier-shaped whether or not the
detector found it, and the corpus-wide test asserts that no persona value reaches a request.

Every assertion passed. The boundary was considered tested.

**Why it was rejected.** The test could not fail for the reason it was written. The detector
finds email addresses and phone numbers, so the policy substituted them before the second
pass ever saw them, and the second pass was never asked whether it could hold them alone.
It could not. It let **every** email address through untouched, plain ASCII included, and
every Canadian postal code: an address carrying no digit is not identifier-shaped, a
lowercase word is not name-shaped, and `A1B 2C3` is all caps so it is not name-shaped while
starting with a letter so the digit run cannot reach it.

The report came from project 04, who found the identical hole in their own second pass on
the identical day, and whose framing is the one worth keeping: *a masking column where a
recogniser is doing the work says nothing about the layer that exists for when a recogniser
is wrong.*

**What replaced it.** The corpus-wide test runs a second time with the detector removed
entirely. Nothing is substituted; only the second pass stands between a persona value and
the request. It now masks all of them, and a stronger piece of evidence arrived by accident:
after three changes to the second pass, the committed answer cache still replayed with no
misses. A cache key is a hash of the outbound message, so unchanged keys mean the second
pass had not been altering a single request in the whole corpus. It was inert, and no test
that kept the detector switched on could ever have said so.

Two more holes fell out of the same idea, both from 04's harness first. `(709) 555-0199`
was masked as `(709) [NUMBER?]`, leaving the area code in clear beside its own placeholder,
which is worse than leaving the number alone because it advertises what was removed. And a
date written in words has no backstop at all, which is now a stated limit with a test rather
than an undiscovered gap: masking every written date would black out the dates a decision
turns on.

**The general lesson,** which is entry 2's lesson at one more remove. Testing a layered
defence with every layer switched on measures the top layer. If a backstop has never been
observed doing anything, it has not been tested; it has been carried. Turn off the layer
above it and see what it catches.

---

All five entries are reproducible: `sever report` produces the first table,
`pytest tests/test_no_raw_entity_leaves.py` is the test that produced the second,
`sever eval-thresholds` produces the third from the committed answer cache, and
`sever eval-sweep --profiles all` produces the fourth, and
`pytest tests/test_no_raw_entity_leaves.py` is the test that produced the fifth.
