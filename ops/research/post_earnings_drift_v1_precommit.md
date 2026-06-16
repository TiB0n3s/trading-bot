# Post-Earnings Drift V1 Pre-Commitment

Created: 2026-06-16

## Hypothesis

Post-earnings drift carries positive expected value over a 5-session holding
horizon after point-in-time validation and actual account friction.

This is a research hypothesis only. It grants no live or paper auto-buy
authority.

## Fixed Test

- Thesis: post-earnings drift after reported earnings events.
- Horizon: 5 trading sessions after the event is knowable.
- Entry anchor: first available 1-minute bar at or after `available_at`.
- Exit anchor: close of the fifth labeled session after entry.
- Feature source: `external_signal_features` rows with
  `feature_family=earnings`.
- Price/label source: `bar_pattern_features`.
- Required event fields: `symbol`, `earnings_ts`, `available_at`, `source`.
- Useful but optional fields: `report_timing`, `eps_surprise_pct`,
  `revenue_surprise_pct`, `guidance_surprise`, `consensus_source`,
  `reported_eps`, `consensus_eps`, `reported_revenue`, `consensus_revenue`.
- Initial cost assumptions: `spread_pct=0.05`, `slippage_pct=0.03`,
  `slippage_turns=2.0`, plus whole-share deployment at the actual account
  equity supplied to the scan.

## Pass Condition

The thesis passes only if all of these are true:

1. Point-in-time integrity is acceptable: `available_at` represents when the
   event data was knowable, not when it was later collected. The manual audit
   in `ops/research/post_earnings_drift_v1_pit_audit.md` must be complete and
   pass or be explicitly marked provisional before scan results are interpreted.
2. The labeled event sample has at least `30` rows.
3. At least one earnings feature has absolute decile lift of at least `8.0`
   percentage points.
4. That same feature has blocked-null p-value `<= 0.05`.
5. That same feature has family-wise max-statistic p-value `<= 0.05`.
6. The result is directionally coherent across the configured regime split:
   same lift direction in any regime bucket with at least `30` rows, or no
   qualifying regime bucket.
7. Aggregate expected value is at least `+0.25%` after spread, slippage, and
   commission assumptions.
8. Whole-share deployment is feasible: at least `1` share deployable at the
   reference price and no `cannot_deploy_whole_share` verdict.
9. If per-symbol costs are available, the passing feature must also remain
   positive-EV after symbol-specific spread/slippage overrides; otherwise the
   result is provisional, not a pass.

## Fail Condition

The thesis fails if any of these are true:

- The event data cannot be represented point-in-time.
- Labeled sample size is `< 30`.
- Absolute decile lift is `< 8.0` percentage points.
- Blocked-null p-value is `> 0.05`.
- Family-wise p-value is `> 0.05`.
- Net expected value after costs is `< +0.25%`.
- Whole-share deployment makes the signal uneconomic at the account size.
- Per-symbol cost review, when available, drops the candidate below positive
  net expected value.

## Actions

- Pass: reduce the survivor to a simple rule/model and run staged paper-only
  observation. No live authority.
- Fail: archive the result and move to the next ranked hypothesis without
  tuning this thesis into a new one.

## Ranked Hypothesis Queue

1. Post-earnings drift.
2. Options positioning / implied volatility / skew / gamma-context effect.
3. Short-interest or crowded-positioning effect.
4. ETF/sector flow or rebalance effect.

## Stopping Rule

If the ranked structural hypotheses above fail point-in-time validation and
cost-aware expected-value review, conclude the accessible edge set is not
currently viable for the account size and stop trying to make the intraday
OHLCV stack profitable.
