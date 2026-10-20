**Corpus:** 210 synthetic documents, 210 pages, 5460 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: federal. Generated 2026-10-20 by `sever report`.

**Model layer:** anthropic/claude-haiku-5-5, through the 04 gateway with data class `personal`. 9559 answers replayed from the cache, nothing spent, of which 1932 were the tool's own residual and 7627 the model-only baseline.

**Cost:** US$0.00523 per page (CA$0.00706 at 1.35 CAD/USD), from project 04's gateway ledger: US$1.0983 over 1895 paid calls and 210 pages. The pipeline asked 1932 times and paid 1895 of them, because 2% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.00533 each, which is the figure to read if your documents are not generated from templates. A further US$3.0920 bought the model-only baseline, which asks about every span rather than the residual. That is a cost of measuring the tool and not of running it, so it is named here rather than divided into the figure above.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 3.8% (2.5% to 5.2%), n=980 | 3.7% (2.4% to 5.1%), n=980 |
| `K2` | 2170 | n/a | 22.4% (20.6% to 24.3%), n=2170 | 22.2% (20.4% to 24.0%), n=2170 |
| `K3` | 280 | n/a | 0.7% (0.0% to 2.1%), n=280 | 0.7% (0.0% to 2.1%), n=280 |
| `K4` | 70 | n/a | 48.6% (45.7% to 50.0%), n=70 | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 16.8% (13.1% to 20.5%), n=280 | 16.8% (13.1% to 20.5%), n=280 |
| `R1` | 1680 | 2.6% (1.7% to 3.6%), n=1680 | n/a | 4.5% (3.0% to 6.2%), n=1680 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 2.6% (1.7% to 3.6%), n=1680 | 16.1% (14.8% to 17.3%), n=3780 | 12.4% (11.4% to 13.4%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| model-only, no rules | 1.5% (1.0% to 2.1%), n=1680 | 42.8% (41.2% to 44.5%), n=3780 | 33.6% (32.2% to 35.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sever, rules only | 2.5% (1.7% to 3.5%), n=1680 | 22.4% (20.9% to 23.9%), n=3780 | 36.0% (34.6% to 37.5%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| blunt redact-all-PII | 1.1% (0.6% to 1.6%), n=1680 | 98.4% (97.9% to 99.0%), n=3780 | 0.0% (0.0% to 1.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sentence-only, no document context | 8.8% (6.9% to 10.8%), n=1680 | 49.3% (47.1% to 51.4%), n=3780 | 57.8% (56.0% to 59.4%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | Box too short | The decision was wrong |
|---|---:|---:|---:|---:|---:|
| sever, rules then the model on the residual | 43 | 17 | 24 | 1 | 1 |
| model-only, no rules | 25 | 17 | 3 | 1 | 4 |
| sever, rules only | 42 | 17 | 24 | 1 | 0 |
| blunt redact-all-PII | 18 | 17 | 0 | 1 | 0 |
| sentence-only, no document context | 147 | 17 | 129 | 1 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it. "Box too short" is a span the tool withheld only part of, where what shows still identifies someone; a remainder that identifies nobody (a long number with four or fewer digits showing, a job title with its role word withheld) is not a leak. See `sever/eval/coverage.py`.

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2259 | 0 | text layer and OCR |

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
