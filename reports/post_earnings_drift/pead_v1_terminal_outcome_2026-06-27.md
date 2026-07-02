# PEAD V1 Terminal Outcome

Archived: 2026-07-01

Hypothesis: post-earnings drift over 5 sessions
Input file: `data/pead_research/pead_research.db`
PIT audit file: `ops/research/post_earnings_drift_v1_pit_audit.md`
Validation report: repository/DB shape only; independent PIT tie-out remains incomplete
Scan report: `reports/post_earnings_drift/scan_2026-06-27.json`
Event rows: 141
Labeled rows: 141
Minimum labeled rows threshold: 30
Point-in-time verdict: provisional; not independently tied out
Absolute decile lift: `-21.5` percentage points on `earnings.post_event_gap_pct`; threshold: `>= 8.0` absolute percentage points
Decile bucket size: 10 buckets x 14 rows for the cited feature
Decile lift CI: `[-50.0, 21.4]` percentage points; interval does not clear the `8.0`pp bar
Blocked-null p-value: `0.1045`; threshold: `<= 0.05`
Family-wise p-value: `0.7015`; threshold: `<= 0.05`
Regime coherence verdict: fail; qualifying regime CIs straddle zero
Net expected value after costs: `-1.402001%`; threshold: `>= +0.25%`
Whole-share/account-size verdict: not evaluated; scan did not include `--account-equity`
Per-symbol cost verdict: provisional/fail; all 141 reviewed symbols used `scan_flat_default`
Final verdict: fail under `ops/research/post_earnings_drift_v1_precommit.md`

Required action:

- Archive PEAD v1.
- Move to the next ranked structural hypothesis only after freezing its own
  precommit contract.
- Do not treat PEAD v2, a redesigned lift construction, or a wider sample as a
  continuation of this v1 contract. Any PEAD v2 must be a new precommit with an
  explicit sample-size / minimum-detectable-effect calculation and stopping rule
  before additional results are inspected.

Notes:

- The ranked queue already exists in the v1 contract: post-earnings drift;
  options positioning / implied volatility / skew / gamma-context effect;
  short-interest or crowded-positioning effect; ETF/sector flow or rebalance
  effect.
- The queue is not the same as a set of frozen contracts. Hypotheses 2-4 still
  require their own PIT source definition, sample-size target, cost model,
  pass/fail gates, and archive/stopping rule before research begins.
- The flat cost model remains optimistic and should be fixed for future EV work,
  but it is not the reason PEAD v1 failed. The decisive non-cost failures were
  blocked-null p-value `0.1045`, family-wise p-value `0.7015`, and the bootstrap
  interval crossing zero.
