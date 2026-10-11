**Corpus:** 210 synthetic documents, 210 pages, 5460 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: nl. Generated 2026-10-10 by `sever report`.

**Model layer:** anthropic/claude-haiku-4-5-20251001, through the 04 gateway with data class `personal`. 9629 answers replayed from the cache, nothing spent, of which 2002 were the tool's own residual and 7627 the model-only baseline.

**Cost:** US$0.00456 per page (CA$0.00615 at 1.35 CAD/USD), from project 04's gateway ledger: US$0.9571 over 871 paid calls and 210 pages. The pipeline asked 2002 times and paid 871 of them, because 56% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.01048 each, which is the figure to read if your documents are not generated from templates. A further US$1.7491 bought the model-only baseline, which asks about every span rather than the residual. That is a cost of measuring the tool and not of running it, so it is named here rather than divided into the figure above.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 6.9% (5.6% to 8.3%), n=980 | 5.3% (3.9% to 6.8%), n=980 |
| `K2` | 2170 | n/a | 29.5% (27.1% to 32.0%), n=2170 | 19.1% (17.3% to 21.1%), n=2170 |
| `K3` | 280 | n/a | n/a | 0.0% (0.0% to 3.4%), n=280 |
| `K4` | 70 | n/a | n/a | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 1.4%), n=280 | 0.0% (0.0% to 1.4%), n=280 |
| `R1` | 1680 | 4.6% (3.6% to 5.7%), n=1680 | n/a | 43.9% (41.4% to 46.3%), n=1680 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 4.6% (3.6% to 5.7%), n=1680 | 20.7% (19.0% to 22.3%), n=3430 | 22.7% (21.6% to 23.7%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| model-only, no rules | 15.4% (13.8% to 17.0%), n=1680 | 43.5% (40.7% to 46.1%), n=3430 | 40.8% (39.7% to 41.9%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sever, rules only | 2.5% (1.7% to 3.5%), n=1680 | 23.7% (22.1% to 25.2%), n=3430 | 37.3% (35.8% to 38.7%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| blunt redact-all-PII | 1.1% (0.6% to 1.6%), n=1680 | 98.3% (97.7% to 98.9%), n=3430 | 0.0% (0.0% to 1.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sentence-only, no document context | 8.8% (6.9% to 10.8%), n=1680 | 49.4% (46.9% to 51.6%), n=3430 | 59.0% (57.4% to 60.6%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |

**Released without the weighing the statute requires**

| System | Spans the Act reserves for a person | Released anyway |
|---|---:|---|
| sever, rules then the model on the residual | 350 | 90.3% (87.0% to 93.2%), n=350 |
| model-only, no rules | 350 | 82.9% (79.4% to 86.5%), n=350 |
| sever, rules only | 350 | 89.7% (86.3% to 92.7%), n=350 |
| blunt redact-all-PII | 350 | 0.0% (0.0% to 2.3%), n=350 |
| sentence-only, no document context | 350 | 51.4% (50.0% to 53.2%), n=350 |

This is not a leak and it is not over-redaction. The information might have been releasable and it might not: nobody weighed it. For a tool whose first claim is that it proposes and a person decides, settling a question the Act assigns to a person is a failure of a different kind from getting the answer wrong, so it is counted separately rather than folded into a rate that would hide it.

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | Box too short | The decision was wrong |
|---|---:|---:|---:|---:|---:|
| sever, rules then the model on the residual | 77 | 17 | 24 | 1 | 35 |
| model-only, no rules | 259 | 17 | 101 | 1 | 140 |
| sever, rules only | 42 | 17 | 24 | 1 | 0 |
| blunt redact-all-PII | 18 | 17 | 0 | 1 | 0 |
| sentence-only, no document context | 147 | 17 | 129 | 1 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it. "Box too short" is a span the tool withheld only part of, where what shows still identifies someone; a remainder that identifies nobody (a long number with four or fewer digits showing, a job title with its role word withheld) is not a leak. See `sever/eval/coverage.py`.

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
