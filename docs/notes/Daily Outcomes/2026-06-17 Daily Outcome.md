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
data_integrity: contended
dropped_audit_writes: unknown
frozen_logic_commit: 8230be2fe37396e0b27c11bbd0e4b5c6b47c860e
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
- `strategy_memory_avoid_weak_evidence` was the top blocker by would-be-strong count: 167, ahead of `setup_avoid` at 148 and about 2.5x plain `strategy_memory_avoid` at 67.
- TSM and ASML were the main weak-evidence cold-start names at the top of the missed-strong list.
- TSM hit max score four consecutive times, which raises the priority of the controlled-exploration question, but this remains one session and should not change hard blocks by itself.
- OKTA remained the main plain avoid-memory name.
- After outcome backfill, the strategy-memory hard-block review moved from no forward grounding to `sample_with_outcome=30` out of `31` displayed rows.
- Keep the denominator straight: `452` is the counterfactual would-be-strong universe; `30` is the current outcomed evidence sample from the review display set. Today's high-score blocker verdicts still should not be changed from this session alone.
- The review is capped/sample-oriented: `candidate_rows=1000` and `strategy_memory_rows=1000` come from `auto_buy_candidates`, while only `31` selected rows were enriched from `candidate_universe`.
- The one missing displayed outcome was `AMD` at `2026-06-17T11:40:30.348149-04:00`; `auto_buy_candidates` has that row, while `candidate_universe` has nearby AMD rows at `11:36:10` and `11:44:12` but no exact `11:40:30` row. This is an enrichment/key absence rather than a no-forward-bars case.
- Targeted coverage check for the named symbols was healthy: `TSM 79/79`, `ASML 86/86`, and `OKTA 74/74` candidate-universe rows had forward outcomes.

## Net/Excess Machinery Check
- Scope: full outcomed `candidate_universe` set for 2026-06-17, not the 31-row strategy-memory review display sample.
- Coverage: `5,756` outcomed candidate rows across `76` symbols.
- Effective-n collapse: 60-minute non-overlapping symbol episodes produced `460` episodes; average rows per episode was `12.51`, median `13`, max `17`.
- Spread guard: treat captured spread as usable for net-cost subtraction only when `0 <= spread_pct <= 2.0`. Wider values are excluded from net fields, not capped. This guarded out `2,731 / 5,756` rows, confirming the raw spread field was dominating the unguarded net result.
- Benchmark coverage: SPY and QQQ same-window local bars were available; SOXX 1-minute bars were pulled for semiconductor excess.
- Row-level score cut `score >= 29`: `11` rows, `3` symbols, average `return_60m=0.312%`, average guarded `net_return_60m=-0.647%`, average guarded `net_excess_spy_60m=-0.478%`, average guarded `net_excess_soxx_60m=-0.763%`; `4` rows were spread-guarded out for net fields.
- Episode-level score cut `score >= 29`: `4` episodes, `3` symbols, average `return_60m=-0.228%`, hit rate `25.0%`, average guarded `net_return_60m=-0.981%`, average guarded `net_excess_spy_60m=-0.914%`, average guarded `net_excess_soxx_60m=-0.663%`; `29` underlying rows were spread-guarded.
- Semiconductor-only episode cut `score >= 29`: `2` episodes, `2` symbols, average `return_60m=-0.185%`, hit rate `0.0%`, average guarded `net_return_60m=-0.981%`, average guarded `net_excess_soxx_60m=-0.663%`.
- Concentration for the top episode cut: TSM, ASML, and two OKTA episodes. Conclusion: the pipeline works and the spread-quality issue is quantified, but this is still one-day machinery validation, not an edge readout. No edge shown; blocks do not look costly; a score of `30` is not tradeable by itself.

## Operational Incident
See [[2026-06-17 Auto-Buy Lock Contention]].

Key operational read:
- Candidate scoring was healthy.
- SQLite write contention caused audit persistence failures/timeouts.
- Fixes were committed to fail open on locked audit writes and shorten audit-write lock waits.
- Production validation rolls to the next market-hours run after `8230be2`.

### Data Integrity
- `data_integrity: contended`. Lock contention occurred and fail-open audit writes were active under `8230be2`, but this run predates audit-write-loss instrumentation, so the dropped-write count is unrecoverable: `dropped_audit_writes: unknown`.
- This means the headline counts (`auto_buy_snapshots=5869`, `auto_buy_hard_blocked=5691`, `would_be_strong=452`, `would_be_watch=519`) cannot be distinguished from a lossy capture. Treat them as a possible undercount, not a confirmed total.
- Going forward, `python3 ops_check.py audit-write-integrity YYYY-MM-DD` reconciles rows-written against durably-recorded dropped writes and emits the `data_integrity` / `dropped_audit_writes` / `frozen_logic_commit` frontmatter for this note. A day with instrumentation present classifies as `clean`, `contended`, `lossy`, or `intrasession-logic-change`.

## Lessons
- Do not interpret a post-build timeout as scorer slowness without checking `build_candidates`.
- Separate final candidate decisions from counterfactual hard-block audit counts.
- `strategy_memory_avoid_weak_evidence` should be treated as an exploration/cold-start issue, not as proven negative expectancy.
- Best-effort audit persistence needs bounded lock waits and should not terminate candidate discovery.

## Follow-Ups
- [ ] Watch the next market-hours auto-buy run after `8230be2`.
- [x] Run candidate outcome backfill for 2026-06-17: `python3 ops_check.py candidate-outcome-backfill 2026-06-17`
- [x] Re-run strategy-memory hard-block review once forward outcomes are available.
  - Result: `candidate_rows=1000`, `strategy_memory_rows=1000`, `sample_rows_enriched=31`, `sample_with_outcome=30`, `sample_missing_outcome=1`, `weak_evidence_rows=766`.
- [x] Review TSM, ASML, and OKTA forward outcomes before changing any hard block.
  - Result: raw forward returns were extracted for the top high-score rows.
- [x] Run full outcomed-set net/excess machinery check with episode collapse.
  - Result: `5,756` outcomed rows collapsed to `460` non-overlapping 60-minute symbol episodes; spread guard removed raw spread distortion; SPY/QQQ/SOXX excess computed where applicable.
- [ ] Continue tracking SQLite writer overlap from `run_label_features` and `session_momentum`.
  - Current command: `python3 scripts/db_workload_report.py --writer-overlap-date YYYY-MM-DD --writer-overlap-duration-threshold-sec 60`.
  - 2026-06-17 baseline: `auto_buy_runs=181`, `watched_runs=32`, `overlap_count=124`, `long_running_overlap_count=124`.
- [x] Add DB workload report flagging long-running writer overlap with auto-buy windows.
  - Result: `scripts/db_workload_report.py` now reads the `job_runs` ledger and flags long `run_label_features` / `session_momentum` overlaps against `auto_buy_manager`.
- [ ] Consider batching auto-buy audit writes into one transaction.
- [ ] Consider moving best-effort audit/event streams to a separate SQLite DB or append-only queue.

## Related
- [[2026-06-17 Auto-Buy Lock Contention]]
- [[strategy_memory_avoid]]
- [[strategy_memory_avoid_weak_evidence]]
- [[sqlite_lock_contention]]
