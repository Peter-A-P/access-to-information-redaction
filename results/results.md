**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Generated 2026-09-20 by `sever report`.

**Model layer:** anthropic/claude-haiku-4-5-20251001, through the 04 gateway with data class `personal`. 2550 answers replayed from the cache, nothing spent.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 6.3% (5.2% to 7.5%), n=980 | 4.7% (3.5% to 6.0%), n=980 |
| `K2` | 2345 | n/a | 33.3% (31.3% to 35.4%), n=2345 | 23.8% (21.8% to 25.9%), n=2345 |
| `K3` | 280 | n/a | 7.1% (4.3% to 10.4%), n=280 | 7.1% (4.3% to 10.4%), n=280 |
| `K4` | 70 | n/a | 48.6% (45.7% to 50.0%), n=70 | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 0.0% (0.0% to 0.0%), n=280 | 0.0% (0.0% to 0.0%), n=280 |
| `R1` | 1400 | 7.9% (6.3% to 9.5%), n=1400 | n/a | 56.1% (53.3% to 59.1%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules then the model on the residual | 7.9% (6.3% to 9.5%), n=1400 | 22.7% (21.4% to 24.0%), n=3955 | 26.9% (25.7% to 28.3%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |
| sever, rules only | 5.4% (3.9% to 7.0%), n=1400 | 29.7% (28.5% to 30.8%), n=3955 | 45.4% (44.3% to 46.3%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |
| blunt redact-all-PII | 1.8% (1.1% to 2.5%), n=1400 | 97.2% (96.5% to 97.9%), n=3955 | 0.0% (0.0% to 0.0%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |
| sentence-only, no document context | 5.4% (3.9% to 7.0%), n=1400 | 56.4% (54.4% to 58.3%), n=3955 | 65.1% (63.6% to 66.5%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |

**Where the leaks come from**

| System | Leaks | The detector never found the span | The decision was wrong |
|---|---:|---:|---:|
| sever, rules then the model on the residual | 110 | 25 | 85 |
| sever, rules only | 75 | 25 | 50 |
| blunt redact-all-PII | 25 | 25 | 0 |
| sentence-only, no document context | 75 | 25 | 50 |

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2224 | 0 | text layer only |

_OCR channel disabled for this run._

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
