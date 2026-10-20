<!-- Output of project 03's release gate at commit efcc1df, run on the files in this folder: uv run gate compare --spec spec.yaml --baseline rules-only.json --candidate rules-then-model.json --ledger ledger.jsonl. Do not hand-edit. -->

## Gate: PASS

Spec `hundreds-of-pages-redacted` (9daacaed91a87672).

Baseline `sever, rules only`, candidate `sever, rules then the model on the residual`.

| Suite | Paired items | Baseline | Candidate | Difference | Margin | Holm p | Verdict |
|---|---:|---|---|---|---:|---:|---|
| no_leak | 210 | 83.3% (78.1 to 88.1) | 82.9% (77.1 to 87.6) | -0.5% (-1.4 to +1.4) | -3% | 0.000 | pass |
| k1_requester | 210 | 64.3% (57.6 to 71.0) | 86.2% (81.4 to 90.5) | +21.9% (+16.2 to +27.1) | -3% | 0.000 | pass |
| k3_public | 70 | 98.6% (95.7 to 100.0) | 98.6% (95.7 to 100.0) | +0.0% (-4.3 to +4.3) | -3% | not decided | warn |
| k6_not_personal | 175 | 60.0% (52.6 to 67.4) | 73.1% (66.3 to 79.4) | +13.1% (+8.0 to +17.7) | -3% | 0.000 | pass |

Difference is candidate minus baseline, paired by item, with its 95% bootstrap interval. A suite passes when the whole interval sits above the margin after Holm's adjustment across the decided suites; an under-powered suite warns and is not decided.

**Reasons**

- pass: 3 of 4 suites decided, none inferior
- under-powered, not decided: k3_public
