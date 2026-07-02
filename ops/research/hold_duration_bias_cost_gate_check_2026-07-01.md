# Hold-Duration Bias, Cost, and Gate Check - 2026-07-01

## Scope

Read-only follow-up to the hold-duration replay. This answers three questions:

1. Is the 15-minute winner extension edge real, or just survivorship bias?
2. What execution-cost evidence exists for holding longer?
3. Do the current approval gates support longer hold durations?

No live behavior, exits, sizing, broker logic, gates, or approved universe were
changed.

## Data

Window: `2026-06-21` through `2026-07-01`.

- `auto_buy_candidates`: 5,378 rows.
- `feature_snapshots`: 8,740 rows, 76 symbols.
- 15-minute return available: 5,269 candidates.
- 15-minute winners (`return_15m > 0`): 2,341.
- 15-minute losers (`return_15m < 0`): 2,783.
- 15-minute flats (`return_15m == 0`): 145.

Forward returns are mark-to-market from feature snapshots. They are not realized
fills.

## 1. Survivorship Bias Check

The inverse test is: what happens to 15-minute losers if they are held longer?

### Fifteen-Minute Winners

| Horizon | Rows | Avg return | Median return | Positive rate | EV hit rate (`>=0.25%`) | Negative rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 15m | 2,341 | +0.7542% | +0.3675% | 100.00% | 62.71% | 0.00% |
| 60m | 2,315 | +0.7174% | +0.4055% | 81.08% | 60.86% | 18.66% |
| 120m | 2,280 | +0.7271% | +0.4311% | 75.18% | 60.13% | 24.56% |
| 240m | 2,225 | +0.6356% | +0.4690% | 69.17% | 57.84% | 30.56% |
| EOD | 2,341 | +0.3917% | +0.1920% | 62.88% | 45.45% | 30.63% |
| 1 session | 2,067 | +0.3539% | +0.3901% | 56.41% | 52.88% | 43.44% |

### Fifteen-Minute Losers

| Horizon | Rows | Avg return | Median return | Positive rate | EV hit rate (`>=0.25%`) | Negative rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 15m | 2,783 | -0.7456% | -0.4358% | 0.00% | 0.00% | 100.00% |
| 60m | 2,749 | -0.7983% | -0.5443% | 15.46% | 8.84% | 84.47% |
| 120m | 2,700 | -0.8874% | -0.6407% | 19.07% | 13.00% | 80.93% |
| 240m | 2,577 | -0.9043% | -0.6816% | 23.24% | 18.70% | 76.68% |
| EOD | 2,783 | -0.8537% | -0.5582% | 17.36% | 9.77% | 79.70% |
| 1 session | 2,468 | -1.2207% | -1.0542% | 34.64% | 30.35% | 65.32% |

Answer: the intraday extension edge is not just mechanical survivorship bias.
Fifteen-minute losers do not generally recover by 60m, 120m, 240m, or EOD. They
remain negative on average and mostly negative by count.

Important caveat: by 5 sessions, 15-minute losers showed a positive average in
the partial sample. That is not promotion evidence because multi-session labels
are incomplete and biased toward earlier rows in the audit window.

## 2. Execution Cost Check

The candidate-level cost answer is currently incomplete.

Available cost fields in the active window:

| Source | Rows | Spread rows | Slippage rows | Execution-cost rows |
| --- | ---: | ---: | ---: | ---: |
| `feature_snapshots` | 8,740 | 0 | n/a | n/a |
| `bar_pattern_features` | 173,437 | 0 | 0 | 0 |

The hold replay therefore measures gross mark-to-market returns only. It does
not include actual hypothetical fill price, bid/ask spread, slippage, fees, or
overnight gap risk.

Observed gross decay for 15-minute winners:

| Horizon | Avg return | Decay vs 15m |
| --- | ---: | ---: |
| 15m | +0.7542% | 0.0000% |
| 60m | +0.7174% | -0.0368% |
| 120m | +0.7271% | -0.0271% |
| 240m | +0.6356% | -0.1186% |
| EOD | +0.3917% | -0.3625% |
| 1 session | +0.3539% | -0.4003% |

Answer: the decay is visible in gross price returns, especially by EOD and
overnight. Because spread/slippage fields are empty, the system cannot yet
separate profit erosion from execution friction. Net EV is lower than these
tables show.

Before any hold-extension policy is promoted, the replay needs explicit cost
assumptions or populated spread/slippage data at entry and hypothetical exit.

## 3. Gate-Structure Check

The current score and setup gates are weak longer-horizon predictors.

### Correlation to Forward Return

| Horizon | Rows | Corr(score, return) | Corr(setup_score, return) |
| --- | ---: | ---: | ---: |
| 15m | 5,269 | +0.1147 | -0.0146 |
| 60m | 5,209 | +0.1123 | -0.0002 |
| 120m | 5,125 | +0.0813 | +0.0144 |
| 240m | 4,947 | +0.0709 | +0.0185 |
| EOD | 5,305 | +0.0849 | -0.0299 |
| 1 session | 4,674 | +0.0550 | +0.0191 |
| 5 sessions | 2,785 | -0.0513 | +0.0969 |

### High-Score Cohort (`score >= 13`)

| Horizon | Rows | Avg return | Median return |
| --- | ---: | ---: | ---: |
| 15m | 314 | +0.1362% | 0.0000% |
| 60m | 313 | +0.2195% | -0.0215% |
| 120m | 309 | +0.0997% | -0.0678% |
| 240m | 290 | -0.0097% | -0.0267% |
| EOD | 315 | -0.1120% | -0.1477% |
| 1 session | 245 | -0.9090% | -1.0276% |
| 5 sessions | 137 | -0.1258% | -0.3028% |

### Gate Groups

Selected average returns:

| Gate group | 15m | 60m | 120m | 240m | EOD | 1 session |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| No hard block | +0.1369% | +0.1232% | +0.1291% | +0.1269% | -0.0601% | -0.0303% |
| Strategy-memory weak | -0.0897% | -0.1501% | -0.2102% | -0.2852% | -0.3077% | -0.5179% |
| Setup avoid | -0.0279% | -0.0710% | -0.1153% | -0.1346% | -0.2029% | -0.4438% |
| Bias avoid | -0.2724% | -0.3584% | -0.3586% | -0.4597% | -0.5441% | -0.8912% |
| Tape regime | -0.2050% | -0.2392% | -0.2661% | -0.3371% | -0.3923% | -0.6907% |

Answer: the current gates do not support a blanket swing-trade transition.
They were not designed to rank multi-session outcomes, and score strength alone
does not carry into EOD/overnight. The existing hard-block groups remain
negative across longer horizons, so weakening them for swing behavior would be
unsupported.

## Decision

The useful adjustment is conditional hold extension, not a general swing-trade
conversion.

Evidence-supported working hypothesis:

- If a candidate is positive after 15 minutes, holding to 60m/120m/240m may
  preserve enough edge to be worth testing.
- If a candidate is negative after 15 minutes, holding longer is usually worse
  through intraday and EOD horizons.
- Current score/gate logic is not sufficient to select overnight or
  multi-session holds.
- Execution-cost data is missing, so all hold-extension EV is currently gross,
  not net.

Recommended next no-write validation:

1. Build a hold-policy counterfactual:
   - exit all at 15m,
   - hold only 15m winners to 60m,
   - hold only 15m winners to 120m,
   - hold only 15m winners to 240m,
   - trail 15m winners to EOD,
   - swing only 15m winners when regime, tape, and cluster stay supportive.
2. Include MAE/MFE or stop/trailing-stop assumptions, not just terminal return.
3. Apply explicit cost assumptions until spread/slippage fields are populated.
4. Evaluate by net EV after costs, drawdown, adverse excursion, and exposure
   time, not average return alone.
