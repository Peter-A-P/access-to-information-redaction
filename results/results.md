**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Generated 2026-09-20 by `sever report`.

**Model layer:** anthropic/claude-haiku-4-5-20251001, through the 04 gateway with data class `personal`. 24 model calls, US$0.0266, US$0.00111 per call, 18044 in / 1721 out tokens, 2550 replayed from the answer cache, free.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 6.9% (5.6% to 8.3%), n=980 | 5.3% (3.9% to 6.8%), n=980 |
| `K2` | 2345 | n/a | 33.8% (31.7% to 35.9%), n=2345 | 24.1% (22.2% to 26.3%), n=2345 |
| `K3` | 280 | n/a | 7.1% (4.3% to 10.4%), n=280 | 7.1% (4.3% to 10.4%), n=280 |
| `K4` | 70 | n/a | 48.6% (45.7% to 50.0%), n=70 | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 0.0%), n=280 | 0.0% (0.0% to 0.0%), n=280 |
| `R1` | 1400 | 7.2% (5.8% to 8.8%), n=1400 | n/a | 56.5% (53.8% to 59.4%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 7.2% (5.8% to 8.8%), n=1400 | 23.1% (21.8% to 24.5%), n=3955 | 27.3% (26.1% to 28.7%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| sever, rules only | 4.7% (3.4% to 6.2%), n=1400 | 30.1% (29.0% to 31.3%), n=3955 | 45.9% (44.8% to 46.9%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| blunt redact-all-PII | 1.1% (0.6% to 1.7%), n=1400 | 98.5% (97.9% to 99.0%), n=3955 | 0.0% (0.0% to 0.0%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |
| sentence-only, no document context | 4.7% (3.4% to 6.2%), n=1400 | 57.5% (55.5% to 59.3%), n=3955 | 66.1% (64.5% to 67.5%), n=5355 | 98.6% (98.1% to 99.0%), n=5355 |

**Where the leaks come from**

| System | Leaks | The detector never found the span | The decision was wrong |
|---|---:|---:|---:|
| sever, rules then the model on the residual | 101 | 16 | 85 |
| sever, rules only | 66 | 16 | 50 |
| blunt redact-all-PII | 16 | 16 | 0 |
| sentence-only, no document context | 66 | 16 | 50 |

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2255 | 0 | text layer only |

_OCR channel disabled for this run._

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
