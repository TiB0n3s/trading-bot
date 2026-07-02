# Strategy Memory Weak-Evidence Demotion Replay - 2026-07-01

## Scope

Diagnostic-only replay for treating `strategy_memory_avoid_weak_evidence` as
insufficient evidence rather than a hard block. This does not change live
authority, paper authority, sizing, broker behavior, or gate behavior.

Command:

```bash
venv/bin/python scripts/strategy_memory_weak_evidence_demotion_report.py \
  --start-date 2026-06-21 \
  --end-date 2026-07-01
```

Audit rows loaded from `trades.db`: 5,378.

Date coverage:

| Date | Rows |
| --- | ---: |
| 2026-06-21 | 0 |
| 2026-06-22 | 928 |
| 2026-06-23 | 1,000 |
| 2026-06-24 | 894 |
| 2026-06-25 | 428 |
| 2026-06-26 | 611 |
| 2026-06-27 | 0 |
| 2026-06-28 | 0 |
| 2026-06-29 | 344 |
| 2026-06-30 | 537 |
| 2026-07-01 | 636 |

## Counterfactual Rule

Eligible rows:

- `hard_block_reason` contains `strategy_memory_avoid_weak_evidence`.
- Explicit weak-evidence reason is logged as `no symbol memory` or
  `sample too small`.
- No other setup, tape, ML, or chase hard blocker is present.
- Score is at least 10.0, covering the strong score slice (`score >= 13`) and
  near-threshold variants.

Counterfactual action:

- Demote the hard block into `watch_only`.
- Cap score to 12.99, below the strong-buy threshold of 13.0.
- Keep remaining context blockers such as `bias_avoid` as blockers; those rows
  are not counted as true unlocks.

## Result

| Metric | Value |
| --- | ---: |
| Eligible rows | 137 |
| Would-watch rows after demotion | 131 |
| Remaining context-block rows | 6 |
| Ineligible rows with other setup/tape/ML/chase blockers | 1,913 |
| Known would-watch outcomes | 131 |
| Avg 60m return, would-watch | +0.0174% |
| Median 60m return, would-watch | -0.1274% |
| EV-bar profitable rows (`return_60m >= 0.25%`) | 42 |
| Positive rows | 55 |
| Negative rows | 73 |
| Below EV bar rows | 89 |
| No-hard-block baseline avg 60m return | +0.1982% |
| EV delta vs no-hard-block baseline | -0.1808% |

Reason split:

| Weak reason | Rows | Avg 60m return | Median 60m return | EV-bar profitable | Negative |
| --- | ---: | ---: | ---: | ---: | ---: |
| `no_symbol_memory` | 100 | -0.0227% | -0.1389% | 34 | 56 |
| `sample_too_small` | 31 | +0.1466% | -0.0341% | 8 | 17 |

Score-band split:

| Score band | Rows | Avg 60m return | Median 60m return | EV-bar profitable | Negative |
| --- | ---: | ---: | ---: | ---: | ---: |
| `near_10_to_10_99` | 13 | +0.5160% | -0.2433% | 4 | 7 |
| `near_11_to_11_99` | 14 | -0.4370% | -0.3452% | 4 | 8 |
| `near_12_to_12_99` | 14 | -0.3343% | -0.4693% | 4 | 10 |
| `strong_score_ge_13` | 90 | +0.0707% | -0.0435% | 30 | 48 |

## Conclusion

Do not promote this demotion to a live soft-block variant from this window.

The counterfactual does unlock profitable rows, but it fails the net-EV guard:
average 60-minute return is below the no-hard-block baseline by 0.1808
percentage points, median return remains negative, and negative rows outnumber
positive rows. The hard block should stand until a narrower rule survives the
same full-window replay without EV regression.
