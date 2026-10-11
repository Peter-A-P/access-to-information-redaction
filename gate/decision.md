<!-- Output of project 03's release gate at commit efcc1df, run on the files in this folder: uv run gate compare --spec spec.yaml --baseline rules-only.json --candidate rules-then-model.json --ledger ledger.jsonl. Do not hand-edit. -->

## Gate: BLOCK

Spec `hundreds-of-pages-redacted` (9daacaed91a87672).

Baseline `sever, rules only`, candidate `sever, rules then the model on the residual`.

| Suite | Paired items | Baseline | Candidate | Difference | Margin | Holm p | Verdict |
|---|---:|---|---|---|---:|---:|---|
| no_leak | 210 | 83.3% (78.1 to 88.1) | 66.7% (60.0 to 73.3) | -16.7% (-21.4 to -11.4) | -3% | 1.000 | block |
| k1_requester | 210 | 64.3% (57.6 to 71.0) | 71.9% (65.7 to 78.1) | +7.6% (+3.8 to +11.0) | -3% | 0.000 | pass |
| k3_public | 70 | 98.6% (95.7 to 100.0) | 100.0% (96.4 to 100.0) | +1.4% (-4.3 to +4.3) | -3% | not decided | warn |
| k6_not_personal | 175 | 60.0% (52.6 to 67.4) | 100.0% (98.6 to 100.0) | +40.0% (+32.6 to +46.9) | -3% | 0.000 | pass |

Difference is candidate minus baseline, paired by item, with its 95% bootstrap interval. A suite passes when the whole interval sits above the margin after Holm's adjustment across the decided suites; an under-powered suite warns and is not decided.

**Reasons**

- no_leak: cannot rule out a 3% drop: -16.7% (-21.4% to -11.4%) over 210 items, 35 worse and 0 better (p 1.000, Holm 1.000)
- under-powered, not decided: k3_public
