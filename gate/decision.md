<!-- Output of project 03's release gate at commit efcc1df, run on the files in this folder: uv run gate compare --spec spec.yaml --baseline rules-only.json --candidate rules-then-model.json --ledger ledger.jsonl. Do not hand-edit. -->

## Gate: PASS

Spec `hundreds-of-pages-redacted` (9daacaed91a87672).

Baseline `sever, rules only`, candidate `sever, rules then the model on the residual`.

| Suite | Paired items | Baseline | Candidate | Difference | Margin | Holm p | Verdict |
|---|---:|---|---|---|---:|---:|---|
| no_leak | 210 | 91.0% (86.7 to 94.8) | 91.0% (86.7 to 94.8) | +0.0% (-1.4 to +1.4) | -3% | 0.002 | pass |
| k1_requester | 210 | 64.8% (58.1 to 71.4) | 93.8% (90.5 to 96.7) | +29.0% (+22.9 to +34.8) | -3% | 0.000 | pass |
| k3_public | 70 | 98.6% (95.7 to 100.0) | 100.0% (96.4 to 100.0) | +1.4% (-4.3 to +4.3) | -3% | not decided | warn |
| k6_not_personal | 175 | 42.3% (35.4 to 49.7) | 100.0% (98.6 to 100.0) | +57.7% (+50.3 to +64.6) | -3% | not decided | warn |

Difference is candidate minus baseline, paired by item, with its 95% bootstrap interval. A suite passes when the whole interval sits above the margin after Holm's adjustment across the decided suites; an under-powered suite warns and is not decided.

**Reasons**

- pass: 2 of 4 suites decided, none inferior
- under-powered, not decided: k3_public, k6_not_personal
