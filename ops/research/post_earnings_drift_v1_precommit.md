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
2. The labeled event sample meets the preselected minimum row threshold.
3. At least one earnings feature clears decile lift, blocked permutation null,
   and family-wise max-statistic null.
4. The result is directionally coherent across the configured regime split.
5. Expected value is positive after spread, slippage, and whole-share
   deployment constraints.

## Fail Condition

The thesis fails if any of these are true:

- The event data cannot be represented point-in-time.
- The sample is too small to run the detector.
- The detector result is within noise.
- Family-wise correction removes the apparent edge.
- Net expected value is non-positive after costs.
- Whole-share deployment makes the signal uneconomic at the account size.

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
