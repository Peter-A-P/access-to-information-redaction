**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Generated 2026-09-19 by `sever report`.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 8.5% (7.3% to 9.6%), n=980 | 8.5% (7.3% to 9.6%), n=980 |
| `K2` | 2345 | n/a | 42.0% (40.3% to 43.7%), n=2345 | 42.0% (40.3% to 43.7%), n=2345 |
| `K3` | 280 | n/a | 14.3% (9.6% to 18.9%), n=280 | 14.3% (9.6% to 18.9%), n=280 |
| `K4` | 70 | n/a | 48.6% (45.7% to 50.0%), n=70 | 48.6% (45.7% to 50.0%), n=70 |
| `K6` | 280 | n/a | 25.0% (21.3% to 28.6%), n=280 | 25.0% (21.3% to 28.6%), n=280 |
| `R1` | 1400 | 5.4% (3.9% to 7.0%), n=1400 | n/a | 89.6% (87.6% to 91.6%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules over the full document context | 5.4% (3.9% to 7.0%), n=1400 | 30.6% (29.4% to 31.8%), n=3955 | 46.1% (44.9% to 47.1%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |
| blunt redact-all-PII | 1.8% (1.1% to 2.5%), n=1400 | 97.2% (96.5% to 97.9%), n=3955 | 0.0% (0.0% to 0.0%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |
| sentence-only, no document context | 5.4% (3.9% to 7.0%), n=1400 | 57.0% (55.0% to 58.9%), n=3955 | 65.5% (64.0% to 67.0%), n=5355 | 97.4% (96.9% to 97.9%), n=5355 |

**Where the leaks come from**

| System | Leaks | The detector never found the span | The decision was wrong |
|---|---:|---:|---:|
| sever, rules over the full document context | 75 | 25 | 50 |
| blunt redact-all-PII | 25 | 25 | 0 |
| sentence-only, no document context | 75 | 25 | 50 |

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2756 | 0 | text layer only |

_OCR channel disabled for this run._

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
