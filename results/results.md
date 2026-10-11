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
