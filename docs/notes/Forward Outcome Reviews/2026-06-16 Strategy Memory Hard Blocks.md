# Forward Outcome Review - 2026-06-16 Strategy Memory Hard Blocks

## Source
- Daily summary surfaced OKTA, PYPL, VZ, and ADSK as high-score hard-blocked candidates.
- Candidate rows came from `candidate_universe` and `auto_buy_candidates` in `trades.db`.
- Timestamps are timezone-aware Eastern strings, for example `2026-06-16T15:04:06.110388-04:00`.

## Pre-Commit
- Primary outcome: `return_60m`.
- Secondary outcomes: `max_favorable_60m` and `max_adverse_60m`.
- Near-close fallback: `return_eod` only when `return_60m` is missing because the row lacks a full 60-minute window.
- Cost treatment here: spread-only net using captured bid/ask against quote-mid reference price. Slippage is not included, so net verdicts are provisional.
- Do not use synthesized `forward_return_pct` for this review because `return_60m or return_30m or return_eod` treats a genuine `0.0` return as missing.

## Avoid-Memory Cohort
Question: did learned avoidance predict negative forward movement, or is the memory stale?

| Time ET | Symbol | Score | Component | Gross Outcome | Spread Cost | Spread-Only Net Read |
| --- | --- | ---: | --- | --- | ---: | --- |
| 14:04:06 | PYPL | 22 | bar-pattern memory: `volume_confirmed_breakout` | `return_60m` +0.253%, MFE +0.507%, MAE -0.115% | 0.046% | Block likely cost upside after spread. |
| 14:40:09 | PYPL | 22 | setup avoid + bar-pattern memory: `volume_confirmed_breakout` | `return_60m` +0.448%, MFE +0.575%, MAE -0.046% | 0.046% | Block likely cost upside after spread. |
| 14:58:08 | PYPL | 22 | bar-pattern memory: `volume_confirmed_breakout` | `return_60m` +0.092%, MFE +0.264%, MAE -0.264% | 0.023% | Small positive after spread, but path was mixed. |
| 15:04:06 | OKTA | 26 | bar-pattern memory: `bearish_divergence` | near-close partial; EOD -1.030%, MFE +0.132%, MAE -1.179% | 0.162% | Block likely saved downside. |
| 15:06:10 | OKTA | 24 | bar-pattern memory: `bearish_divergence` | near-close partial; EOD -1.072%, MFE +0.089%, MAE -1.221% | 0.247% | Block likely saved downside. |
| 15:10:08 | PYPL | 25 | bar-pattern memory: `volume_confirmed_breakout` | near-close partial; EOD -0.160%, MFE +0.011%, MAE -0.412% | 0.023% | Block likely saved downside. |
| 15:30:06 | OKTA | 26 | bar-pattern memory: `constructive_continuation` | near-close partial; EOD +0.298%, MFE +1.475%, MAE 0.000% | 10.367% | Captured spread was too wide to trust as executable upside. |
| 15:34:06 | OKTA | 25 | bar-pattern memory: `constructive_continuation` | near-close partial; EOD +2.174%, MFE +3.242%, MAE 0.000% | 6.818% | Gross move was favorable, but quoted spread overwhelms it. Verify quote quality. |

## Avoid-Memory Read
- PYPL is mixed: earlier rows suggest the block cost tradable upside, while the 15:10 row supports the block.
- OKTA is also split: earlier rows support the block, later rows had favorable gross movement but unusably wide captured spreads.
- The fired sub-component is not plain symbol memory. OKTA and PYPL symbol memory are neutral; the hard block was tightened to `learned_min=70` by bar-pattern memory.
- Do not conclude "avoid OKTA" or "avoid PYPL" from this sample. The hypothesis is narrower: whether specific bar-pattern memory states should hard-block high-score candidates.

## Weak-Evidence Cohort
Question: is the gate preventing cold-start learning?

| Time ET | Symbol | Score | Reason | Gross Outcome | Spread Cost | Spread-Only Net Read |
| --- | --- | ---: | --- | --- | ---: | --- |
| 15:56:08 | VZ | 25 | no symbol memory | near-close partial; EOD +0.011%, MFE +0.011%, MAE -0.021% | 0.021% | Flat after spread; not enough to validate a hard exclusion. |
| 15:56:08 | ADSK | 21 | sample too small: 2 closed trades | near-close partial; EOD -0.141%, MFE 0.000%, MAE -0.141% | 0.084% | Block avoided mild downside, but this remains a cold-start case. |

## Weak-Evidence Read
- VZ and ADSK should not be scored as learned avoid calls.
- These are exploration-starvation candidates: sparse bot history, not a market-quality verdict.
- Better fix space is paper probes or size-limited exploration, with explicit caps, rather than permanent exclusion.

## Lessons
- Split `strategy_memory_avoid` from `strategy_memory_avoid_weak_evidence`; they answer different questions.
- Surface the strategy-memory sub-component before attributing a block to a ticker.
- Use `return_60m` directly for primary review; do not use synthesized `forward_return_pct`.
- Near-close rows need explicit partial labeling because 60-minute outcomes are unavailable.
- Captured spreads can dominate the verdict. OKTA's late rows require quote-quality review before treating gross upside as missed EV.

## Full-Set Machinery Check
- Candidate outcome backfill for 2026-06-16 completed with `rows=7600`, `skipped_existing=7501`, `updated=99`, `no_bars=99`, and coverage unchanged at `7501 / 7600` (`98.7%`).
- Spread capture existed for this day: all `7,501` outcomed `candidate_universe` rows had raw spread fields.
- Spread-quality issue was already present: using the same `0 <= spread_pct <= 2.0` guard excluded `3,459 / 7,501` rows from net-cost subtraction.
- Full outcomed set: `7,501` rows across `76` symbols collapsed into `532` non-overlapping 60-minute symbol episodes; average rows per episode was `14.10`, median `16`, max `17`.
- Benchmark coverage: SPY and QQQ same-window local bars were available; SOXX 1-minute bars were pulled for semiconductor excess.
- There were no `score >= 29` episodes on 2026-06-16, so the 6/17 high-score episode cut has no direct same-cut comparison.
- Episode-level `score >= 25`: `6` episodes, `6` symbols, hit rate `40.0%`, average `return_60m=-0.869%`, guarded `net_return_60m=-0.149%`, guarded `net_excess_spy_60m=0.025%`, guarded `net_excess_soxx_60m=0.847%`; `45` underlying rows were spread-guarded.
- Semiconductor-only episode `score >= 20`: `1` episode, `1` symbol, hit rate `0.0%`, average `return_60m=-3.880%`, guarded `net_return_60m=-3.951%`, guarded `net_excess_soxx_60m=-2.562%`.
- Discipline: this is one-day data-quality and drift validation, not edge evidence. A bad read is consistent with the no-edge prior; a good read would still be one independent day in one regime.

## Follow-Ups
- [x] Add a report that decomposes `strategy_memory` hard blocks into symbol, context, and bar-pattern contributors.
  - Command: `python3 ops_check.py strategy-memory-hard-blocks 2026-06-16 --samples 20`
- [x] Run 2026-06-16 candidate outcome backfill and guarded full-set net/excess machinery check.
- [x] Add full-day forward-outcome tracking for all hard-blocked candidates so the next audit closes the loop automatically.
  - Command: `python3 ops_check.py strategy-memory-hard-blocks YYYY-MM-DD --full-day`
  - 2026-06-16 smoke result: `full_day_rows_enriched=1177`, `full_day_with_outcome=1078`, `full_day_missing_outcome=99`, `full_day_missing_join=0`.
- [x] Add or locate a per-symbol slippage model; current net review only subtracts captured spread.
  - Located `ops/model_promotion_evidence/cost_slippage_exit_analysis.json`, but it is evidence-only and not a per-symbol slippage model. The report now prints this distinction.
- [ ] Consider paper or size-limited probes for `strategy_memory_avoid_weak_evidence` rows.
  - The report surfaces weak-evidence probe candidates from the full-day reviewed set; actual paper/size-limited authority remains a separate approval decision.
- [ ] Re-run this review over multiple sessions before changing any hard block.

## Related
- [[strategy_memory]]
- [[strategy_memory_avoid]]
- [[strategy_memory_avoid_weak_evidence]]
- [[OKTA]]
- [[PYPL]]
- [[VZ]]
- [[ADSK]]
