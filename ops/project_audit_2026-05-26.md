# Project Audit - 2026-05-26

## Current Operating Posture

- Runtime remains `EXECUTION_MODE=paper`.
- `LIVE_TRADING_ENABLED=false` remains the outer live-cash guard.
- TradingView alerts remain connected for the original alert cohort.
- Internal/bar-only symbols are now collected, scored, and eligible for
  auto-buy paper execution through `auto_buy_manager.py`.
- Prediction/model output remains observe-only.

## Completed Integration Work

- Added rejected-signal counterfactual outcomes:
  - `rejected_signal_outcome_builder.py`
  - `rejected_signal_outcomes`
  - `ops_check.py rejected-outcomes`
- Added internal/bar-only symbol cohort:
  - `SYMBOL_UNIVERSE_VERSION=approved_universe_2026_05_26_internal_bar_expansion_v1`
  - 18 symbols tagged as `internal_bar_only`
  - market context, session momentum, and feature snapshots refreshed for 59 symbols
- Added auto-buy candidate methodology:
  - `auto_buy_manager.py --scope internal`
  - `auto_buy_candidates`
  - `AUTO_BUY_CANDIDATE` bot events
  - `ops_check.py auto-buy`
  - live paper execution enabled through cron with `--live`
- Auto-buy live safety rails:
  - `AUTO_BUY_MAX_ORDERS_PER_RUN=1`
  - `AUTO_BUY_MAX_DAILY_ORDERS=3`
  - `AUTO_BUY_COOLDOWN_MINUTES=60`
  - small default sizing: `AUTO_BUY_POSITION_SIZE_PCT=0.50`
- Auto-sell cleanup:
  - existing position-momentum auto-sell remains enabled
  - indentation/comment cleanup around risk/profit gates
  - broker sell cancel polling remains centralized in `broker.py`

## Current Evidence From 2026-05-26

- Rejected outcome coverage:
  - rejected rows: 1459
  - outcome rows: 1459
  - labeled: 1274
  - partial: 185
  - missing/error: 0
- Auto-buy internal cohort observe run:
  - strong candidates: BURL, PFE, DKS
  - no orders submitted during the after-hours validation run because market was closed
- Order health:
  - approved rows: 33
  - missing order IDs: 0
  - missing order status: 0

## Enhancement Opportunities

1. Auto-buy forward outcome validation
   - Join `auto_buy_candidates` to forward bars, just like rejected signals.
   - Compare internal candidate quality to TradingView-triggered approvals and
     rejections by 5m/15m/30m/60m returns.

2. Decision snapshots
   - Add immutable per-signal decision snapshots before broader ML training.
   - Include market context hash, override hash, symbol universe version, setup,
     session momentum, risk gates, final decision, and order metadata.

3. Internal signal candidate generator
   - Promote auto-buy scoring into a generalized internal signal stream.
   - Record candidate events even when score is below buy threshold so missed
     internal opportunities can be evaluated.

4. Auto-sell outcome attribution
   - Add forward/post-exit outcome tracking for `position_momentum_checks`.
   - Quantify avoided drawdown vs. left-on-table for auto-sell candidates.

5. Symbol-source cohort reporting
   - Add a daily report comparing `internal_bar_only` vs `tradingview_alert`
     cohorts by signal count, candidate score, approval rate, realized P&L,
     forward returns, and rejection categories.

6. Point-in-time context archives
   - Archive `market_context.json`, override files, and symbol universe metadata
     by effective timestamp.
   - Required before historical replay can be trusted for training.

7. Feature retention and compaction
   - Define hot/warm/cold retention windows for feature snapshots, labels,
     rejected outcomes, auto-buy candidates, and bot events.

8. `app.py` decomposition
   - Still the highest structural maintainability project.
   - Start with behavior-preserving extraction of validation/context/risk-check
     helpers behind tests.

## Recommended Next Step

Run the auto-buy live paper lane for at least one clean session, then add an
`auto_buy_outcome_report.py` that labels auto-buy candidates with forward returns
and compares them against TradingView-triggered signals.
