# Auto-Buy Strategy Status

Generated: 2026-06-16

## Current Status

The current OHLCV-derived auto-buy strategy stack has no demonstrated deployable
edge and must remain in observe/research mode. Do not loosen live-buy, score,
probability, setup-memory, or ML authority gates to increase trade count without
new evidence that clears the promotion checklist below.

Emergency operational halt: on 2026-07-02, scheduled `auto_buy_manager --live`
cron entries were removed and `/etc/trading-bot.env` was changed to
`AUTO_BUY_LIVE_BUYS=false` after repeated `trades.db` reads and backup
verification attempts entered `D`-state I/O wait on `/dev/sdd`, leaving zero
verified restorable database backups. Do not restore scheduled auto-buy or
`AUTO_BUY_LIVE_BUYS=true` until storage is repaired and a fresh manifest-backed
database backup passes restore verification. This halt is risk reduction during
an infrastructure failure, not a strategy promotion or research verdict.

This status covers the existing auto-buy confluence score, setup score,
probability gate, intraday feedback, strategy-memory, and layered-ML authority
path as currently built from price/volume-derived candidate features.

## Evidence Summary

- Narrow candidate scans produced provisional feature lift, but the strongest
  lead, `session_trend_score`, weakened to within-noise on the wider rejected
  forward-outcome sample.
- Feature scans must account for multiple looks. Per-feature blocked-null
  p-values are insufficient by themselves because scanning many features and
  regimes will produce false leads by chance. The research harness now applies
  a max-statistic permutation null across the scanned feature family.
- The additive confluence score did not rank-order forward winners in the wider
  labeled sample.
- Setup score did not show stable discrimination in the wider rejected-outcome
  sample.
- The only wider global survivor, `momentum_30m_pct` with lower values doing
  better, was marginal and directionally inconsistent with the earlier trend
  continuation lead.
- `intraday_feedback_evidence.loss_rate` was audited and is not direct same-day
  or future-label leakage: materialized feedback uses prior `matched_trades`
  only, with a 20-day lookback and `same_day_trades=0` in current rows. It is
  still thin evidence because matched realized trades are limited.
- Full-span `candidate_universe` scanning is operationally expensive because
  candidate features are stored as large JSON blobs. A flat labeled feature
  table is optional research infrastructure, not a deployment unlock.

## Observe-Mode Learning Ceiling

Additional observe-mode data can improve estimates for signals the system
already sees, but it should not be treated as a mechanism for discovering edge
from the current feature set. More candidate-forward outcomes may improve
probability calibration, more matched trades may reduce strategy-memory and
intraday-feedback noise, and more market days may strengthen regime and symbol
priors. That is useful learning, but if the underlying OHLCV-derived features
remain non-discriminative, the expected result is a better-estimated null: more
confident `avoid` or `caution` decisions, not deployable capital authority.

Because execution is frozen, the realized-trade channel also does not receive
new entry/exit/net-cost examples. Observe mode can refine candidate proxy
labels, but it cannot answer whether actual fills, exits, spreads, slippage, and
whole-share sizing produce net profitability. The data's primary value during
the freeze is as a multi-regime research substrate for new orthogonal signals or
new interaction hypotheses, not as passive fuel for the existing intelligence to
bootstrap an edge.

## Promotion Checklist

No auto-buy strategy variant may receive capital authority unless it clears all
of the following, in order:

1. Demonstrated discrimination before capital authority.
2. Decile lift before calibration.
3. Regime split before global conclusions.
4. Blocked permutation null before trusting per-feature p-values.
5. Multiple-testing correction before trusting the best feature in a scan.
6. Leakage and circularity audit before trusting any survivor.
7. Net-of-costs edge before capital authority.
8. Wider independent days before deployment confidence.

Net-of-costs review must include spread, slippage, order timing, missed fills,
and whole-share sizing drag for the actual account size.

The promotion model is:

```text
validated information -> calibrated probability -> expected value after costs -> action/no action
```

Do not promote probability-only gates, percentile-only gates,
best-candidate-buying logic, unvalidated ML approvals, or OHLCV-only pattern
authority. Probability is an input to the expected-value calculation, not a
capital-authority decision by itself.

## Operational Guardrail

Until a new thesis clears the checklist:

- Keep this OHLCV auto-buy stack in observe/research mode.
- Do not flip percentile probability mode, relax learned setup thresholds, or
  lower conviction bars as a substitute for measured edge.
- Runtime config must treat `CONVICTION_PROBABILITY_GATE_MODE=percentile` as
  non-authoritative unless `CONVICTION_ALLOW_PERCENTILE_PROBABILITY_GATE=true`
  is also set for deliberate research.
- Treat additional candidate captures as passive research data only.
- Any future live or paper-authority promotion must include a new evidence note
  that explicitly supersedes this file.

## Research Infrastructure Priorities

The useful work is not more runtime intelligence. It is infrastructure that
makes future intelligence harder to overfit or misread:

1. Consolidate the detector into one reusable research harness: feature in,
   verdict out, covering decile lift, regime splits, blocked nulls,
   multiple-testing correction, leakage checks, and net-cost review.
2. Make the net-of-cost hurdle concrete using actual fill data: spread,
   slippage, timing, missed fills, and whole-share sizing drag should produce a
   numeric expectancy gate before any capital authority.
3. Prune or quarantine unvalidated layered ML, ensemble, and meta-label
   machinery that has not earned a place through the harness. Complexity without
   evidence is maintenance burden and a source of false confidence.
4. Treat new orthogonal data sources as the primary frontier. More transforms of
   the same OHLCV inputs are lower-priority unless they pass the corrected
   research harness out of sample.

## Historical Candle Research Use

Historical candle data should be used to widen the research view, not to relax
runtime authority. Use `scripts/historical_market_view.py` to:

- audit symbol/date/label coverage in `bar_pattern_features`,
- summarize baseline outcomes by symbol, trend-scan label, bar-pattern label,
  opportunity action, triple-barrier reason, day of week, and intraday bucket,
- rerun the corrected feature scan over historical bar-pattern rows, including
  blocked market-date permutation and max-statistic family correction,
- optionally export a flat CSV substrate for future signal tests.

This report is read-only and explicitly non-authoritative. A historical-candle
survivor still needs the full promotion checklist, including leakage review,
independent validation, and net-of-cost expectancy, before auto-buy can act.

## Orthogonal Signal Research Use

Price and volume remain useful as state: regime, risk, sizing context, and
whether a move is already extended. They are not currently demonstrated as a
standalone predictive edge. New edge work should therefore enter as
point-in-time external features through `external_signal_features`, then pass
the same detector and promotion checklist before any runtime authority changes.

Acceptable external-feature candidates include event structure, earnings or
filing evidence, macro/calendar state, options-derived positioning, sector or
ETF flow context, short-interest context, and other data whose availability can
be represented without lookahead. The key contract is `available_at`: a feature
must only join to candidate decisions after it was knowable in real time. The
table and scanner are research infrastructure only; they do not grant capital
authority.

The first explicitly supported orthogonal thesis is post-earnings drift over
multi-session horizons. Use `scripts/post_earnings_drift_research.py` to ingest
point-in-time earnings events, label forward returns from `bar_pattern_features`,
run the corrected feature detector, and compute expected value after spread,
slippage, and whole-share deployment constraints.

PEAD v1 terminal status: failed and archived on 2026-07-01 from the June 27
scan. The frozen contract did not clear the non-cost statistical gates
(`blocked-null p=0.1045`, `family-wise p=0.7015`) or the EV/cost gates
(`net EV=-1.402001%`, `provisional_no_symbol_costs`). Treat any PEAD v2 or
successor thesis as a new precommit, not an extension of v1.

The remaining structural hypothesis queue is governance-only until re-ranked by
an explicit feasibility and minimum-detectable-effect review. See
`ops/research/structural_hypothesis_queue.md`.

Structural-hypothesis terminal status: parked as `not_affordably_testable` under
the current matrix. No successor hypothesis is ready for a frozen precommit; no
bounded follow-up task has been opened. See
`reports/structural_hypothesis/structural_hypothesis_terminal_outcome_2026-07-02.md`.

The structural-hypothesis program has concrete unpark triggers, not an open-ended
research queue. Reopen only through the candidate-specific thresholds in
`ops/research/structural_hypothesis_queue.md`: clustered/effective-sample power
at alpha `0.0125` and `80%` power, verified PIT source coverage and cost caps,
an explicit budget/economics decision, or a newly frozen successor family with a
program-level alpha plan. Deep Thought/SaaS work is not automatically funded or
selected by this parked trading-research outcome.

## PEAD / Strategy Reason To Reopen

Reopen only for one of these bounded cases:

- A genuinely new, orthogonal data source or signal thesis is introduced.
- A flat labeled feature table is built for cheaper offline research.
- A materially wider independent-day sample is available under a newly frozen
  precommit or explicitly defined successor framework with lift/regime,
  blocked-null, multiple-testing, leakage, net-cost, and sample-size rules.

These general strategy reopen cases do not override the structural-hypothesis
unpark triggers above.
