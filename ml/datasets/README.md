# Dataset Spec

Initial target: build supervised research datasets from existing SQLite tables
without changing runtime behavior.

## Sources

- `feature_snapshots`: intraday feature vectors.
- `labeled_setups`: forward-return and excursion labels.
- `daily_symbol_context`: deterministic premarket context.
- `daily_symbol_events`: symbol-level event context.
- `daily_symbol_predictions`: observe-only prediction outputs.
- `trades`: live signal decisions.
- `matched_trades`: realized closed-trade outcomes when available.

## Initial Label Targets

- `entry_quality_outcome`
- `max_favorable_excursion`
- `max_adverse_excursion`
- `time_to_profit`
- `time_to_drawdown`
- `profit_after_15m`
- `profit_after_30m`
- `profit_after_60m`
- `would_hit_stop`
- `would_hit_take_profit`
- `was_late_entry`
- `was_churn`
- `was_bad_fill`
- `was_correct_rejection`

First useful model target:

```text
Given the feature/context state at snapshot time, did the symbol move favorably
over the next 15 or 30 minutes?
```

Avoid using “should buy” as the first target. It mixes market outcome, current
policy, broker state, and risk controls into one noisy label.

Prefer fixed-horizon labels for training. Realized PnL labels are useful, but
they depend on the active exit logic and must carry `exit_policy_version` and
`position_manager_version`.

## Counterfactual Outcomes

Approved trades have observed outcomes. Rejected signals only become useful for
"should we have taken this?" if their forward price path is reconstructed.

Required rejected-signal labels:

- `return_5m`
- `return_15m`
- `return_30m`
- `return_60m`
- `return_eod`
- `max_favorable_60m`
- `max_adverse_60m`

Until those are present, supervised reports must say they are approved-trade
only and selection-biased.

## Leakage Rules

- No future prices or labels in feature columns.
- No fill outcomes in setup-prediction features.
- No same-row `labeled_setups` outputs as features.
- Daily context must be available at or before the snapshot date.
- Event context must use only events collected before the evaluated session.
- Every canonical row needs `feature_available_at`, `feature_generated_at`,
  `feature_age_seconds`, `source`, `is_stale`, and `staleness_reason`.
- Decision-time rows must not use anything learned after
  `order_decision_time`.
- Trend/momentum reports generated after the fact are evaluation evidence, not
  decision-time features.
- Historical replay must not read the current `market_context.json`; it needs a
  point-in-time market-context archive or decision snapshot.
- Manual overrides and symbol overrides must be timestamped as training
  confounders or affected rows must be excluded.
- Symbol-universe changes must be versioned. Historical datasets should not
  treat newly added symbols as if they were always eligible.

## Post-QA Symbol Candidates

Candidate additions to review after Tuesday QA:

- AMZN
- JPM
- TSM
- PYPL
- SOFI
- PFE
- CMCSA
- T
- VZ
- F
- HBAN
- KEY
- KHC

These are not part of Tuesday's runtime change plan. If approved later, they
need a new symbol-universe version and fresh data coverage before symbol-level
ML claims.

## Validation Rules

- Use purged walk-forward validation with embargo periods for financial
  time-series samples.
- Track class distribution for every target.
- Report precision at threshold, winner recall, false-reject rate for winners,
  expected value after friction, balanced accuracy, and class distribution.
- Compare against the null no-ML current bot and the current Claude plus
  deterministic-gate policy, not only random baselines.

## Dataset Manifest

Every exported dataset should include a manifest with:

- `dataset_id`
- `created_at`
- `source_db_path`
- `source_db_hash`
- `query_version`
- `label_version`
- `feature_version`
- `row_count`
- `symbol_count`
- `date_range`
- `excluded_rows_reason_counts`
- `git_sha`
- `override_files`
- `override_state_hash`
- `override_tracking_status`

Until full timestamped override history exists, manifests must at least hash
the current `manual_strategy_overrides.json` and `symbol_overrides.json` state
and mark the tracking status. Rows spanning unknown active override periods
should be excluded or flagged before training.

Generate the current scaffold manifest with:

```bash
python3 -m ml_platform.cli dataset-manifest --start-date 2026-05-20 --end-date 2026-05-26
```

## Minimum Sample Guidelines

- Fewer than 500 labeled snapshots: reports only, no model training claims.
- 500-2,000 labeled snapshots: exploratory baselines only.
- 2,000+ labeled snapshots: begin walk-forward validation.
- Matched-trade models need separate thresholds because trades are much sparser
than snapshots.

## Profiling

Use the read-only platform CLI to summarize whether enough data exists:

```bash
python3 -m ml_platform.cli profile-dataset --start-date 2026-05-20 --end-date 2026-05-26
```

Brain/intelligence feature export:

```bash
python3 -m ml_platform.cli export-brain-features --date 2026-05-26 --output /tmp/brain_features.csv
```
