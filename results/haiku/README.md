# Claude Haiku 5.5, as published until 2026-10-21

These are the tables the README and the website published while Claude Haiku 5.5 was the
model on the residual, at its confidence threshold of 0.90. They were written by the
measurement commands at commit `0341b5c` and are kept as they were, not regenerated: the
published model is now Jev 1.14 (PLAN.md 12.52), and the tables one level up are its.

| File here | Written by | Answers replayed from |
|---|---|---|
| `results.md`, `results.json` | `sever report --model` | `results/model-answers-haiku.jsonl` |
| `thresholds.md` | `sever eval-thresholds` | `results/model-answers-haiku.jsonl` |
| `traps.md` | `sever eval-traps --model` | `results/model-answers-traps-haiku.jsonl` |
| `releases.md` | `sever eval-releases --model` | `results/model-answers-releases-haiku.jsonl` |
| `releases-heldout.md` | `sever eval-releases --model --held-out` | `results/model-answers-releases-haiku.jsonl` |
| `cost.json` | `sever cost --model-name anthropic/claude-haiku-5-5 --runs sever-haiku55-210-r2`, 2026-10-21 | `results/model-answers-haiku.jsonl` |

To reproduce one, check out `0341b5c` and run its command with `--replay-only`, pointing
`--answer-cache` at the file in the last column (they were named without `-haiku` then).
`cost.json` is the one file written since, from the same ledger run, so that it records the
mean time a call took (1.8 seconds) beside the cost per page (US$0.00644) for the website's
comparison with Jev.
