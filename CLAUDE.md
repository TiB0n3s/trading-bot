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
```

There are no tests or linting configured.

## Environment / Secrets

All secrets are stored in `/etc/trading-bot.env` (owned `tradingbot:tradingbot`, `chmod 600`):
```
WEBHOOK_SECRET
ANTHROPIC_API_KEY
ALPACA_API_KEY
ALPACA_SECRET_KEY
```
The systemd service loads this via `EnvironmentFile=/etc/trading-bot.env`. Cron jobs source it explicitly with `set -a; source /etc/trading-bot.env; set +a`.

## Cron Jobs (tradingbot user)

```
*/2 * * * *   fill_poller.py                  — polls Alpaca for order fill updates, writes to trades.db
0 16 * * 1-5  daily_summary.py                — end-of-day report at 4 PM CDT, appends to daily_summary.log
5 16 * * 5    daily_summary.py --week         — weekly rollup every Friday at 4:05 PM CDT, appends to daily_summary.log
0 8 * * 1-5   pre_market_research.py          — pre-market web-search research at 8 AM CDT, writes market_context.json (read by `_load_market_context` on bot startup)
```
Server timezone is `America/Chicago (CDT, -0500)`. Cron uses local time.

## Architecture

Seven files, each with a single responsibility:

**`app.py`** — Flask server (gunicorn, 3 workers). Exposes `POST /webhook?secret=<token>` and `GET /health`. On startup, each gunicorn worker runs in order:
1. **`_init_db()`** — creates `trades.db` if missing.
2. **`_startup_reconcile()`** — checks that `ANTHROPIC_API_KEY`, `ALPACA_API_KEY`, and `ALPACA_SECRET_KEY` are set (logs an error for each missing key); fetches live Alpaca positions and compares against symbols with a net open position in `trades.db` (FIFO-matched filled orders); logs a WARNING for any symbol Alpaca holds but DB doesn't track and vice versa; closes with a summary line: `"Startup reconciliation: X positions in Alpaca, Y tracked in DB, Z discrepancies"`. Appears 3× in logs (once per worker) — that's expected. Wrapped in outer try/except so a reconciliation failure never prevents the bot from starting.

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

Dispatches `process_signal()` in a background thread. `process_signal` runs checks in this order:

**Pre-Claude checks (zero API cost):**
1. **Trend table update** — prepends the incoming `action` to `_signal_history[symbol]` (capped at 10), recomputes `_trend_table[symbol]`, keeping it current before any decision is made.
2. **Ghost sell filter** — skips sell signals with no open Alpaca position.
3. **Market hours** — rejects if outside 9:45–15:45 ET or if it's a weekend; uses `pytz.timezone("America/New_York")` for automatic DST handling.
4. **Circuit breaker** — rejects if `daily_pnl_pct < -3.0%`.
5. **Cooldown** — rejects if the same `(symbol, action)` pair had a successful order within the last 15 minutes. Tracked in module-level `_last_order` dict (resets on restart). Sells and buys have independent cooldown keys, so a buy cooldown never blocks a sell on the same symbol. Buy signals additionally check `_last_sell[symbol]` for sell→buy churn: if a sell executed within the last 30 minutes the buy is blocked outright; if the sell was more than 30 minutes ago but the current signal price is within 0.5% of the last sell price, the buy is also blocked (prevents re-entering a position at essentially the same price you just exited). `_last_sell` stores `(datetime, signal_price)` and is updated only when a sell `order_result` is returned successfully — both dicts are in-memory and reset on restart, so a buy immediately after a restart can slip through if the prior sell was recent.
6. **4% per-symbol exposure cap** — buy signals only. If `existing_position` is already in scope (reused from the ghost-sell fetch, no extra API call) and `qty * current_price / balance >= 4.0%`, rejects before Claude is called. Uses `account_state["balance"]` (cash balance) as the denominator, not `portfolio_value`, matching the hard rule intent.
7. **Trend gate** — buy signals only. Blocks buys on symbols whose trend `direction` is `neutral` or `bearish`, but only once the symbol has *established history*. Uses `len(_signal_history[symbol]) > 1` as the established-vs-new test: since the trend table is updated at the top of `process_signal` (so every symbol always has an entry by the time pre-checks run), the history length is the reliable signal — length 1 means the just-inserted current signal is the only entry, length 2+ means real prior history. Brand-new symbols like GOOGL/GLD/IWM pass through on their first buy. This is a hard block — previously neutral/bearish buys would reach Claude and be filtered only by the post-Claude confidence gate, costing an API call per rejection. Now they're rejected pre-Claude with a clear audit line showing direction, strength, and consecutive_count.
8. **Momentum check** — buy signals only, fail-open. `get_momentum(symbol, price)` fetches the last 5 one-minute bars via `api.get_bars(symbol, '1Min', start=now-10min, feed='iex')` — `feed='iex'` is mandatory because the paper account's data subscription rejects recent SIP queries with `"subscription does not permit querying recent SIP data"`. Computes `momentum_pct = (last_close - first_close) / first_close * 100`, tags `direction` as `rising`/`falling`/`flat` using a ±0.1% threshold, and returns a dict `{direction, momentum_pct, price_vs_bars, bar_count, last_close}`. The dict is injected into `account_state["momentum"]` so Claude can reason about short-term price action alongside the longer trend table. Additionally injects `account_state["signal_confidence_hint"]`: `"high"` when direction is `rising`, `"low"` when direction is `falling` and `momentum_pct < -0.15%`; flat momentum produces no hint. The hint is consumed by `decision_engine.py`'s prompt (MOMENTUM GUIDANCE section) as a starting confidence before trend rules apply. Wrapped in try/except so a bars-fetch failure logs a WARNING and returns None — momentum data never blocks trading; Claude evaluates on trend alone if momentum is unavailable.
9. **Market bias gate** — buy signals only. Reads `_market_bias`, a module-level dict populated at startup by `_load_market_context()` from `market_context.json` (only loaded if `market_date` matches today in ET). Each entry is `{bias, reason, confidence}`. If the symbol's bias is `"avoid"`, the buy is rejected pre-Claude with the research reason and confidence in the WARNING log line. If `"buy"`, injects `account_state["market_bias"] = "buy"` so Claude elevates confidence/sizing per the `MARKET BIAS GUIDANCE` section in `decision_engine.py`. `"neutral"` or absent entries pass through unchanged — the gate only acts on positive and negative biases, not on the absence of data. **Caveat:** the bias dict is loaded once at module import (i.e. at gunicorn worker startup), so `pre_market_research.py` running at 8:00 AM CDT only takes effect after the next service restart. If you keep the service running across days, restart it manually after the cron completes (or add a daily restart cron).

Before calling Claude, `account_state["trend_table"] = _trend_table` is injected so Claude receives the full trend picture for all symbols.

**Post-Claude check:**

6. **Confidence gate** — if action is `buy` and Claude returns `confidence: "low"`, the order is skipped without calling `place_order`. `log_trade` is still called so the DB records the decision (visible as `approved=1`, `confidence=low`, `order_id=NULL`). Sells bypass this check entirely.

After the pipeline completes, `log_trade` writes to both `signals.log` (pipe-delimited audit line) and `trades.db` (SQLite insert), wrapped in try/except so DB failures never interrupt trading.

**Trend table** (`_trend_table`, `_signal_history`) — module-level dicts, reset on restart and pre-populated from `trades.db` history by `_build_trend_table()` at startup. Each symbol entry: `direction` ("bullish"/"bearish"/"neutral"), `strength` ("confirmed" ≥5 consecutive / "developing" 3-4 / "weak" <3), `consecutive_count`, `last_signal`, `last_time`. Claude uses trend data to: prefer buys on bullish/confirmed symbols (high confidence, up to 2.5% position size), approve bullish/developing normally, treat neutral cautiously (medium/low confidence), and reject buy signals on bearish symbols regardless of other criteria.

**`decision_engine.py`** — Calls `claude-haiku-4-5-20251001` to evaluate a signal against account state. Logs account context (balance, positions, count) at DEBUG before the API call. Returns a JSON approval decision with `position_size_pct`, `stop_loss_pct`, `take_profit_pct`, `confidence`. Defaults to `approved: false` on any error. On `JSONDecodeError`, logs the raw Claude response before falling back. Hard rules enforced via prompt: 2% max position size per order (2.5% allowed for bullish/confirmed trend), 4% max total exposure per symbol (`qty * current_price / balance`), max 8 open positions (new opens only — sells always approved), symbol whitelist, source must be `TradingPilotAI`. Trend table guidance: bullish/confirmed → high confidence + up to 2.5% sizing; bullish/developing → normal approval; neutral → cautious (medium/low confidence); bearish → reject buys. Note: the 9:45–15:45 ET window and the -3% daily loss circuit breaker are enforced in `process_signal` before Claude is called — Claude's prompt rules for these are a secondary backstop only.

`get_mock_account_state()` (name retained for compatibility) now returns live data: balance and portfolio value from Alpaca, open positions and unrealized P&L from `api.list_positions()`, and realized P&L from FIFO-matched filled buy/sell pairs in `trades.db` for the current day. `daily_pnl` and `daily_pnl_pct` are computed from `unrealized + realized` against start-of-day portfolio value. Each data source is independently wrapped in try/except — any failure falls back to 0.0 without blocking the pipeline. `process_signal` in `app.py` calls only `get_mock_account_state()` and `get_position(symbol)`; redundant separate calls to `get_account()` and `api.list_positions()` were removed.

**`broker.py`** — Alpaca paper trading wrapper (`https://paper-api.alpaca.markets`). `place_order()` flow:
- **Sell path:** fetches position qty (sign preserved — no `abs()`) → rejects with `"Refusing sell ... is short/zero, not a long to close"` if `qty <= 0` → cancels all open bracket orders for the symbol → sleeps 1s → re-fetches position to confirm qty matches before proceeding → submits market sell. Returns `None` if position fetch fails (logged as `"Failed to fetch position"` to distinguish API errors from a 404), qty is non-positive, cancel fails, or qty mismatches. The qty-sign guard prevents the sell path from deepening an existing short — historically a sell with no underlying long would open a short at Alpaca, which then polluted account state until the bracket expired (see ghost-sell incident on QQQ 2026-05-04).
- **Buy path:** calculates `qty = int(balance * position_size_pct/100 / current_price)` → submits bracket order with stop-loss and take-profit legs. Returns `None` if qty < 1.
- All `return None` paths have a preceding `logger.error` identifying the failure.

**`fill_stream.py`** — Standalone async process managed by `fill-stream.service`. Connects to `wss://paper-api.alpaca.markets/stream/` via `alpaca_trade_api.Stream` and subscribes to `trade_updates`. On `fill` or `partial_fill` events, updates `order_status` and `fill_price` in `trades.db` in real time using the `order_id`. Non-fill events (canceled, expired, etc.) are logged but don't touch the DB. Reconnects automatically after 30 seconds on any error by recreating the `Stream` object. Logs to `fill_stream.log`.

**`fill_poller.py`** — Fallback polling safety net. Queries `trades.db` for rows with `order_status IN (pending_new, new, partially_filled)`, calls `api.get_order()` for each, updates `order_status` and `fill_price`. Idempotent — skips rows where status and fill_price are unchanged. Catches any fills missed during `fill-stream.service` downtime.

**`daily_summary.py`** — Reporting script. No external dependencies — stdlib only, no API keys required. Two entry points:
- `run(date)` — daily report for a single date (defaults to today). Queries `trades.db` with `WHERE timestamp LIKE 'YYYY-MM-DD%'`.
- `run_week(date)` — weekly report spanning Monday–Friday of the week containing the given date (defaults to current week; rolls back to last completed week if run on a weekend). Queries with a `>=`/`<` date range. On weekends, automatically uses the most recently completed Mon–Fri week.

Both call a shared `_render(rows, header)` function containing all computation: signal totals, approval rate, rejection breakdown, orders by symbol, realized P&L (FIFO buy/sell matching using `fill_price` with `signal_price` as fallback), win rate, best/worst trades, estimated Claude API cost at Haiku pricing. Both append to `daily_summary.log`.

CLI usage:
```bash
python daily_summary.py               # today's daily
python daily_summary.py 2026-05-04    # specific date
python daily_summary.py --week        # current/most recent week
python daily_summary.py --week 2026-04-28  # week containing that date
```

**`pre_market_research.py`** — Standalone pre-market research script. Single Claude call to `claude-sonnet-4-6` with the `web_search_20260209` server tool (`max_uses=10`, 120-second per-chunk idle timeout) covering all 15 approved symbols in one shot. Uses `client.messages.stream()` rather than `messages.create()` because web-search calls can take 30–60+ seconds server-side and the streaming SSE connection avoids socket-timeout drops on long calls. Output JSON has `{market_date, macro_sentiment, macro_summary, symbols: {<sym>: {bias, reason, confidence}}}`; `bias` is `"buy"` / `"avoid"` / `"neutral"` per a fixed rubric in the prompt (earnings today / downgrade / negative news / pre-market down >1% → avoid; pre-market strength + upgrade + sector tailwind → buy). Sources `ANTHROPIC_API_KEY` from `/etc/trading-bot.env` if not already in env so the script runs cleanly under cron. Writes `market_context.json` next to itself; on completion prints a 15-row table (Symbol / Bias / Conf / Reason). Cron job runs it at 08:00 CDT Mon–Fri; output is consumed by `app.py`'s `_load_market_context()` at the next bot startup.

## Data Flow

```
TradingPilotAI webhook → app.py validates → process_signal() (background thread)
  → [pre-check: skip sell if no Alpaca position]
  → [pre-check: reject if outside 9:45–15:45 ET or weekend]
  → [pre-check: reject if daily_pnl_pct < -3.0%]
  → decision_engine.py (Claude API)
  → broker.py place_order() (Alpaca API)
  → log_trade() → signals.log + trades.db

fill_stream.py (systemd, real-time) → Alpaca websocket → trades.db (fill_price, order_status)
fill_poller.py (cron every 2min, fallback) → Alpaca API → trades.db (fill_price, order_status)
daily_summary.py (cron 4PM CDT) → trades.db → daily_summary.log
```

## Log Rotation

Configured at `/etc/logrotate.d/trading-bot`. Runs automatically via system cron (`/etc/cron.daily`). Settings: daily rotation, 7 compressed archives kept, `copytruncate` (no service restart needed), skips empty files, tolerates missing files. The most-recently rotated file is left uncompressed for one cycle (`delaycompress`) before being compressed on the next run.

## Log Files

| File | Contents |
|---|---|
| `trading_bot.log` | Full application logs at DEBUG level (verbose — includes httpcore/anthropic SDK debug output) |
| `signals.log` | Structured audit trail: `TIMESTAMP \| SIGNAL: {...} \| DECISION: {...} \| ORDER: {...}` |
| `trades.db` | SQLite — same data as signals.log plus fill_price updated by fill_poller |
| `fill_stream.log` | Real-time fill events from the websocket stream |
| `fill_poller.log` | Output of each fill_poller.py cron run (fallback) |
| `daily_summary.log` | Appended end-of-day reports |
| `pre_market_research.log` | Output of each 8 AM CDT `pre_market_research.py` cron run (logger output + the 15-row summary table) |

## Known Issues

1. **AAPL is over the 4% per-symbol exposure limit** — 18 shares × ~$283 ≈ $5,093 (~5.8% of balance), built up before the rule was added. Further AAPL buys will be rejected by Claude but the existing position is not automatically reduced. Current open positions as of 2026-05-06 morning: AAPL (5.8%), MSFT (3.3%), AMD (2.4%), ORCL (1.7%), META (1.4%) — 5 positions total. QQQ and TSLA closed overnight via end-of-day bracket order expiry/cancellation. TSCO `PRICE_RANGES` updated from `(100, 400)` to `(20, 80)` after stock was found trading ~$33 — signals were being incorrectly rejected by the price sanity check.

2. **Ghost sell signals from TradingPilotAI** — META and MSFT continuously receive sell signals for positions that don't exist. The `process_signal` pre-check drops these before Claude is called, and `broker.py` now has a second layer of defense (rejects sells when qty is short or zero) so a regression in the pre-check can no longer create a phantom short. Root cause is still on the TradingPilotAI alert configuration side (likely alerts firing on every bar after an exit condition rather than once).

3. **`stop_loss` / `take_profit` in the order result are prices, not percentages** — for sell orders these are both set to `current_price` (meaningless) because Claude returns `0.0` for these fields on sell approvals.

4. **`daytrade_count: 6` with `daytrading_buying_power: 0`** — the paper account has exhausted day trading buying power. Same-day buy+sell cycles may be blocked depending on account state at time of trade.

5. **Intraday stop-loss fills have no trades.db record** — bot-initiated sells are captured correctly by `fill_stream.py` in real time. Bracket take-profit legs expiring unfilled at market close is normal (they appear as `expired`/`canceled` events in `fill_stream.log`). The true gap is if a bracket stop-loss leg fires intraday autonomously (i.e. price drops to the stop level without the bot sending a sell signal) — in that case Alpaca fills the stop order but no row exists in `trades.db` to update, so the exit goes unrecorded and daily P&L will be understated by that amount.

6. **Fundamental analysis is now done manually, not via an automated script** — an earlier attempt at automating per-symbol fundamental research with `fundamental_research.py` (single Sonnet 4.6 call with `web_search_20260209`) was removed because the API cost wasn't justified by daily rerun frequency and the output never got wired into the trading pipeline. The current workflow is: paste Claude's market briefing from the Chrome extension into a text file, run `parse_market_brief.py` on it, which produces `market_context.json` consumed by the existing market-bias gate (pre-check #9). This sources fundamentals indirectly — Claude in Chrome reads news/earnings/analyst data and writes the per-symbol bias; the parser converts that into the same JSON shape the bot already understands. No automated fundamental-only feed exists.
