**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: federal. Generated 2026-09-20 by `sever report`.

**Model layer:** anthropic/claude-haiku-4-5-20251001, through the 04 gateway with data class `personal`. 2606 answers replayed from the cache, nothing spent.

**Cost:** US$0.00456 per page (CA$0.00615 at 1.35 CAD/USD), from project 04's gateway ledger: US$0.9571 over 871 paid calls and 210 pages. The pipeline asked 2606 times and paid 871 of them, because 67% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.01364 each, which is the figure to read if your documents are not generated from templates.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 6.9% (5.6% to 8.3%), n=980 | 5.3% (3.9% to 6.8%), n=980 |
| `K2` | 2345 | n/a | 34.0% (32.0% to 36.1%), n=2345 | 24.3% (22.3% to 26.5%), n=2345 |
| `K3` | 280 | n/a | 7.1% (4.3% to 10.4%), n=280 | 7.1% (4.3% to 10.4%), n=280 |
| `K4` | 70 | n/a | 48.6% (45.7% to 50.0%), n=70 | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 0.0%), n=280 | 0.0% (0.0% to 0.0%), n=280 |
| `R1` | 1400 | 5.3% (4.1% to 6.5%), n=1400 | n/a | 57.6% (54.8% to 60.6%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 5.3% (4.1% to 6.5%), n=1400 | 23.3% (21.9% to 24.6%), n=3955 | 27.7% (26.4% to 29.1%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| sever, rules only | 2.8% (1.8% to 4.0%), n=1400 | 30.3% (29.1% to 31.4%), n=3955 | 46.5% (45.4% to 47.5%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| blunt redact-all-PII | 1.1% (0.6% to 1.7%), n=1400 | 98.5% (97.9% to 99.0%), n=3955 | 0.0% (0.0% to 0.0%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| sentence-only, no document context | 2.8% (1.8% to 4.0%), n=1400 | 58.0% (56.0% to 59.9%), n=3955 | 66.9% (65.5% to 68.4%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | The decision was wrong |
|---|---:|---:|---:|---:|
| sever, rules then the model on the residual | 74 | 16 | 23 | 35 |
| sever, rules only | 39 | 16 | 23 | 0 |
| blunt redact-all-PII | 16 | 16 | 0 | 0 |
| sentence-only, no document context | 39 | 16 | 23 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it.

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2287 | 0 | text layer only |

_OCR channel disabled for this run._

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
