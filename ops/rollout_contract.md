# Rollout Contract

The rollout contract is a deterministic governance report for deciding whether
a diagnostic feature family is mature enough to consider for future authority.
It does not grant live trading authority by itself.

## Status Meanings

- `not_ready`: the family failed a hard guardrail, such as sample size, missing
  rate, stability, or absolute overlap risk.
- `observe_only`: the family can be reviewed in reports and snapshots, but must
  not size, block, approve, or submit orders.
- `size_down_candidate`: the family has enough evidence to consider a future
  size-reduction-only policy. It still cannot affect live trades until a
  separate explicit authority path consumes it.
- `narrow_block_candidate`: the family has enough evidence to consider a future
  narrowly scoped block policy. The current contract still marks this as
  review-only and requires future implementation before enforcement.

## Current Family Caps

These are maximum rollout statuses, not live permissions.

| Feature family | Current cap | Rationale |
| --- | --- | --- |
| `portfolio_decision` | `narrow_block_candidate` | Duplicate portfolio risk is closest to deterministic risk control. |
| `execution_quality` | `size_down_candidate` | Execution costs affect net edge, but block authority needs more evidence. |
| `volatility_normalization` | `size_down_candidate` | Useful for stretch/chase containment, with overlap risk to monitor. |
| `market_microstructure` | `size_down_candidate` | Useful for liquidity/session effects, with overlap risk to monitor. |
| `downside_asymmetry` | `size_down_candidate` | Good candidate for risk reduction; event-risk blocks require later evidence. |
| `market_participation` | `observe_only` | Likely correlated with regime, trend, and setup quality. |
| `market_regime` | `observe_only` | Broad context; high overlap risk with other signals. |
| `utility_estimate` | `observe_only` | Derived/meta feature; should not govern directly yet. |
| `calibrated_confidence` | `observe_only` | Evidence layer, not a policy layer. |
| `setup_structure` | `observe_only` | Potential size-down candidate later, but overlaps existing setup quality. |

## Threshold Meanings

- `min_sample_size_size_down`: minimum outcome rows before a family can be
  considered for size-down candidacy.
- `min_sample_size_block`: minimum outcome rows before a family can be
  considered for narrow-block candidacy.
- `max_missing_rate`: maximum allowed share of rows missing the feature family.
- `min_stability_share_size_down`: minimum share of rolling windows where the
  best bucket remains favorable enough for size-down review.
- `min_stability_share_block`: stricter rolling-window stability requirement for
  narrow-block review.
- `max_overlap_risk_for_promotion`: maximum feature-family overlap before
  promotion is capped to observe-only.
- `max_overlap_risk_absolute`: hard failure threshold for duplicate-signal risk.
- `min_false_positive_reduction_*`: minimum observed reduction in allowed losers
  required for candidate status.
- `max_false_negative_cost_*`: maximum allowed increase in blocked/rejected
  winners required for candidate status.
- `min_calibration_quality`: minimum calibration grade required before promotion
  beyond observe-only.

## Candidate Does Not Mean Authority

`size_down_candidate` and `narrow_block_candidate` are governance labels. They
mean the family is eligible for operator review and replay validation.

They do not:

- change approval behavior
- change sizing behavior
- block signals
- submit orders
- bypass existing hard gates

Live authority requires a separate implementation, explicit runtime config, and
tests proving the new authority path consumes the rollout assessment safely.
