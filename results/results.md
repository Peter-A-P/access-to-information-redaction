**Corpus:** 210 synthetic documents, 210 pages, 5355 labelled spans, seed 20270802. Labels known by construction. Detector: sever-detector. Generated 2026-09-13 by `sever report`.

**Per category, this tool**

| Category | Spans | Leak rate (must-redact released) | Over-redaction (must-keep withheld) | Escalation rate |
|---|---:|---|---|---|
| `K1` | 980 | n/a | 9.1% (7.8% to 10.4%), n=980 | 9.1% (7.8% to 10.4%), n=980 |
| `K2` | 2345 | n/a | 36.6% (34.7% to 38.5%), n=2345 | 36.6% (34.7% to 38.5%), n=2345 |
| `K3` | 280 | n/a | 12.1% (8.2% to 16.4%), n=280 | 12.1% (8.2% to 16.4%), n=280 |
| `K4` | 70 | n/a | 40.0% (32.9% to 45.7%), n=70 | 40.0% (32.9% to 45.7%), n=70 |
| `K6` | 280 | n/a | 25.0% (21.3% to 28.6%), n=280 | 25.0% (21.3% to 28.6%), n=280 |
| `R1` | 1400 | 14.6% (12.3% to 16.8%), n=1400 | n/a | 80.4% (78.0% to 82.9%), n=1400 |

**Against the baselines**

| System | Leak rate | Over-redaction rate | Escalation rate | Detector recall |
|---|---|---|---|---|
| sever, rules over the full document context | 14.6% (12.3% to 16.8%), n=1400 | 27.3% (26.2% to 28.4%), n=3955 | 41.2% (40.1% to 42.2%), n=5355 | 91.7% (90.9% to 92.5%), n=5355 |
| blunt redact-all-PII | 8.1% (6.6% to 9.6%), n=1400 | 91.6% (90.7% to 92.5%), n=3955 | 0.0% (0.0% to 0.0%), n=5355 | 91.7% (90.9% to 92.5%), n=5355 |
| sentence-only, no document context | 14.5% (12.2% to 16.7%), n=1400 | 50.9% (49.0% to 52.9%), n=3955 | 58.7% (57.2% to 60.2%), n=5355 | 91.7% (90.9% to 92.5%), n=5355 |

**Where the leaks come from**

| System | Leaks | The detector never found the span | The decision was wrong |
|---|---:|---:|---:|
| sever, rules over the full document context | 205 | 113 | 92 |
| blunt redact-all-PII | 113 | 113 | 0 |
| sentence-only, no document context | 203 | 113 | 90 |

**PDF leak test**

| Redaction boxes applied | Boxes with recoverable text | Channels checked |
|---:|---:|---|
| 2588 | 0 | text layer only |

_OCR channel disabled for this run._

Intervals are 95 percent bootstrap percentile intervals resampled over documents,
not over spans, because spans within a document are not independent.
