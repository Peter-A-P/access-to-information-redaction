**Corpus:** 210 synthetic documents, 210 pages, 5460 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: federal. Generated 2026-10-08 by `sever report`.

**Model layer:** anthropic/claude-haiku-4-5-20251001, through the 04 gateway with data class `personal`. 9923 answers replayed from the cache, nothing spent, of which 2173 were the tool's own residual and 7750 the model-only baseline.

**Cost:** US$0.00456 per page (CA$0.00615 at 1.35 CAD/USD), from project 04's gateway ledger: US$0.9571 over 871 paid calls and 210 pages. The pipeline asked 2173 times and paid 871 of them, because 60% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.01137 each, which is the figure to read if your documents are not generated from templates. A further US$1.4744 bought the model-only baseline, which asks about every span rather than the residual. That is a cost of measuring the tool and not of running it, so it is named here rather than divided into the figure above.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 6.9% (5.6% to 8.3%), n=980 | 5.3% (3.9% to 6.8%), n=980 |
| `K2` | 2345 | n/a | 30.3% (28.1% to 32.5%), n=2345 | 20.6% (18.8% to 22.5%), n=2345 |
| `K3` | 280 | n/a | 0.0% (0.0% to 3.4%), n=280 | 0.0% (0.0% to 3.4%), n=280 |
| `K4` | 70 | n/a | 48.6% (45.7% to 50.0%), n=70 | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 1.4%), n=280 | 0.0% (0.0% to 1.4%), n=280 |
| `R1` | 1505 | 4.9% (3.8% to 6.1%), n=1505 | n/a | 53.6% (51.4% to 56.0%), n=1505 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 4.9% (3.8% to 6.1%), n=1505 | 20.5% (19.1% to 21.9%), n=3955 | 25.2% (24.1% to 26.4%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| model-only, no rules | 11.4% (9.8% to 13.0%), n=1505 | 41.9% (39.4% to 44.4%), n=3955 | 41.4% (40.4% to 42.5%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sever, rules only | 2.6% (1.7% to 3.7%), n=1505 | 23.2% (21.7% to 24.6%), n=3955 | 40.4% (39.2% to 41.6%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| blunt redact-all-PII | 1.1% (0.6% to 1.6%), n=1505 | 98.5% (97.9% to 99.0%), n=3955 | 0.0% (0.0% to 1.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sentence-only, no document context | 2.6% (1.7% to 3.7%), n=1505 | 48.9% (46.7% to 50.8%), n=3955 | 59.0% (57.4% to 60.6%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | The decision was wrong |
|---|---:|---:|---:|---:|
| sever, rules then the model on the residual | 74 | 16 | 23 | 35 |
| model-only, no rules | 172 | 16 | 16 | 140 |
| sever, rules only | 39 | 16 | 23 | 0 |
| blunt redact-all-PII | 16 | 16 | 0 | 0 |
| sentence-only, no document context | 39 | 16 | 23 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it.

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2246 | 0 | text layer and OCR |

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
