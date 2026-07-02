# Hold-Duration Edge Replay - 2026-07-01

## Scope

Read-only replay reframing the question from "short-term vs long-term" to
"which hold duration fits the observed edge?"

Terminology used here:

- Scalp: seconds to a few minutes.
- Day trade: intraday, minutes to hours.
- Swing trade: hours to a few days, including overnight.
- Position trade: days to weeks or months.

This analysis does not change exits, holding rules, broker behavior, sizing,
or trade authority.

## Data

Active candidate window:

- `auto_buy_candidates`: 5,378 rows from `2026-06-22` through `2026-07-01`.
- `feature_snapshots`: 8,740 rows, 76 symbols, from
  `2026-06-22T09:31:03-04:00` through `2026-07-01T15:56:26-04:00`.

Coverage limitation:

- 5m through EOD horizons are broadly covered.
- 1-session through 5-session horizons are progressively partial because the
  feature snapshot window ends on `2026-07-01`.
- 5-session results apply mostly to earlier candidates in the audit window, not
  the entire window.

Older realized-trade context:

- `historical_trade_outcomes`: 66 realized rows from Alpaca order export.
- This is older context, not direct validation of the active scoring audit
  window.

## All Candidates by Hold Horizon

| Horizon | Rows | Avg return | Median return | Positive rate | EV hit rate (`>=0.25%`) | Negative rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 5m | 5,281 | -0.0674% | -0.0272% | 44.16% | 25.43% | 52.43% |
| 15m | 5,269 | -0.0587% | -0.0370% | 44.43% | 27.86% | 52.82% |
| 30m | 5,257 | -0.0728% | -0.0437% | 44.72% | 30.00% | 52.73% |
| 60m | 5,209 | -0.1026% | -0.0568% | 44.44% | 31.89% | 53.10% |
| 120m | 5,125 | -0.1436% | -0.0795% | 43.77% | 33.81% | 53.83% |
| 240m | 4,947 | -0.1856% | -0.1164% | 43.48% | 35.98% | 53.99% |
| EOD | 5,305 | -0.2748% | -0.1078% | 37.23% | 25.45% | 55.89% |
| 1 session | 4,674 | -0.5068% | -0.4139% | 44.39% | 40.48% | 55.52% |
| 2 sessions | 4,146 | -0.5148% | -0.3857% | 46.26% | 43.54% | 53.74% |
| 3 sessions | 3,803 | -0.1247% | -0.0084% | 49.75% | 47.57% | 50.25% |
| 5 sessions | 2,785 | +1.0088% | +0.9935% | 55.04% | 53.29% | 44.81% |

Interpretation: the full candidate stream does not show a clean scalp/day-trade
edge. Average return is negative from 5m through 2 sessions. The positive
5-session result is interesting but partial and must be rechecked with more
complete later-window coverage.

## Fifteen-Minute Winners Held Longer

Rows where the 15-minute return was already positive:

| Horizon | Rows | Avg return | Median return | Positive rate | EV hit rate (`>=0.25%`) | Negative rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 15m | 2,341 | +0.7542% | +0.3675% | 100.00% | 62.71% | 0.00% |
| 30m | 2,338 | +0.7339% | +0.3909% | 90.25% | 63.26% | 9.75% |
| 60m | 2,315 | +0.7174% | +0.4055% | 81.08% | 60.86% | 18.66% |
| 120m | 2,280 | +0.7271% | +0.4311% | 75.18% | 60.13% | 24.56% |
| 240m | 2,225 | +0.6356% | +0.4690% | 69.17% | 57.84% | 30.56% |
| EOD | 2,341 | +0.3917% | +0.1920% | 62.88% | 45.45% | 30.63% |
| 1 session | 2,067 | +0.3539% | +0.3901% | 56.41% | 52.88% | 43.44% |
| 2 sessions | 1,786 | +0.2369% | +0.2811% | 53.19% | 50.22% | 46.81% |
| 3 sessions | 1,628 | +0.7108% | +0.6184% | 55.10% | 52.95% | 44.90% |
| 5 sessions | 1,148 | +1.1357% | +1.2461% | 55.84% | 54.70% | 44.16% |

Interpretation: the better question is not "should every signal be held
longer?" It is "when a candidate proves itself early, should exits allow more
room?" Fifteen-minute winners retained positive average return through 2h and
4h, and the partial multi-session result is also positive. Negative-rate growth
is material after 60m, so this supports a conditional hold-extension study, not
a blanket swing-trade rule.

## Score Bands

High-score candidates (`score >= 13`):

| Horizon | Rows | Avg return | Median return |
| --- | ---: | ---: | ---: |
| 15m | 314 | +0.1362% | 0.0000% |
| 30m | 313 | +0.1511% | -0.0202% |
| 60m | 313 | +0.2195% | -0.0215% |
| 120m | 309 | +0.0997% | -0.0678% |
| 240m | 290 | -0.0097% | -0.0267% |
| EOD | 315 | -0.1120% | -0.1477% |
| 1 session | 245 | -0.9090% | -1.0276% |
| 2 sessions | 203 | -1.5526% | -1.1532% |
| 3 sessions | 184 | -0.5638% | -0.7642% |
| 5 sessions | 137 | -0.1258% | -0.3028% |

Near-threshold candidates (`score 10-12.99`):

| Horizon | Rows | Avg return | Median return |
| --- | ---: | ---: | ---: |
| 15m | 209 | +0.2294% | +0.0239% |
| 30m | 208 | +0.1783% | +0.0217% |
| 60m | 206 | +0.1986% | +0.0302% |
| 120m | 202 | +0.0550% | 0.0000% |
| 240m | 192 | -0.2103% | 0.0000% |
| EOD | 209 | +0.0254% | 0.0000% |
| 1 session | 177 | -0.1909% | +0.2899% |
| 2 sessions | 146 | -0.3769% | +0.0134% |
| 3 sessions | 133 | +1.2958% | +1.5504% |
| 5 sessions | 96 | +1.4163% | +2.3083% |

Interpretation: score is not enough by itself to justify swing holds. The
`score >= 13` cohort works best around 60m, then deteriorates badly overnight.
The near-threshold cohort has intriguing 3-session and 5-session partial
results, but that needs a coverage-controlled replay before any policy work.

## Older Realized Trade Context

Historical Alpaca export outcomes by holding bucket:

| Hold bucket | Rows | Avg PnL | Win rate |
| --- | ---: | ---: | ---: |
| Scalp `<5m` | 1 | -2.0900% | 0.00% |
| Scalp `5-30m` | 6 | -0.1368% | 50.00% |
| Day `30-120m` | 17 | -0.3460% | 35.29% |
| Day `2h-1session` | 14 | +0.1446% | 64.29% |
| Overnight `<1d` | 19 | +0.0422% | 52.63% |
| Swing `1-3d` | 9 | +0.5874% | 88.89% |

Interpretation: small sample, older data, but it points in the same direction:
very fast exits do not look obviously superior, while 2h-to-swing buckets may
contain the better realized edge.

## Conclusion

Yes, this reframes the investigation usefully.

The current evidence says:

1. The raw candidate stream is not profitable just because it is held longer.
2. The edge may exist in conditional extension: candidates that are already
   working after 15 minutes retain positive average return through 2h and 4h.
3. High score alone does not justify swing/overnight holds; the high-score
   cohort degrades after intraday horizons.
4. Partial 3-session and 5-session results are interesting but not yet
   promotion evidence because coverage is incomplete and biased toward earlier
   rows in the audit window.

Recommended next validation:

- Build a no-write hold-policy counterfactual:
  - baseline current/15m behavior,
  - hold winners to 60m,
  - hold winners to 120m,
  - hold winners to 240m,
  - trail winners to EOD,
  - swing only if 15m winner plus regime/cluster remains supportive.
- Score each policy by EV after modeled slippage and worst adverse excursion,
  not just final forward return.
- Do not promote overnight/swing behavior until a full-window replay includes
  complete 1/2/3/5-session labels for all rows.
