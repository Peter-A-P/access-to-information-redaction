**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Generated 2026-09-19 by `sever report`.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 8.8% (7.7% to 10.0%), n=980 | 8.8% (7.7% to 10.0%), n=980 |
| `K2` | 2345 | n/a | 37.8% (36.1% to 39.6%), n=2345 | 37.8% (36.1% to 39.6%), n=2345 |
| `K3` | 280 | n/a | 12.9% (8.6% to 17.5%), n=280 | 12.9% (8.6% to 17.5%), n=280 |
| `K4` | 70 | n/a | 42.9% (35.7% to 48.6%), n=70 | 42.9% (35.7% to 48.6%), n=70 |
| `K6` | 280 | n/a | 25.0% (21.3% to 28.6%), n=280 | 25.0% (21.3% to 28.6%), n=280 |
| `R1` | 1400 | 14.1% (11.8% to 16.5%), n=1400 | n/a | 80.9% (78.3% to 83.6%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules over the full document context | 14.1% (11.8% to 16.5%), n=1400 | 28.0% (26.9% to 29.1%), n=3955 | 41.9% (40.7% to 42.9%), n=5355 | 92.6% (91.8% to 93.3%), n=5355 |
| blunt redact-all-PII | 6.9% (5.6% to 8.4%), n=1400 | 92.4% (91.4% to 93.4%), n=3955 | 0.0% (0.0% to 0.0%), n=5355 | 92.6% (91.8% to 93.3%), n=5355 |
| sentence-only, no document context | 14.1% (11.8% to 16.5%), n=1400 | 52.2% (50.3% to 54.1%), n=3955 | 59.7% (58.1% to 61.2%), n=5355 | 92.6% (91.8% to 93.3%), n=5355 |

**Where the leaks come from**

| System | Leaks | The detector never found the span | The decision was wrong |
|---|---:|---:|---:|
| sever, rules over the full document context | 197 | 97 | 100 |
| blunt redact-all-PII | 97 | 97 | 0 |
| sentence-only, no document context | 197 | 97 | 100 |

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2615 | 0 | text layer only |

_OCR channel disabled for this run._

Intervals are 95 percent bootstrap percentile intervals resampled over the 210 documents,
not over the spans, because spans within a document are not independent: one
persona generates many of them, and resampling spans would report one fact as
many. Project 03 implemented the same estimator independently and the two agree
to within Monte Carlo noise; `tests/test_confusion.py` pins that.
