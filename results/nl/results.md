**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: nl. Generated 2026-09-20 by `sever report`.

**Cost:** US$0.00456 per page (CA$0.00615 at 1.35 CAD/USD), from project 04's gateway ledger: US$0.9571 over 871 paid calls and 210 pages. The pipeline asked 2606 times and paid 871 of them, because 67% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.01364 each, which is the figure to read if your documents are not generated from templates.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 9.1% (7.8% to 10.4%), n=980 | 9.1% (7.8% to 10.4%), n=980 |
| `K2` | 2345 | n/a | 41.1% (39.4% to 42.8%), n=2345 | 41.1% (39.4% to 42.8%), n=2345 |
| `K3` | 280 | n/a | n/a | 14.3% (9.6% to 18.9%), n=280 |
| `K4` | 70 | n/a | n/a | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 25.0% (21.3% to 28.6%), n=280 | 25.0% (21.3% to 28.6%), n=280 |
| `R1` | 1400 | 2.8% (1.8% to 4.0%), n=1400 | n/a | 92.2% (90.5% to 93.9%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules only | 2.8% (1.8% to 4.0%), n=1400 | 31.2% (29.9% to 32.3%), n=3605 | 46.5% (45.4% to 47.5%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| blunt redact-all-PII | 1.1% (0.6% to 1.7%), n=1400 | 98.3% (97.7% to 98.9%), n=3605 | 0.0% (0.0% to 0.0%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| sentence-only, no document context | 2.8% (1.8% to 4.0%), n=1400 | 57.9% (55.7% to 59.9%), n=3605 | 66.9% (65.5% to 68.4%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |

**Released without the weighing the statute requires**

| System | Spans the Act reserves for a person | Released anyway |
|---|---:|---|
| sever, rules only | 350 | 78.9% (74.4% to 83.1%), n=350 |
| blunt redact-all-PII | 350 | 0.0% (0.0% to 0.0%), n=350 |
| sentence-only, no document context | 350 | 40.6% (36.3% to 44.6%), n=350 |

This is not a leak and it is not over-redaction. The information might have been releasable and it might not: nobody weighed it. For a tool whose first claim is that it proposes and a person decides, settling a question the Act assigns to a person is a failure of a different kind from getting the answer wrong, so it is counted separately rather than folded into a rate that would hide it.

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | The decision was wrong |
|---|---:|---:|---:|---:|
| sever, rules only | 39 | 16 | 23 | 0 |
| blunt redact-all-PII | 16 | 16 | 0 | 0 |
| sentence-only, no document context | 39 | 16 | 23 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it.

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
