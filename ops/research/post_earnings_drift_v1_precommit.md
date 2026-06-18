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
- Timestamp contract: event and availability timestamps must be canonical UTC
  strings in `YYYY-MM-DDTHH:MM:SSZ` format. Session labels are derived in
  `America/New_York` market time.
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
   percentage points. (Strengthened by Amendment A1: the decile lift must be
   computed on at least `decile_min_rows` rows, and the bootstrap interval — not
   just the point estimate — must clear the `8.0`pp bar.)
4. That same feature has blocked-null p-value `<= 0.05`.
5. That same feature has family-wise max-statistic p-value `<= 0.05`.
6. The result is directionally coherent across the configured regime split:
   same lift direction in any regime bucket with at least `30` rows, or no
   qualifying regime bucket. (Strengthened by Amendment A1: a regime bucket
   qualifies only with at least `regime_min_rows` rows, and its direction must be
   bootstrap-stable — the interval must not straddle zero.)
7. Aggregate expected value is at least `+0.25%` after spread, slippage, and
   commission assumptions.
8. Whole-share deployment is feasible: at least `1` share deployable at the
   reference price and no `cannot_deploy_whole_share` verdict.
9. Per-symbol cost review must pass using symbol-specific spread/slippage
   overrides, or an explicit `DEFAULT` fallback plus symbol reference prices.
   A scan without symbol costs is provisional, not a pass.

## Fail Condition

The thesis fails if any of these are true:

- The event data cannot be represented point-in-time.
- Labeled sample size is `< 30`.
- Absolute decile lift is `< 8.0` percentage points.
- Blocked-null p-value is `> 0.05`.
- Family-wise p-value is `> 0.05`.
- Net expected value after costs is `< +0.25%`.
- Whole-share deployment makes the signal uneconomic at the account size.
- Per-symbol cost review is missing, provisional, or drops any reviewed symbol
  below positive net expected value.
- (Amendment A1) The decile lift is computed on fewer than `decile_min_rows`
  rows, regime directional coherence is asserted on a bucket below
  `regime_min_rows`, or — when the bootstrap is enabled — the decile-lift
  interval does not clear `8.0`pp or a qualifying regime bucket's interval
  straddles zero.

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

## Amendments

This contract is frozen. Thresholds are not edited in place; changes land here as
explicit, dated, append-only amendments. An amendment may only **strengthen** a
condition — never relax one.

### Amendment A1 — Power floors and bootstrap intervals for conditions 3 and 6

- Created: 2026-06-18
- Status: Proposed. Strengthening-only, so safe to adopt before the first-slice
  scan. The scan code (`scripts/post_earnings_drift_research.py`) already ships
  these defaults; adopting the amendment is merging it.
- Scope: conditions 3 and 6 only. No existing threshold is changed. The `8.0`pp
  decile-lift bar, the `30`-row aggregate floor for conditions 2 and 7, and the
  `<= 0.05` p-value gates (conditions 4 and 5) all stand exactly as written.

**Why.** The single `--min-rows 30` floor is adequate for the aggregate net-EV
read (condition 7) but under-powers two conditions:

- Condition 3 (absolute decile lift `>= 8.0`pp): 30 rows over 10 deciles is ~3
  names per decile, where an 8pp lift is within noise.
- Condition 6 (directional coherence across the regime split): splitting again
  by `report_timing` leaves each regime bucket near the 30-row floor, where a
  consistent direction can appear by chance.

The blocked-null (condition 4) and family-wise max-statistic (condition 5) gates
protect the *p-values*, but they do not make the decile-lift *magnitude* or the
regime *direction* stable. Conditions 3 and 6 can still pass on noise at N≈30.

**A1.1 — Decile-lift floor (condition 3).** The qualifying feature's decile lift
must be computed on at least `decile_min_rows` labeled rows (default `100`, ≈10
names per decile), set via `--decile-min-rows`. Below this floor the scan reports
`too_few_rows` for that feature and condition 3 cannot be claimed.

**A1.2 — Regime-bucket floor (condition 6).** A regime bucket qualifies for the
directional-coherence check only with at least `regime_min_rows` rows (default
`60`), set via `--regime-min-rows`. The existing "or no qualifying regime bucket"
escape is unchanged: a too-thin bucket simply does not qualify and can never
establish coherence.

**A1.3 — Interval gate (conditions 3 and 6).** With `--bootstrap-resamples > 0`
(default `1000`) the scan reports a 95% bootstrap CI of the decile lift, resampled
with replacement. The interval — not only the point estimate — must clear the bar:

- Condition 3: the 95% CI of the decile lift must lie entirely beyond `±8.0`pp on
  one side (`decile_lift_ci.ci_clears_bar == true`: `ci_low >= 8.0` or
  `ci_high <= -8.0`).
- Condition 6: each qualifying regime bucket's 95% CI must not straddle zero
  (`regime_direction_ci[*].direction_stable == true`), in addition to agreeing in
  direction across buckets.

A formable CI requires `regime_min_rows >= 3 x n_buckets` (≥ 30 at the default 10
deciles); the default 60 satisfies this. With `--bootstrap-resamples 0` the
interval gate is disabled and only the point estimate and the floors apply.

**A1.4 — Never-loosen invariant.** Both sub-floors are clamped up to `--min-rows`
at runtime, so no CLI setting can make conditions 3 or 6 weaker than the frozen
30-row aggregate floor. The defaults above encode this amendment; lowering them on
the command line can only raise, never lower, the effective floor below `--min-rows`.

**A1.5 — Payload surface (auditability).** The scan payload reports:

- `power_floors`: the effective `aggregate_min_rows`, `decile_min_rows`,
  `regime_min_rows`, and the `lift_bar_pct`.
- `decile_lift_ci`: the cited feature, point lift, 95% CI bounds, `same_sign_frac`,
  and `ci_clears_bar`. `null` when below the decile floor or the bootstrap is off.
- `regime_direction_ci`: per qualifying regime bucket, the cited feature, point
  lift, 95% CI bounds, and `direction_stable`.
