**Corpus:** 210 synthetic documents, 210 pages, 5460 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Jurisdiction: federal. Generated 2026-10-21 by `sever report`.

**Model layer:** openrouter/jaredpalmer/kev-4b, through the 04 gateway with data class `personal`. 7549 model calls, US$0.7639, US$0.00010 per call, 18188965 in / 1130684 out tokens, 2372 replayed from the answer cache, free, of which 2294 were the tool's own residual and 7627 the model-only baseline.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 9.1% (7.8% to 10.4%), n=980 | 9.1% (7.8% to 10.4%), n=980 |
| `K2` | 2170 | n/a | 31.4% (29.0% to 33.8%), n=2170 | 31.4% (29.0% to 33.8%), n=2170 |
| `K3` | 280 | n/a | 0.7% (0.0% to 2.1%), n=280 | 0.7% (0.0% to 2.1%), n=280 |
| `K4` | 70 | n/a | 1.4% (0.0% to 4.3%), n=70 | 1.4% (0.0% to 4.3%), n=70 |
| `K6` | 280 | n/a | 45.4% (39.6% to 51.2%), n=280 | 15.7% (12.0% to 19.4%), n=280 |
| `R1` | 1680 | 1.1% (0.7% to 1.7%), n=1680 | n/a | 65.8% (62.1% to 69.6%), n=1680 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 1.1% (0.7% to 1.7%), n=1680 | 23.8% (22.3% to 25.3%), n=3780 | 35.2% (33.8% to 36.7%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| model-only, no rules | 1.1% (0.6% to 1.6%), n=1680 | 98.1% (97.4% to 98.7%), n=3780 | 96.6% (96.2% to 97.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sever, rules only | 1.1% (0.7% to 1.7%), n=1680 | 23.8% (22.3% to 25.3%), n=3780 | 35.7% (34.3% to 37.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| blunt redact-all-PII | 1.1% (0.6% to 1.6%), n=1680 | 98.4% (97.9% to 99.0%), n=3780 | 0.0% (0.0% to 1.1%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |
| sentence-only, no document context | 7.4% (5.6% to 9.3%), n=1680 | 51.9% (49.8% to 54.0%), n=3780 | 58.9% (57.2% to 60.6%), n=5460 | 98.6% (98.2% to 99.0%), n=5460 |

**Where the leaks come from**

| System | Leaks | Never found | Found, called impersonal | Box too short | The decision was wrong |
|---|---:|---:|---:|---:|---:|
| sever, rules then the model on the residual | 19 | 17 | 1 | 1 | 0 |
| model-only, no rules | 18 | 17 | 0 | 1 | 0 |
| sever, rules only | 19 | 17 | 1 | 1 | 0 |
| blunt redact-all-PII | 18 | 17 | 0 | 1 | 0 |
| sentence-only, no document context | 124 | 17 | 106 | 1 | 0 |

The middle column is the one worth knowing about. A span typed as a place or an organisation is not personal information, so the rule releases it and says why, and recall counts it as found the whole time. It is a wrong label rather than a wrong decision, and a two-column decomposition blamed the decision layer for it. "Box too short" is a span the tool withheld only part of, where what shows still identifies someone; a remainder that identifies nobody (a long number with four or fewer digits showing, a job title with its role word withheld) is not a leak. See `sever/eval/coverage.py`.

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
