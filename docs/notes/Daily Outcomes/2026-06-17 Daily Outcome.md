---
date: 2026-06-17
type: daily-outcome
mode: observe-only / candidate discovery
signals_total: 0
signals_approved: 0
signals_rejected: 0
live_trade_rows: 0
live_buy_rows: 0
orders_submitted: 0
realized_pnl: none
auto_buy_snapshots: 5869
auto_buy_hard_blocked: 5691
would_be_strong: 452
would_be_watch: 519
primary_incident: "[[2026-06-17 Auto-Buy Lock Contention]]"
---

# Daily Outcome - 2026-06-17

## Summary
- No external/actionable signals were received.
- No live execution rows, BUY rows, submitted orders, or matched buy/sell P&L.
- Auto-buy operated as candidate discovery / observe-only.
- Main operational issue was SQLite write-lock contention in post-build audit persistence.
- Candidate scoring itself was healthy by the end of the day; post-build audit writes were the failure point.

## Signal And Execution Counts
| Metric | Count |
| --- | ---: |
| Signals received | 0 |
| Signals approved | 0 |
| Signals rejected | 0 |
| Actionable signals | 0 |
| Live trade rows | 0 |
| Live BUY rows | 0 |
| Orders submitted | 0 |
| Matched realized P&L rows | 0 |

## Auto-Buy Candidate Outcome
| Metric | Count |
| --- | ---: |
| Saved auto-buy snapshots | 5,869 |
| Hard-blocked snapshots | 5,691 |
| Counterfactual would-be strong | 452 |
| Counterfactual would-be watch | 519 |
| Submitted auto-buy orders | 0 |

Partial auto-buy health output:

| Decision | Rows | Avg Score | Max Score |
| --- | ---: | ---: | ---: |
| `skip` | 5,780 | -5.77 | 30.00 |
| `strong_buy_candidate` | 84 | 19.27 | 30.00 |
| `watch` | 5 | 10.40 | 12.00 |

Note: `would_be_strong` is counterfactual after removing hard blocks. `strong_buy_candidate` is the saved final decision distribution.

## Hard-Block Audit
| Blocker | Rows | Would Strong | Would Watch | Avg Score | Max Score |
| --- | ---: | ---: | ---: | ---: | ---: |
| `strategy_memory_avoid_weak_evidence` | 827 | 167 | 81 | 0.4 | 30.0 |
| `setup_avoid` | 2,320 | 148 | 191 | -4.3 | 23.0 |
| `strategy_memory_avoid` | 234 | 67 | 50 | 5.0 | 30.0 |
| `extreme_mature_chase` | 68 | 32 | 17 | 10.1 | 25.0 |
| `layered_ml_veto` | 258 | 20 | 63 | 4.6 | 21.0 |
| `unclassified_extended_vwap` | 141 | 11 | 48 | -0.1 | 15.0 |
| `bias_avoid` | 1,485 | 4 | 25 | -15.2 | 16.0 |
| `intraday_pattern_feedback` | 123 | 2 | 32 | -2.2 | 22.0 |
| `15m_falling` | 96 | 1 | 12 | -1.1 | 13.0 |
| `negative_session` | 127 | 0 | 0 | -10.4 | 2.0 |

## Top Missed Strong Candidates
| Time ET | Symbol | Score | Blocker | Final |
| --- | --- | ---: | --- | --- |
| 09:46:47 | TSM | 30.0 | `strategy_memory_avoid_weak_evidence` | `strong_buy_candidate` |
| 09:50:43 | TSM | 30.0 | `strategy_memory_avoid_weak_evidence` | `strong_buy_candidate` |
| 09:54:44 | TSM | 30.0 | `strategy_memory_avoid_weak_evidence` | `strong_buy_candidate` |
| 09:58:35 | TSM | 30.0 | `strategy_memory_avoid_weak_evidence` | `strong_buy_candidate` |
| 11:50:12 | ASML | 30.0 | `strategy_memory_avoid_weak_evidence` | `strong_buy_candidate` |
| 12:18:12 | OKTA | 30.0 | `strategy_memory_avoid` | `skip` |
| 11:46:08 | ASML | 29.0 | `strategy_memory_avoid_weak_evidence` | `strong_buy_candidate` |
| 11:50:12 | OKTA | 29.0 | `strategy_memory_avoid` | `skip` |

## Strategy-Memory Read
- Strategy-memory remained the most important high-score blocker family.
- `strategy_memory_avoid_weak_evidence` blocked more would-be strong candidates than plain `strategy_memory_avoid`.
- TSM and ASML were the main weak-evidence cold-start names at the top of the missed-strong list.
- OKTA remained the main plain avoid-memory name.
- The strategy-memory hard-block review had `sample_with_outcome=0`, so today's high-score blocker verdicts should not be changed from this session alone.

## Operational Incident
See [[2026-06-17 Auto-Buy Lock Contention]].

Key operational read:
- Candidate scoring was healthy.
- SQLite write contention caused audit persistence failures/timeouts.
- Fixes were committed to fail open on locked audit writes and shorten audit-write lock waits.
- Production validation rolls to the next market-hours run after `8230be2`.

## Lessons
- Do not interpret a post-build timeout as scorer slowness without checking `build_candidates`.
- Separate final candidate decisions from counterfactual hard-block audit counts.
- `strategy_memory_avoid_weak_evidence` should be treated as an exploration/cold-start issue, not as proven negative expectancy.
- Best-effort audit persistence needs bounded lock waits and should not terminate candidate discovery.

## Follow-Ups
- [x] Pull signal counts and hard-block audit from `auto_buy.log` and `trades.db` to complete this log.
- [ ] Watch the next market-hours auto-buy run after `8230be2`: expected no crash on locked audit writes, no 5-second-per-row waits.
- [ ] Add DB workload report to flag long-running writer overlap with auto-buy windows.
- [ ] Run candidate outcome backfill for `2026-06-17`.
  - Command: `python3 ops_check.py candidate-outcome-backfill 2026-06-17`
- [ ] Re-run strategy-memory hard-block review once forward outcomes are available.
- [ ] Review TSM, ASML, and OKTA forward outcomes before changing any hard block.

## Related
- [[2026-06-17 Auto-Buy Lock Contention]]
- [[strategy_memory]]
- [[strategy_memory_avoid]]
- [[strategy_memory_avoid_weak_evidence]]
- [[auto_buy_manager]]
- [[candidate_universe]]
- [[SQLite lock contention]]
- [[TSM]]
- [[ASML]]
- [[OKTA]]
