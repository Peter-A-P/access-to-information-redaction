# What did not work

Rule C of the portfolio: name an approach that was tried and rejected, with the evidence.
Three are recorded here. The first is the approach this project exists to replace, and the
measurement is the argument for the project. The second is a design idea inside the project
that was wrong, caught by a test, and replaced. The third is a number that was guessed and
turned out to be the wrong guess.

## 1. Blunt redact-all-PII

**The approach.** Run a general PII detector over the record and redact every span it
finds. This is what an off-the-shelf tool does, it is what most public bodies are offered,
and it takes about twenty lines of code. It is implemented in
`sever/decide/pipeline.py::blunt_baseline` and it is measured on the same corpus, with the
same detections, as the tool itself.

**Why it is tempting.** It is safe in the direction people worry about. On the corpus it
leaks 1.8 percent against this tool's 7.9, and every one of its leaks is a span the
detector never found rather than a decision it got wrong. If leak rate were the only
number, the blunt baseline would win and this project would not need to exist.

**Why it was rejected.**

| System | Leak rate | Over-redaction rate |
|---|---|---|
| Blunt redact-all-PII | 1.8% (1.1 to 2.5) | **97.2% (96.5 to 97.9)** |
| This tool, rules then the model on the residual | 7.9% (6.3 to 9.5) | **22.7% (21.4 to 24.0)** |
| This tool, rules only | 5.4% (3.9 to 7.0) | **29.7% (28.5 to 30.8)** |

It withholds **97.2 percent of everything that must be released**. On the corpus that means
the signing officer's name and title, the minister on the letterhead, the department, the
requester's own address in their own file. What it produces is not a redacted record, it is
a page of black boxes with the prepositions left in, and a requester who receives one has
been answered in form and refused in substance.

The 6.1-point leak gap is the honest cost of releasing anything at all. It is smaller than
it looks: 25 of this tool's 110 leaks are the same detector misses the blunt baseline has,
so the decision layer contributes 85 of them, 50 from the rules and 35 more from the model.

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

**The trade, stated plainly.** Over-masking costs the model context and therefore accuracy,
and the paired placeholders-against-raw-text ablation is designed to measure exactly that
cost. Under-masking sends a real person's name to a vendor, which is not measurable and not
reversible. When one side of a trade shows up in a results table and the other shows up in
a breach, the choice makes itself.

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

---

All three entries are reproducible: `sever report` produces the first table,
`pytest tests/test_no_raw_entity_leaves.py` is the test that produced the second, and
`sever eval-thresholds` produces the third from the committed answer cache.
