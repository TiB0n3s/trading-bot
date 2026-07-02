# Symbol Performance and Correlation Expansion Check - 2026-07-01

## Scope

Read-only review before expanding the instrument range. This analysis does not
change the approved universe, add crypto, alter gates, change broker behavior,
or grant trading authority.

Primary local evidence:

- `trades.db`
- `scripts/symbols_config.py`
- `feature_snapshots`
- `auto_buy_candidates`
- `matched_trades`

## Data Availability

The active scoring audit window is `2026-06-21` through `2026-07-01`.

- `auto_buy_candidates`: 5,378 rows from `2026-06-22` through `2026-07-01`.
- `matched_trades`: 213 realized trades, but latest entry is
  `2026-06-15 11:58:10`; there are no realized trades in the active scoring
  audit window.
- `rejected_signal_outcomes`: 0 rows with 60-minute labels in the active
  scoring audit window.

Interpretation: current-window evidence is candidate forward-return evidence,
not realized PnL evidence. Realized matched-trade history is older context only.

## Current Universe

The approved universe already contains 77 symbols and 36 context-only symbols.
It is already broad across AI infrastructure, mega-cap tech, defense/aerospace,
healthcare, industrials, software, consumer, energy, financials, telecom,
materials, and index/hedge proxies.

Largest approved clusters:

| Cluster | Symbols |
| --- | ---: |
| `ai_infra` | 17 |
| `mega_cap_tech` | 11 |
| `defense` | 9 |
| `healthcare` | 8 |
| `industrials` | 8 |
| `software_infra` | 8 |
| `aerospace` | 7 |
| `power_energy` | 7 |

## Candidate Forward-Return Performance

Window: `2026-06-21` through `2026-07-01`.
Metric: computed 60-minute forward return from feature snapshots.

Best current-window symbols with at least 20 candidate rows:

| Symbol | Rows | Avg 60m | Median 60m | EV hit rate | Negative rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| OKTA | 101 | +0.7075% | +0.3751% | 52.48% | 35.64% |
| MRK | 86 | +0.4868% | +0.3096% | 51.16% | 33.72% |
| TSCO | 43 | +0.4170% | +0.0467% | 37.21% | 48.84% |
| CMCSA | 94 | +0.3888% | +0.0205% | 32.98% | 46.81% |
| LMT | 48 | +0.3576% | +0.0983% | 41.67% | 33.33% |
| MDB | 100 | +0.3505% | -0.1789% | 38.00% | 55.00% |
| RTX | 43 | +0.3361% | +0.2970% | 53.49% | 25.58% |
| ABBV | 82 | +0.3158% | +0.0218% | 32.93% | 43.90% |
| VRTX | 65 | +0.2969% | +0.2030% | 49.23% | 35.38% |
| V | 62 | +0.2628% | +0.0202% | 33.87% | 50.00% |

Worst current-window symbols with at least 20 candidate rows:

| Symbol | Rows | Avg 60m | Median 60m | EV hit rate | Negative rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| BE | 50 | -1.6584% | -1.4500% | 20.00% | 74.00% |
| ORCL | 41 | -1.3001% | -1.1443% | 4.88% | 92.68% |
| RKLB | 42 | -1.0772% | -0.9561% | 19.05% | 71.43% |
| ALB | 60 | -0.7965% | -0.5683% | 15.00% | 66.67% |
| VRT | 47 | -0.7673% | -0.4635% | 34.04% | 55.32% |
| NVDA | 45 | -0.7102% | -0.4690% | 13.33% | 75.56% |
| AAPL | 48 | -0.6952% | -0.2419% | 16.67% | 70.83% |
| TSLA | 47 | -0.6838% | -0.2592% | 21.28% | 70.21% |
| MRVL | 69 | -0.6635% | -0.6125% | 33.33% | 66.67% |
| KTOS | 55 | -0.6294% | -0.6808% | 29.09% | 63.64% |

## Cluster Performance

Current-window candidate forward returns by cluster:

| Cluster | Symbols | Rows | Avg 60m | Median 60m | EV hit rate | Negative rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `cybersecurity` | 2 | 197 | +0.4321% | +0.1133% | 45.69% | 43.15% |
| `healthcare` | 8 | 612 | +0.1717% | +0.0096% | 35.62% | 47.22% |
| `payments` | 3 | 221 | +0.1566% | 0.0000% | 34.39% | 48.87% |
| `energy` | 2 | 99 | +0.1064% | +0.0786% | 31.31% | 33.33% |
| `software_infra` | 8 | 646 | +0.1026% | -0.0384% | 37.77% | 51.39% |
| `ai_infra` | 16 | 1,044 | -0.3499% | -0.2170% | 34.77% | 56.03% |
| `mega_cap_tech` | 11 | 643 | -0.3205% | -0.1985% | 26.59% | 59.41% |
| `power_energy` | 7 | 392 | -0.5686% | -0.4191% | 27.81% | 61.22% |
| `critical_materials` | 3 | 184 | -0.5494% | -0.4605% | 26.09% | 62.50% |
| `defense` | 9 | 544 | -0.1984% | -0.0508% | 32.17% | 52.76% |

## Correlation Structure

Feature-snapshot 5-minute return correlations were computed from 76 symbols and
2,850 symbol pairs in the active audit window.

Highest positive pairs:

| Pair | Corr |
| --- | ---: |
| QQQ/SPY | +0.9341 |
| IWM/SPY | +0.8563 |
| NVDA/QQQ | +0.8223 |
| MRVL/QQQ | +0.8088 |
| ASML/QQQ | +0.7949 |
| T/VZ | +0.7811 |
| NVDA/SPY | +0.7801 |
| AVGO/QQQ | +0.7724 |
| QQQ/TSM | +0.7656 |
| IWM/QQQ | +0.7614 |

Lowest pairs:

| Pair | Corr |
| --- | ---: |
| T/TSM | -0.4496 |
| CMCSA/MRVL | -0.4404 |
| TSM/VZ | -0.4174 |
| QQQ/T | -0.4141 |
| CMCSA/FCX | -0.4028 |
| KTOS/MRK | -0.4024 |
| NVDA/VZ | -0.3965 |
| QQQ/VZ | -0.3897 |

Cluster average correlations:

| Cluster | Avg corr |
| --- | ---: |
| `broad_index` | +0.8506 |
| `networking` | +0.5710 |
| `telecom` | +0.5397 |
| `semiconductors` | +0.4236 |
| `ai_infra` | +0.3910 |
| `mega_cap_tech` | +0.3270 |
| `defense` | +0.2555 |
| `healthcare` | +0.1175 |
| `consumer` | +0.0432 |

## Interpretation

The evidence does not support broad expansion as the first fix for PnL.

The current universe is already broad, but the recent candidate opportunity set
was dominated by correlated weakness in AI infrastructure, mega-cap tech,
semiconductors, power energy, and critical materials. Adding more names inside
those same themes would likely increase noise and exposure without improving
market perspective.

The better expansion direction is selective context and paper-only observation
in lower-correlation clusters where current-window evidence is less bad:

- Healthcare quality/liquidity names adjacent to MRK, VRTX, ABBV.
- Cybersecurity/software names adjacent to OKTA, ZS, MDB, but only after
  checking spread and event sensitivity.
- Payments/financials names adjacent to V, MA, PYPL, JPM, SOFI.
- Telecom/defensive yield proxies as context/risk-regime signals, not as
  immediate buy candidates.

Crypto should not be added as a live or paper-buy authority shortcut. If it is
explored, the first safe version is context-only:

- BTC/ETH as 24/7 risk-appetite and liquidity-regime context.
- No broker/order integration.
- No sizing, gate override, or live buy authority.
- Separate volatility, liquidity, fee, custody, weekend, and data-quality
  assumptions.
- Promotion only after a replay shows incremental predictive value after costs
  and no degradation in equity-symbol EV.

## Recommended Next Validation

Create a no-write expansion-readiness report that scores candidate additions by:

1. Incremental cluster coverage.
2. Correlation to the existing universe.
3. Current-window forward-return profile.
4. Spread/liquidity/affordability.
5. Whether the symbol would reduce concentration in losing clusters.

Until that report exists, the practical action is not "add more symbols"; it is
"rebalance observation weight toward lower-correlation clusters and stop
treating AI-infra breadth as diversification."
