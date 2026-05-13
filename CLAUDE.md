# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Bot

```bash
# The bot runs as a systemd service — use this to manage it
sudo systemctl restart trading-bot
sudo systemctl status trading-bot

# Health check (also returns live Alpaca account state)
curl http://localhost:5000/health

# Send a test signal
curl -X POST "http://localhost:5000/webhook?secret=$WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"action": "buy", "symbol": "AAPL", "price": 195.5, "source": "TradingPilotAI"}'

# Operator dashboards (no secret required)
curl http://localhost:5000/status                   # full operational snapshot
curl "http://localhost:5000/positions?secret=$WEBHOOK_SECRET"   # current positions enriched with trend/bias/exposure
```

There are no tests or linting configured.

## Environment / Secrets

All secrets are stored in `/etc/trading-bot.env` (owned `tradingbot:tradingbot`, `chmod 600`):
```
WEBHOOK_SECRET
ANTHROPIC_API_KEY
ALPACA_API_KEY
ALPACA_SECRET_KEY
LOG_LEVEL=INFO    # optional; default INFO. Set DEBUG temporarily for httpcore tracing
```
The systemd service loads this via `EnvironmentFile=/etc/trading-bot.env`. Cron jobs source it explicitly with `set -a; source /etc/trading-bot.env; set +a`.

## Cron Jobs (tradingbot user)

```
*/2 * * * *   fill_poller.py                  — polls Alpaca for order fill updates, writes to trades.db
0 8 * * 1-5   pre_market_research.py          — pre-market web-search research at 8 AM CDT, writes market_context.json
0 16 * * 1-5  daily_summary.py                — end-of-day report at 4 PM CDT, appends to daily_summary.log
5 16 * * 5    daily_summary.py --week         — weekly rollup every Friday at 4:05 PM CDT, appends to daily_summary.log
10 16 * * 1-5 trade_matcher.py                — rebuild matched_trades table at 4:10 PM CDT (backup; daily_summary.py also triggers it inline)
```
Server timezone is `America/Chicago (CDT, -0500)`. Cron uses local time.

## Architecture

Twelve files in regular use, each with a single responsibility:

**`app.py`** — Flask server (gunicorn, 3 workers). Exposes `POST /webhook?secret=<token>`, `GET /health`, `GET /status`, and `GET /positions?secret=<token>`. On startup, each gunicorn worker runs in order:
1. **`_init_db()`** — creates `trades.db` if missing AND idempotently adds the four operational tables (cooldowns / recent_sells / fill_events / matched_trades) and the 11 decision-context columns on `trades` via `ALTER TABLE ADD COLUMN` guarded by `PRAGMA table_info`.
2. **`_startup_reconcile()`** — checks required env vars are set; fetches live Alpaca positions and compares against symbols with a net open position in `trades.db` (FIFO-matched filled orders); logs WARNINGs for discrepancies. Wrapped in outer try/except so a reconciliation failure never prevents startup. Appears 3× in logs (once per worker).
3. **`_build_trend_table()`** — hydrates `_trend_table` and `_signal_history` from `trades.db`. Filters to legitimate signals only (`approved=1 OR rejection_reason LIKE 'confidence_gate:%'`) so hard-rule rejections don't pollute trend computation.
4. **`_hydrate_cooldowns()` / `_hydrate_recent_sells()`** — load operational state from the `cooldowns` and `recent_sells` tables, filtering to entries within their respective windows (15 min / 30 min). This restores cooldown and churn-prevention state across restarts and ensures all 3 gunicorn workers see the same state.
5. **`_load_market_context()`** — reads `market_context.json` and populates `_market_bias`. Lazy mtime refresh: re-runs at the top of every `process_signal` call so a fresh `parse_market_brief.py` or `pre_market_research.py` is picked up without a service restart.

Webhook validates: secret, JSON parseable, action in `[buy/sell]`, symbol in `APPROVED_SYMBOLS`, price numeric and positive, price within ±20% of per-symbol `PRICE_RANGES`. Current symbols and ranges:

| Symbol | Price range | Symbol | Price range |
|--------|-------------|--------|-------------|
| AAPL | 150–500 | TSLA | 100–800 |
| SPY | 400–700 | META | 200–1000 |
| QQQ | 400–900 | AMD | 50–600 |
| MSFT | 200–600 | CVX | 100–260 |
| NVDA | 80–600 | XOM | 80–215 |
| ORCL | 80–300 | TSCO | 20–80 |
| GOOGL | 250–550 | GLD | 250–550 |
| IWM | 180–350 | | |

Dispatches `process_signal()` in a background thread.

### Pre-Claude pipeline (zero API cost)

Every gate writes a categorized rejection row to `trades.db` via `log_rejection()` (Stage 5 attribution refactor). Each rejection's `rejection_reason` carries a `<category>: <detail>` prefix so analytics can group cleanly. The 11 decision-context columns are also populated per row, capturing macro / trend / bias / momentum state at the moment of rejection.

Pre-checks fire in this order:

1. **Lazy market_context refresh** — `_load_market_context()` checks `market_context.json` mtime and reloads `_market_bias` if changed.
2. **Trend table update** — prepends the incoming action to `_signal_history[symbol]` (capped at 10) after `_refresh_signal_history(symbol)` re-pulls the latest from `trades.db` (so all workers agree). Recomputes `_trend_table[symbol]`.
3. **Market hours** — rejects if outside 9:45–15:45 ET or weekend (`pytz.timezone("America/New_York")`). Category: `market_hours`.
4. **Circuit breaker** — rejects if `daily_pnl_pct < -3.0%`. Category: `circuit_breaker`.
5. **Ghost sell filter** — sells only. Skips if no open Alpaca position. Category: `ghost_sell`.
6. **Cooldown** — DB-backed via `_read_cooldown(symbol, action)`. Rejects if same `(symbol, action)` had a successful order within 15 minutes. Cross-worker correct via the `cooldowns` table. Category: `cooldown`.
7. **Sell→buy churn** — buys only, DB-backed via `_read_recent_sell(symbol)`. Two sub-gates: `churn_window` (block if a sell executed within the last 30 minutes) and `churn_price` (block if signal price within 0.5% of the last sell, regardless of time). Backed by the `recent_sells` table.
8. **4% per-symbol exposure cap** — buys only. If `existing_position` (reused from the ghost-sell fetch) value / cash balance ≥ 4%, rejects. Category: `exposure_cap`.
9. **Correlation cluster cap** — buys only. Calls `_cluster_exposure(symbol, balance)` to check the symbol's clusters (`mega_cap_tech` ≤15%, `broad_index` ≤12%, `energy` ≤8%) against current Alpaca positions. Symbols can belong to multiple clusters (e.g. QQQ is in both `mega_cap_tech` and `broad_index`); rejection fires on the first at-cap cluster. Category: `correlation_cap`. Cluster definitions and limits live in `CORRELATION_CLUSTERS` and `CLUSTER_EXPOSURE_LIMITS` next to `APPROVED_SYMBOLS`.
10. **Trend gate** — buys only. Blocks if `direction in ("neutral", "bearish")` *and* `len(_signal_history[symbol]) > 1` (established history — new symbols on first buy pass through). Category: `trend_gate`.
11. **Macro-risk gate** — buys only. `get_macro_risk()` reads the regime from `market_context.json`'s `macro_sentiment` and maps it to a policy (multiplier / position cap / hard block). Two sub-gates: `macro_risk` (capital-preservation regime hard-blocks all buys) and `macro_position_limit` (regime-tightened position count cap, e.g. defensive caps at 4 positions vs the default 8). Result is also injected into `account_state["macro_risk"]` so Claude can reason about the regime.
12. **Market bias gate** — buys only. If `_market_bias[symbol]["bias"] == "avoid"`, rejects with research reason. If `"buy"`, injects `account_state["market_bias"] = "buy"`. Always passes `risk_level` and `entry_quality` through to Claude regardless of bias direction. Category: `market_bias_avoid`.
13. **Chase prevention gate** — buys only. Hard reject if `entry_quality in ("do_not_chase", "avoid_chasing")`. These flags come from the manual brief and indicate extended/parabolic names where fundamentals may be excellent but the entry is tactically poor. Category: `chase_prevention`.
14. **Momentum check** — buys only, fail-open. `get_momentum(symbol, price)` fetches the last 5 one-minute bars via `api.get_bars(..., feed='iex')` (paper account rejects recent SIP queries). Computes `momentum_pct` and tags direction as `rising`/`falling`/`flat` (±0.1% threshold). Injects `account_state["momentum"]`. Sets `account_state["signal_confidence_hint"] = "high"` on rising, `"low"` on falling+`<-0.15%`. Never blocks trading.

Before calling Claude, `account_state["trend_table"] = _trend_table` is injected so Claude receives the full trend picture for all symbols.

The live decision path now also includes setup observation and prediction gating:
- `live_features.py` builds feature snapshots
- `setup_engine.py` classifies setups
- `setup_policy.py` maps setup labels to block/boost/allow/neutral actions
- `app.py` enforces setup-policy and prediction-gate behavior through explicit flags
- `label_features.py` and `prediction_report.py` remain offline evaluation/tuning tools

### Post-Claude check

15. **Confidence gate** — buys only. If Claude returns `confidence: "low"`, the order is skipped. Recorded via `log_rejection()` with category `confidence_gate` (Stage 5 refactor: previously used `log_trade` with `approved=1` which conflated bot-rejected with Claude-approved). Sells bypass this entirely.

After the pipeline completes, approved+filled orders are recorded via `log_trade(data, decision, order_result, account_state=account_state)`. Both `log_trade` and `log_rejection` call `_build_decision_context()` to snapshot the 11 attribution fields (macro_regime, risk_multiplier, market_bias, risk_level, entry_quality, trend_direction, trend_strength, momentum_direction, momentum_pct, correlation_cluster, cluster_exposure_pct) at decision time.

### Sizing pipeline

When Claude approves, `position_size_pct` is multiplied by `account_state["macro_risk"]["risk_multiplier"]` *before* `place_order()` is called. So Claude's recommended 2.5% becomes 1.875% under `caution` regime (×0.75) or 1.25% under `defensive` (×0.50). The broker then halves qty further if `risk_level=="very_high"` (Stage 3 of the execution-quality work). The two multipliers compound — an extended-risk symbol in a defensive macro regime gets a tiny entry.

### Operational state (persisted)

| Module-level dict | DB table | Hydration on startup | Write-through |
|---|---|---|---|
| `_last_order` | `cooldowns` | `_hydrate_cooldowns()` | `_write_cooldown()` after order success |
| `_last_sell` | `recent_sells` | `_hydrate_recent_sells()` | `_write_recent_sell()` after successful sell |
| `_signal_history` | `trades` | `_build_trend_table()` | `_refresh_signal_history(symbol)` per signal |
| `_trend_table` | derived from `_signal_history` | `_build_trend_table()` | recomputed per signal |
| `_market_bias` | `market_context.json` | `_load_market_context()` (lazy refresh) | mtime-driven reload |

Reads in pre-Claude gates go through DB-backed helpers (`_read_cooldown`, `_read_recent_sell`) so all 3 gunicorn workers see the same state. The in-memory dicts are kept as same-worker caches but are no longer the source of truth for gate decisions.

### Operator endpoints

- **`GET /health`** — minimal: `{status, timestamp, account: {balance, buying_power, portfolio_value, status}}`.
- **`GET /status`** — full operational snapshot: timestamp, uptime, market_session, **macro_risk** (current regime + multiplier + caps), account, **positions** (each enriched with trend_direction/strength, market_bias, exposure_cap_hit), position_count, **correlation_exposure** (per-cluster utilization with held members), **pre_check_state** (which symbols would be blocked right now by which gate — cooldowns, churn, exposure cap, trend gate, market bias avoided, all read fresh from DB), **trend_table_summary** (all 15 approved symbols), today_signals counts.
- **`GET /positions?secret=...`** — sorted-by-market-value list of open Alpaca positions enriched per item with: avg_entry, current_price, market_value, unrealized_pl/_pct, exposure_pct, exposure_cap_hit, trend_direction/_strength, market_bias, cooldown_active. Plus a top-level summary (total_positions / max_positions, total_unrealized_pl, account_balance, daily_pnl_pct, market_context_date, macro_sentiment). Calls `_load_market_context()` opportunistically so a fresh brief is reflected immediately.

**`decision_engine.py`** — Calls `claude-haiku-4-5-20251001` to evaluate a signal against account state. Logs account context at DEBUG before the API call. Returns a JSON approval decision with `position_size_pct`, `stop_loss_pct`, `take_profit_pct`, `confidence`. Defaults to `approved: false` on any error. On `JSONDecodeError`, logs the raw Claude response before falling back. The `TRADING_RULES` system prompt has these named sections:
- **HARD RULES** — 2% max position size (2.5% for bullish/confirmed), 4% per-symbol exposure, max 8 positions, symbol whitelist, source=TradingPilotAI.
- **TREND TABLE GUIDANCE** — bullish/confirmed → high confidence + 2.5% sizing; bullish/developing → normal; neutral → cautious; bearish → reject buys.
- **MOMENTUM GUIDANCE** — `account_state["momentum"]` and `signal_confidence_hint` interpretation.
- **MARKET BIAS GUIDANCE** — `account_state["market_bias"] == "buy"` elevates conviction; never overrides bearish trend rejection.
- **EXECUTION QUALITY GUIDANCE** — interprets `risk_level` and `entry_quality`. `do_not_chase`/`avoid_chasing` are filtered pre-Claude (won't appear). `tactical_only` requires bullish/developing+ trend; `hedge_only` caps position size at 1.0%; conditional entries (`good_on_pullbacks`, `good_if_holds_gap`, `good_if_breadth_holds`) reduce position size by ~25% with confidence "medium".

Note: market hours, circuit breaker, and 4% exposure are enforced in `process_signal` before Claude is called — Claude's prompt rules for these are a secondary backstop only.

`get_mock_account_state()` returns live Alpaca data: balance and portfolio value from `get_account()`, open positions and unrealized P&L from `api.list_positions()`, realized P&L from FIFO-matched filled buy/sell pairs in `trades.db` for the current day. `daily_pnl` and `daily_pnl_pct` computed from `unrealized + realized` against start-of-day portfolio value. Each data source is independently wrapped in try/except.

**`broker.py`** — Alpaca paper trading wrapper (`https://paper-api.alpaca.markets`). `place_order(symbol, action, position_size_pct, stop_loss_pct, take_profit_pct, risk_level=None)`:
- **Sell path:** `qty = int(float(existing.qty))` (sign preserved — no `abs()`) → rejects with `"Refusing sell ... is short/zero"` if `qty <= 0` → cancels open bracket orders → sleeps 1s → re-fetches to confirm qty matches → submits market sell. The qty-sign guard prevents the historical short-deepening bug (sell-with-no-long would otherwise open a short at Alpaca).
- **Buy path:** `qty = int(balance * position_size_pct/100 / current_price)`. If `risk_level == "very_high"` AND `qty >= 2`, halves to `qty // 2` (floored at 1; Stage 3 risk multiplier). Submits bracket order with stop-loss and take-profit legs. Returns `None` if qty < 1.
- All `return None` paths log an error identifying the failure.

**`fill_stream.py`** — Standalone async process managed by `fill-stream.service`. Connects to `wss://paper-api.alpaca.markets/stream/` via `alpaca_trade_api.Stream` and subscribes to `trade_updates`. Two-stage handler:
1. **`record_fill_event(event, order)`** — every event (fill / partial_fill / canceled / expired / replaced / new) is persisted to the `fill_events` audit table with `raw_json` for forensic replay. Always runs, regardless of whether the event matches a `trades.db` row.
2. **`update_db()`** — UPDATE on the `trades` row by `order_id`. If 0 rows match AND `side == 'sell'`, calls **`insert_synthetic_exit()`** to insert a synthetic trade row with `rejection_reason="synthetic_bracket_exit: parent_order_id=..."`. This catches autonomous bracket-leg fills (stop-loss or take-profit triggers) so FIFO P&L matching in `analytics_report.py` and `trade_matcher.py` sees the exit. Non-sell unmatched fills get a WARNING.

Reconnects automatically after 30 seconds on any error. Logs to `fill_stream.log`.

**`fill_poller.py`** — Fallback polling safety net. Queries `trades.db` for rows with `order_status IN (pending_new, new, partially_filled)`, calls `api.get_order()` for each, updates `order_status` and `fill_price`. Idempotent. Catches any fills missed during `fill-stream.service` downtime.

**`pre_market_research.py`** — Standalone pre-market research script. Single Claude call to `claude-sonnet-4-6` with the `web_search_20260209` server tool (`max_uses=3`, 120-second per-chunk idle timeout) covering all 15 approved symbols. Uses `client.messages.stream()` to keep the SSE connection alive across long web-search operations. Output JSON has `{market_date, macro_sentiment, macro_summary, symbols: {<sym>: {bias, reason, confidence}}}` with `bias` ∈ `buy/avoid/neutral` per a fixed rubric in the prompt. Cron at 08:00 CDT. Output: `market_context.json` (consumed by `_load_market_context()` lazy-refresh).

**`parse_market_brief.py`** — Manual brief parser. Reads stdin or a file path argument; auto-detects JSON vs free-text/table format:
- **JSON path** — extracts `trading_bias`, `fundamental_score`, `risk_level`, `entry_quality`, `reason` per symbol; macro fields from `macro_summary` block.
- **Text/table path** — regex-based extraction from dense Chrome-paste tables. Time-respecting FIFO heuristic (prefers table-row matches over prose mentions of the same symbol elsewhere).

Output schema matches `pre_market_research.py` plus extra fields (fundamental_score, risk_level, entry_quality). Optional `--date YYYY-MM-DD` overrides the default `market_date` (default = next trading day, skipping weekends; doesn't honor US holidays).

**`macro_risk.py`** — Pure read-only module. `get_macro_risk(base_dir=None)` reads `market_context.json` and maps `macro_regime` (or fallback `macro_sentiment`) to a policy dict: `{macro_regime, risk_multiplier, max_new_positions, block_new_buys, reason}`. Regimes: `risk_on`/`bullish`/`normal` (1.0× / 8 / pass), `caution`/`mixed`/`neutral` (0.75× / 6), `defensive`/`risk_off` (0.50× / 4), `capital_preservation`/`panic`/`crisis` (0.0× / 0 / **block**). Unknown / file missing / parse error → caution defaults (0.75× / 6).

**`daily_summary.py`** — End-of-day reporting. `run(date)` and `run_week(date)` entry points. Both call `rebuild_matched_trades()` first (try/except for graceful degrade) to ensure `matched_trades` is current, then read from it for realized P&L, win rate, profit factor, and per-symbol stats. Rejection breakdown recognizes the Stage 5 category prefixes (`market_hours:`, `cooldown:`, `trend_gate:`, etc.) via a `PREFIX_BUCKETS` map; falls through to legacy substring matching for pre-Stage-5 rows. Includes Claude API cost estimate at Haiku pricing.

CLI usage:
```bash
python daily_summary.py               # today's daily
python daily_summary.py 2026-05-04    # specific date
python daily_summary.py --week        # current/most recent week
python daily_summary.py --week 2026-04-28  # week containing that date
```

**`trade_matcher.py`** — FIFO buy-sell matcher. `match_trades()` walks `trades.db` (with the canonical filter `approved=1 AND action IN ('buy','sell') AND qty NOT NULL AND fill_price NOT NULL AND order_status IN ('filled','partially_filled')`) in time order, popping buys from a per-symbol deque against each sell. Time-respecting: a sell only matches against buys that came BEFORE it. `rebuild_matched_trades()` wipes and reinserts the `matched_trades` table with all 21 columns including the 11 decision-context fields from the entry-side row. Idempotent. Cron at 16:10 CDT (backup; daily_summary.py also calls `rebuild_matched_trades()` inline). CLI usage prints a recent-matches table and open-lots summary.

**`analytics_report.py`** — Read-only analytics across `trades.db`. Sections: EXECUTION (filled buys/sells/synthetic exits, open tracked positions, fill events captured), RISK FILTERS (rejection breakdown by category prefix, with `claude_rejection` bucket for legacy verbose reasons), PERFORMANCE (in-memory FIFO match — uses canonical filter and time-respecting algorithm so it agrees with `matched_trades`), PER-SYMBOL PERFORMANCE, MATCHED-TRADE ATTRIBUTION (queries `matched_trades` for aggregate / per-symbol / `macro_regime` / `trend_direction × trend_strength` breakdowns — most attribution sections empty until trades close after the context migration), DATA QUALITY (compares confirmed-fill view to best-effort FIFO; warns if either gap > 10% and lists rows with NULL fill_price for diagnosis).

CLI usage:
```bash
python analytics_report.py             # today (default)
python analytics_report.py --week      # Mon–Fri of current/most-recent week
python analytics_report.py --all       # entire history
python analytics_report.py --date 2026-05-07
```

**`backfill_missing_fills.py`** — One-off reconciler. Finds rows with `approved=1 AND fill_price IS NULL AND order_id IS NOT NULL`, queries `api.get_order()` for each. If Alpaca returns `status IN (filled, partially_filled)` with a non-null `filled_avg_price`, updates the row's `fill_price` and `order_status`. Never uses `signal_price` as the confirmed fill. `--dry-run` prints what would change without writing.

## Database schema (trades.db)

| Table | Purpose | Key columns |
|---|---|---|
| `trades` | Per-signal audit trail (approvals + rejections + fills + synthetic exits) | `id`, `timestamp`, `symbol`, `action`, `signal_price`, `approved`, `rejection_reason` (with category prefix), `confidence`, `position_size_pct/stop_loss_pct/take_profit_pct`, `order_id`, `order_status`, `qty`, `fill_price`, plus 11 attribution columns: `macro_regime`, `risk_multiplier`, `market_bias`, `risk_level`, `entry_quality`, `trend_direction`, `trend_strength`, `momentum_direction`, `momentum_pct`, `correlation_cluster`, `cluster_exposure_pct` |
| `cooldowns` | Active 15-min cooldowns, cross-worker shared | PK `(symbol, action)`, `last_order_time` |
| `recent_sells` | Active 30-min churn-prevention state, cross-worker shared | PK `symbol`, `last_sell_time`, `last_sell_price` |
| `fill_events` | Forensic audit of every Alpaca trade_update event | `id` AUTOINC, `timestamp`, `event`, `order_id`, `parent_order_id`, `client_order_id`, `symbol`, `side`, `status`, `filled_qty`, `fill_price`, `raw_json` |
| `matched_trades` | FIFO-closed positions with entry-side context | `id` AUTOINC, `symbol`, `entry_timestamp`, `exit_timestamp`, `holding_minutes`, `qty`, `entry_price`, `exit_price`, `realized_pnl`, `realized_pnl_pct`, `won`, plus the 11 attribution columns from the entry row |

`_init_db()` creates all tables with `IF NOT EXISTS` and adds attribution columns via `ALTER TABLE ADD COLUMN` guarded by a `PRAGMA table_info()` check. Safe to re-run on existing DBs without data loss.

## Data Flow

```
TradingPilotAI webhook → app.py validates
  → process_signal() (background thread)
      → _load_market_context() lazy refresh
      → _refresh_signal_history(symbol) + _trend_table update
      → 14 pre-Claude gates (each calls log_rejection on block)
      → decision_engine.py (Claude API)
      → place_order() with risk-multiplier-adjusted sizing
      → log_trade() with full decision context

market_context.json
  ← pre_market_research.py (cron 8 AM CDT, web_search) — automated
  ← parse_market_brief.py — manual paste from Chrome
  → _load_market_context() lazy refresh per signal → _market_bias
  → macro_risk.get_macro_risk() per signal → regime gate + sizing multiplier

fill_stream.py (systemd, real-time)
  → record_fill_event() → fill_events
  → update_db() → trades (fill_price, order_status)
  → if unmatched sell → insert_synthetic_exit() → trades

fill_poller.py (cron every 2min, fallback)
  → trades (fill_price, order_status)

trade_matcher.py / daily_summary.py
  → rebuild_matched_trades() → matched_trades

daily_summary.py / analytics_report.py
  → reads trades + matched_trades + fill_events
```

## Log Rotation

Configured at `/etc/logrotate.d/trading-bot`. Runs automatically via system cron (`/etc/cron.daily`). Settings: daily rotation, 7 compressed archives kept, `copytruncate` (no service restart needed), skips empty files, tolerates missing files. The most-recently rotated file is left uncompressed for one cycle (`delaycompress`) before being compressed on the next run.

## Log Files

| File | Contents |
|---|---|
| `trading_bot.log` | Application logs at LOG_LEVEL (default INFO; bump to DEBUG for httpcore/anthropic SDK tracing) |
| `signals.log` | Structured audit trail: `TIMESTAMP \| SIGNAL: {...} \| DECISION: {...} \| ORDER: {...}` |
| `trades.db` | SQLite — five tables (see schema section above) |
| `fill_stream.log` | Real-time fill events from the websocket stream |
| `fill_poller.log` | Output of each fill_poller.py cron run (fallback) |
| `daily_summary.log` | Appended end-of-day reports |
| `pre_market_research.log` | Output of each 8 AM CDT `pre_market_research.py` cron run |
| `trade_matcher.log` | Output of each 16:10 CDT `trade_matcher.py` cron run |

## Known Issues

1. **Some symbols are over the 4% per-symbol exposure limit** — built up before the rule was added or via concentrated daily accumulation (e.g. AAPL ~5.6% of balance). Further buys on those symbols are rejected by the exposure cap pre-check; existing positions are not automatically reduced.

2. **Ghost sell signals from TradingPilotAI** — META and MSFT continuously receive sell signals for positions that don't exist (~33% of all rejections on a typical day). The `process_signal` ghost-sell pre-check drops these before Claude is called, and `broker.py` has a second layer of defense (rejects sells when qty is short or zero) so a regression in the pre-check can no longer create a phantom short. Root cause is on the TradingPilotAI alert configuration side (likely alerts firing on every bar after an exit condition).

3. **`stop_loss` / `take_profit` in the order result are prices, not percentages** — for sell orders these are both set to `current_price` (meaningless) because Claude returns `0.0` for these fields on sell approvals.

4. **`daytrade_count: 6` with `daytrading_buying_power: 0`** — the paper account has exhausted day trading buying power. Same-day buy+sell cycles may be blocked depending on account state at time of trade.

5. **Intraday bracket-leg fills are now captured** — `fill_stream.py` Stage 2 detects unmatched sell fills and inserts `synthetic_bracket_exit` rows so FIFO P&L matching catches autonomous stop-loss / take-profit triggers. The forensic `fill_events` table records every Alpaca event for replay. Historical gaps (rows from before this code was deployed) won't be backfilled automatically — they appear as orphan parents in `_startup_reconcile` discrepancy warnings until the position closes.

6. **Fundamental analysis is done manually, not via an automated script** — an earlier `fundamental_research.py` was removed because the daily API cost wasn't justified by the rerun frequency and the output never got wired into the trading pipeline. Current workflow: paste Claude's market briefing from the Chrome extension into a file, run `parse_market_brief.py` on it, which produces `market_context.json` consumed by the bias + macro_risk gates. The brief carries fundamentals indirectly (Claude in Chrome reads news/earnings/analyst data and writes per-symbol bias/risk_level/entry_quality/fundamental_score; the parser converts that into the JSON shape the bot already understands).

7. **In-memory state on restart** — gunicorn workers' in-memory dicts (`_last_order`, `_last_sell`, `_signal_history`, `_market_bias`) are still kept as same-worker caches even though DB-backed reads are now authoritative. If you restart the service mid-day, hydration reloads the relevant slices from `cooldowns` / `recent_sells` / `trades.db` / `market_context.json` so behavior is preserved.

8. **Two FIFO performance views in `analytics_report.py`** — the in-memory FIFO (PERFORMANCE section) and the matched_trades-driven view (MATCHED-TRADE ATTRIBUTION) should agree exactly. The DATA QUALITY section flags any divergence > 10% and lists the offending rows. Backfilling `fill_price` via `backfill_missing_fills.py` is the standard remediation when divergence appears.
