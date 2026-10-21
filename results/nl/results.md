**Corpus:** 210 synthetic documents, 210 pages, 5460 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: nl. Generated 2026-10-21 by `sever report`.

**Model layer:** openrouter/typesafe/jev-1.14 at a confidence threshold of 0.60, below which its answer is escalated to a person, through the 04 gateway with data class `personal`. 9921 answers replayed from the cache, nothing spent, of which 2294 were the tool's own residual and 7627 the model-only baseline.

**Cost:** US$0.00129 per page (CA$0.00174 at 1.35 CAD/USD), from project 04's gateway ledger: US$0.2708 over 2257 paid calls and 210 pages. The pipeline asked 2294 times and paid 2257 of them, because 2% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.00131 each, which is the figure to read if your documents are not generated from templates. A further US$0.6351 bought the model-only baseline, which asks about every span rather than the residual. That is a cost of measuring the tool and not of running it, so it is named here rather than divided into the figure above.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 1.7% (0.8% to 2.8%), n=980 | 1.7% (0.8% to 2.8%), n=980 |
| `K2` | 2170 | n/a | 2.1% (1.5% to 2.8%), n=2170 | 1.8% (1.3% to 2.5%), n=2170 |
| `K3` | 280 | n/a | n/a | 0.0% (0.0% to 3.4%), n=280 |
| `K4` | 70 | n/a | n/a | 50.0% (50.0% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 1.4%), n=280 | 0.0% (0.0% to 1.4%), n=280 |
| `R1` | 1680 | 1.1% (0.7% to 1.7%), n=1680 | n/a | 2.3% (1.4% to 3.1%), n=1680 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 1.1% (0.7% to 1.7%), n=1680 | 1.8% (1.4% to 2.4%), n=3430 | 2.4% (1.9% to 2.8%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| model-only, no rules | 2.7% (2.0% to 3.5%), n=1680 | 5.4% (4.6% to 6.2%), n=3430 | 9.7% (8.8% to 10.7%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sever, rules only | 1.1% (0.7% to 1.7%), n=1680 | 26.2% (24.6% to 27.7%), n=3430 | 36.3% (35.0% to 37.7%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| blunt redact-all-PII | 1.1% (0.6% to 1.6%), n=1680 | 98.3% (97.7% to 98.9%), n=3430 | 0.0% (0.0% to 1.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sentence-only, no document context | 7.4% (5.6% to 9.3%), n=1680 | 52.1% (49.7% to 54.3%), n=3430 | 58.9% (57.2% to 60.6%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |

**Released without the weighing the statute requires**

| System | Spans the Act reserves for a person | Released anyway |
|---|---:|---|
| sever, rules then the model on the residual | 350 | 90.0% (86.7% to 92.9%), n=350 |
| model-only, no rules | 350 | 55.1% (47.1% to 62.5%), n=350 |
| sever, rules only | 350 | 89.4% (86.0% to 92.6%), n=350 |
| blunt redact-all-PII | 350 | 0.0% (0.0% to 2.3%), n=350 |
| sentence-only, no document context | 350 | 50.0% (50.0% to 50.0%), n=350 |

This is not a leak and it is not over-redaction. The information might have been releasable and it might not: nobody weighed it. For a tool whose first claim is that it proposes and a person decides, settling a question the Act assigns to a person is a failure of a different kind from getting the answer wrong, so it is counted separately rather than folded into a rate that would hide it.

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | Box too short | The decision was wrong |
|---|---:|---:|---:|---:|---:|
| sever, rules then the model on the residual | 19 | 17 | 1 | 1 | 0 |
| model-only, no rules | 46 | 17 | 1 | 3 | 25 |
| sever, rules only | 19 | 17 | 1 | 1 | 0 |
| blunt redact-all-PII | 18 | 17 | 0 | 1 | 0 |
| sentence-only, no document context | 124 | 17 | 106 | 1 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it. "Box too short" is a span the tool withheld only part of, where what shows still identifies someone; a remainder that identifies nobody (a long number with four or fewer digits showing, a job title with its role word withheld) is not a leak. See `sever/eval/coverage.py`.

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
