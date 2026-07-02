# Hold-Duration Pattern Rescue V1 Pre-Commitment

Created: 2026-07-02

Status: frozen; validation interpretation paused pending date-cluster
sensitivity. This is a research contract only and grants no paper, cash,
sizing, exit, or gate authority.

## Background

The `2026-07-01 --lookback-days 10` hold-duration replay is exploratory only.
It showed pattern-supported non-passing candidates clearing some post-cost
screen cells, but it was a single-window, multi-horizon scan with no
precommitted primary horizon. It cannot be used as validation evidence for a
holding-policy change.

Before any second non-overlapping window is interpreted, the primary test
horizon is fixed here.

## Fixed Test

- Thesis: among auto-buy candidates that did not pass approval gates, the
  `bar_pattern_features` buy-window signal can identify a subset with positive
  60-minute edge after realistic costs.
- Primary horizon: `60m`.
- Primary cohort: non-passing candidates with pattern buy support, where pattern
  buy support is `opportunity_action == buy_candidate`, buy-window quality, or
  `long_opportunity_score >= 70`, excluding sell/avoid windows.
- Ordering feature for lift: `long_opportunity_score`.
- Success label for decile lift and blocked-null testing:
  `net_return_pct >= +0.25%`.
- Cost model: use the hold-duration replay default `16 bps` round trip unless a
  stronger real per-symbol cost model is available before the run. A zero-cost
  replay is not eligible for interpretation.
- Null model: market-date blocked permutation null with horizon-specific
  permutation seed salt and at least 2,000 permutations. Shared base code is
  acceptable; shared random streams across horizons are not. If the observed
  p-value lands on the permutation floor because there are zero null
  exceedances, record it as a floor-bound estimate, not a precise p-value.
  The current implementation is a within-date blocked hypergeometric
  permutation over top/bottom score buckets; it is not whole-date cluster
  resampling. A validation result may not be promoted to "confirming window"
  evidence until a date-cluster sensitivity check is written and run.
- Validation window: the next run must be non-overlapping with
  `2026-06-21..2026-07-01`. The first candidate validation command is:
  `PYTHONPATH=src TRADING_BOT_SKIP_VENV_REEXEC=1 python3 ops_check.py hold-duration-replay 2026-06-20 --lookback-days 10 --gate-permutations 2000 --authority-horizons 60m --primary-horizon-only`.

## Pass Conditions

The V1 validation window passes only if the primary `60m` row satisfies all of
these:

1. Pattern-supported primary-horizon rows `>= 300`.
2. Primary-horizon coverage `>= 75%`.
3. Average net return after costs `>= +0.25%`.
4. Top-minus-bottom success-rate decile lift on `long_opportunity_score`
   `>= +8.0` percentage points.
5. Market-date blocked-null p-value `<= 0.05`.
6. P-value diagnostics are present: sample fingerprint, block count,
   permutation seed salt, permutation count, exceedance count, p-value floor,
   floor flag, null mean/std, null p95, and null max.
7. Sample concentration diagnostics are present for the primary sample:
   symbol count, top-symbol share, top-5-symbol share, date count, top-date
   share, and top-3-date share.
8. Date-cluster sensitivity is present and does not contradict the row-level
   blocked-null result. This must treat trading dates as the effective
   independent units, not only as within-date exchangeability blocks.

## Date-Cluster Sensitivity Addendum

This addendum must be implemented before the 2026-06-10..2026-06-20 validation
window can be interpreted as confirming evidence.

The cluster sensitivity test is fixed as follows:

1. Use only the precommitted primary cohort and `60m` horizon.
2. Keep the full-window `long_opportunity_score` ordering and identify the
   global bottom and top score buckets used for the primary decile lift.
3. For each trading date, compute top-minus-bottom success-rate lift using only
   rows from that date that fall into those global top/bottom buckets. A date is
   valid only if it has at least 20 top-bucket rows and 20 bottom-bucket rows.
4. Run a one-sided exact sign test over valid trading dates where a success is
   `date_lift_pp > 0`.
5. Run leave-one-date-out aggregate checks; after omitting each valid date in
   turn, recompute the primary aggregate net EV and top-minus-bottom lift.

The date-cluster sensitivity passes only if all of these are true:

1. At least five valid trading dates are available.
2. The one-sided sign-test p-value is `<= 0.05`. With seven valid dates, this
   requires all seven dates to have positive top-minus-bottom lift.
3. Median date-level lift is `>= +8.0` percentage points.
4. Every leave-one-date-out aggregate keeps average net return after costs
   `>= +0.25%`.
5. Every leave-one-date-out aggregate keeps top-minus-bottom lift `>= +8.0`
   percentage points.

If any condition fails, the validation window is not confirming evidence. It may
remain exploratory evidence, but no promotion contract can cite it as a passed
second window.

## Fail Conditions

The V1 validation window fails if any primary-horizon pass condition fails.
`15m`, `eod`, `1_session`, `3_sessions`, and `5_sessions` are diagnostics only
and cannot rescue a failed `60m` result. A later choice to test another horizon
requires a new precommitment before inspecting another validation window.

## Actions

- Pass: record the result as validation evidence for a future, separate frozen
  promotion contract. No automatic bot behavior, exit, gate, or holding-policy
  change follows from this pass.
- Fail: record the result and do not adjust holding logic from this pattern
  rescue thesis.

## Known Limitations

- The July 1 exploratory window was already inspected and is not validation
  evidence.
- The validation run remains a historical replay, not live paper proof.
- Overlap among secondary horizons is expected; secondary horizon p-values are
  not independent promotion evidence.
- The current row-level blocked-null p-value controls for market-date base
  rates, but the June 10..June 20 validation sample is concentrated across
  seven trading dates. Until date-cluster sensitivity is added, the locked
  window is not recorded as a confirming pass.
