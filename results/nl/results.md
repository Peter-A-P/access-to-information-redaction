**Corpus:** 210 synthetic documents, 210 pages, 5460 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: nl. Generated 2026-10-08 by `sever report`.

**Cost:** US$0.00456 per page (CA$0.00615 at 1.35 CAD/USD), from project 04's gateway ledger: US$0.9571 over 871 paid calls and 210 pages. The pipeline asked 2606 times and paid 871 of them, because 67% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.01364 each, which is the figure to read if your documents are not generated from templates. A further US$1.4616 bought the model-only baseline, which asks about every span rather than the residual. That is a cost of measuring the tool and not of running it, so it is named here rather than divided into the figure above.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 9.1% (7.8% to 10.4%), n=980 | 9.1% (7.8% to 10.4%), n=980 |
| `K2` | 2345 | n/a | 30.7% (28.5% to 33.1%), n=2345 | 30.7% (28.5% to 33.1%), n=2345 |
| `K3` | 280 | n/a | n/a | 0.7% (0.0% to 2.1%), n=280 |
| `K4` | 70 | n/a | n/a | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 25.0% (21.3% to 28.6%), n=280 | 25.0% (21.3% to 28.6%), n=280 |
| `R1` | 1505 | 2.6% (1.7% to 3.7%), n=1505 | n/a | 85.8% (84.1% to 87.6%), n=1505 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules only | 2.6% (1.7% to 3.7%), n=1505 | 24.4% (22.9% to 25.8%), n=3605 | 40.4% (39.2% to 41.6%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| blunt redact-all-PII | 1.1% (0.6% to 1.6%), n=1505 | 98.3% (97.7% to 98.9%), n=3605 | 0.0% (0.0% to 1.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sentence-only, no document context | 2.6% (1.7% to 3.7%), n=1505 | 48.9% (46.5% to 51.0%), n=3605 | 59.0% (57.4% to 60.6%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |

**Released without the weighing the statute requires**

| System | Spans the Act reserves for a person | Released anyway |
|---|---:|---|
| sever, rules only | 350 | 89.7% (86.3% to 92.7%), n=350 |
| blunt redact-all-PII | 350 | 0.0% (0.0% to 2.3%), n=350 |
| sentence-only, no document context | 350 | 51.4% (50.0% to 53.2%), n=350 |

This is not a leak and it is not over-redaction. The information might have been releasable and it might not: nobody weighed it. For a tool whose first claim is that it proposes and a person decides, settling a question the Act assigns to a person is a failure of a different kind from getting the answer wrong, so it is counted separately rather than folded into a rate that would hide it.

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | The decision was wrong |
|---|---:|---:|---:|---:|
| sever, rules only | 39 | 16 | 23 | 0 |
| blunt redact-all-PII | 16 | 16 | 0 | 0 |
| sentence-only, no document context | 39 | 16 | 23 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it.

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2385 | 0 | text layer and OCR |

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
