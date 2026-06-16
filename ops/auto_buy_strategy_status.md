# Auto-Buy Strategy Status

Generated: 2026-06-16

## Current Status

The current OHLCV-derived auto-buy strategy stack has no demonstrated deployable
edge and must remain in observe/research mode. Do not loosen live-buy, score,
probability, setup-memory, or ML authority gates to increase trade count without
new evidence that clears the promotion checklist below.

This status covers the existing auto-buy confluence score, setup score,
probability gate, intraday feedback, strategy-memory, and layered-ML authority
path as currently built from price/volume-derived candidate features.

## Evidence Summary

- Narrow candidate scans produced provisional feature lift, but the strongest
  lead, `session_trend_score`, weakened to within-noise on the wider rejected
  forward-outcome sample.
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
4. Blocked permutation null before trusting p-values.
5. Leakage and circularity audit before trusting any survivor.
6. Net-of-costs edge before capital authority.
7. Wider independent days before deployment confidence.

Net-of-costs review must include spread, slippage, order timing, missed fills,
and whole-share sizing drag for the actual account size.

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

## Reason To Reopen

Reopen only for one of these bounded cases:

- A genuinely new, orthogonal data source or signal thesis is introduced.
- A flat labeled feature table is built for cheaper offline research.
- A materially wider independent-day sample is available and rerun through the
  existing lift, regime, blocked-null, leakage, and net-cost framework.
