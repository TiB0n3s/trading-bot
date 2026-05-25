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

- `ret_fwd_5m`
- `ret_fwd_15m`
- `ret_fwd_30m`
- `max_up_15m`
- `max_down_15m`
- `outcome_label`

First useful model target:

```text
Given the feature/context state at snapshot time, did the symbol move favorably
over the next 15 or 30 minutes?
```

Avoid using “should buy” as the first target. It mixes market outcome, current
policy, broker state, and risk controls into one noisy label.

## Leakage Rules

- No future prices or labels in feature columns.
- No fill outcomes in setup-prediction features.
- No same-row `labeled_setups` outputs as features.
- Daily context must be available at or before the snapshot date.
- Event context must use only events collected before the evaluated session.

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
