**Corpus:** 210 synthetic documents, 210 pages, 5460 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: nl. Generated 2026-10-10 by `sever report`.

**Model layer:** anthropic/claude-haiku-4-5-20251001, through the 04 gateway with data class `personal`. 9752 answers replayed from the cache, nothing spent, of which 2002 were the tool's own residual and 7750 the model-only baseline.

**Cost:** US$0.00456 per page (CA$0.00615 at 1.35 CAD/USD), from project 04's gateway ledger: US$0.9571 over 871 paid calls and 210 pages. The pipeline asked 2002 times and paid 871 of them, because 56% of its requests were byte-identical to one already made. Without that deduplication the same pages would cost about US$0.01048 each, which is the figure to read if your documents are not generated from templates. A further US$1.4744 bought the model-only baseline, which asks about every span rather than the residual. That is a cost of measuring the tool and not of running it, so it is named here rather than divided into the figure above.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 6.9% (5.6% to 8.3%), n=980 | 5.3% (3.9% to 6.8%), n=980 |
| `K2` | 2170 | n/a | 29.6% (27.1% to 32.1%), n=2170 | 19.1% (17.3% to 21.1%), n=2170 |
| `K3` | 280 | n/a | n/a | 0.0% (0.0% to 3.4%), n=280 |
| `K4` | 70 | n/a | n/a | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 1.4%), n=280 | 0.0% (0.0% to 1.4%), n=280 |
| `R1` | 1680 | 4.5% (3.5% to 5.7%), n=1680 | n/a | 43.9% (41.4% to 46.3%), n=1680 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 4.5% (3.5% to 5.7%), n=1680 | 20.7% (19.0% to 22.4%), n=3430 | 22.7% (21.6% to 23.8%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| model-only, no rules | 15.5% (13.9% to 17.1%), n=1680 | 43.1% (40.4% to 45.8%), n=3430 | 41.4% (40.4% to 42.5%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sever, rules only | 2.4% (1.6% to 3.5%), n=1680 | 23.7% (22.1% to 25.2%), n=3430 | 37.3% (35.8% to 38.7%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| blunt redact-all-PII | 1.0% (0.6% to 1.5%), n=1680 | 98.3% (97.7% to 98.9%), n=3430 | 0.0% (0.0% to 1.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sentence-only, no document context | 8.7% (6.8% to 10.7%), n=1680 | 49.4% (46.9% to 51.6%), n=3430 | 59.0% (57.4% to 60.6%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |

**Released without the weighing the statute requires**

| System | Spans the Act reserves for a person | Released anyway |
|---|---:|---|
| sever, rules then the model on the residual | 350 | 90.3% (87.0% to 93.2%), n=350 |
| model-only, no rules | 350 | 73.7% (69.3% to 77.8%), n=350 |
| sever, rules only | 350 | 89.7% (86.3% to 92.7%), n=350 |
| blunt redact-all-PII | 350 | 0.0% (0.0% to 2.3%), n=350 |
| sentence-only, no document context | 350 | 51.4% (50.0% to 53.2%), n=350 |

This is not a leak and it is not over-redaction. The information might have been releasable and it might not: nobody weighed it. For a tool whose first claim is that it proposes and a person decides, settling a question the Act assigns to a person is a failure of a different kind from getting the answer wrong, so it is counted separately rather than folded into a rate that would hide it.

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | The decision was wrong |
|---|---:|---:|---:|---:|
| sever, rules then the model on the residual | 76 | 17 | 24 | 35 |
| model-only, no rules | 261 | 17 | 104 | 140 |
| sever, rules only | 41 | 17 | 24 | 0 |
| blunt redact-all-PII | 17 | 17 | 0 | 0 |
| sentence-only, no document context | 146 | 17 | 129 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it.

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
