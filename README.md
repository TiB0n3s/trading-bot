# AI Trading Bot

An automated paper trading system that receives signals from TradingView, evaluates them through a multi-layer risk pipeline, and executes approved orders via the Alpaca broker API. Claude Haiku serves as the AI decision engine for signal evaluation.

---

## What It Does

- Receives webhook alerts from TradingView (TradingPilotAI V3 indicator, 5-minute charts)
- Runs incoming signals through 13 hard pre-checks before calling Claude — zero API cost on rejections
- Evaluates passing signals using Claude Haiku against a full set of risk, trend, momentum, and market context rules
- Executes approved buy/sell orders on an Alpaca paper trading account
- Persists all trade decisions, fill prices, rejection reasons, and risk attribution to SQLite
- Generates daily and weekly P&L summaries with win rate and profit factor

---

## Architecture

```
TradingView Alert (TradingPilotAI V3, 5m chart)
        │
        ▼
Cloudflare Tunnel → Nginx → Gunicorn (3 workers) → Flask (app.py)
        │
        ├── Webhook validation (secret, symbol whitelist, price sanity)
        │
        ├── Pre-Check Stack (13 gates, zero API cost)
        │     1. Trend table update (DB-backed, cross-worker)
        │     2. Ghost sell filter
        │     3. Market hours (9:45–15:45 ET, pytz DST-aware)
        │     4. Circuit breaker (daily P&L < -3%)
        │     5. Cooldown (15 min per symbol/action, DB-backed)
        │     6. Churn window (30 min post-sell)
        │     7. Churn price (0.5% minimum improvement)
        │     8. Exposure cap (4% per symbol)
        │     9. Correlation cluster cap (mega_cap_tech / broad_index / energy)
        │    10. Trend gate (neutral/bearish blocked)
        │    11. Macro-risk gate (regime-based blocks + position cap tightening)
        │    12. Market bias gate (avoid from pre-market research)
        │    13. Chase prevention (do_not_chase / avoid_chasing entry quality)
        │
        ├── Momentum Check (last 5 one-minute bars via Alpaca IEX)
        │     → injects momentum data + confidence hint into account_state
        │
        ▼
Claude Haiku (decision_engine.py)
        │   TRADING_RULES + TREND + MOMENTUM + MARKET BIAS + EXECUTION QUALITY GUIDANCE
        │
        ├── Confidence Gate (post-Claude, pre-order)
        │
        ▼
Alpaca Paper Trading (broker.py)
        │   bracket buys · market sells · very_high qty halving · sign-preserving sell path
        │
        ▼
trades.db (SQLite) ← fill_stream.py (websocket, real-time fills + synthetic bracket exits)
                   ← fill_poller.py (cron fallback, every 2 min)
```

---

## Risk Rules

| Rule | Value |
|---|---|
| Approved symbols | 15 (see below) |
| Max open positions | 8 (new opens only — sells always approved) |
| Max position size | 2% per order (2.5% for bullish/confirmed trend) |
| Max symbol exposure | 4% of account balance (hard pre-check) |
| Daily loss limit | 3% (hard circuit breaker) |
| Trading hours | 9:30 AM – 4:00 PM Eastern |
| Cooldown | 15 minutes per (symbol, action) pair |
| Churn prevention | 30-minute window + 0.5% minimum price improvement |
| Cluster cap | Limits concentration in mega_cap_tech / broad_index / energy |

---

## Approved Symbols (33)

`AAPL` `SPY` `QQQ` `MSFT` `NVDA` `ORCL` `TSCO` `TSLA` `META` `AMD` `CVX` `XOM` `GOOGL` `GLD` `IWM` `AVGO` `CRDO` `GEV` `BE` `CAT` `VRT` `RKLB` `RTX` `LMT` `HWM` `VRTX` `MRNA` `CRSP` `V` `MA` `LLY` `LIN` `GE`

---

## Key Files

| File | Purpose |
|---|---|
| `app.py` | Flask webhook receiver, all pre-checks, DB writes, `/status` `/positions` `/health` endpoints |
| `decision_engine.py` | Claude Haiku signal evaluator — TRADING_RULES, TREND, MOMENTUM, MARKET BIAS, EXECUTION QUALITY prompts |
| `broker.py` | Alpaca order placement — bracket buys, market sells, bracket cancellation, very_high qty halving |
| `fill_stream.py` | Alpaca websocket listener — real-time fill updates, fill_events audit table, synthetic bracket exit insertion |
| `fill_poller.py` | Cron fallback — polls Alpaca every 2 minutes for missed fills |
| `daily_summary.py` | Daily and weekly P&L reports with win rate and profit factor |
| `pre_market_research.py` | Daily pre-market research via Claude Sonnet 4.6 + web_search (streaming, 3-search budget) |
| `parse_market_brief.py` | Parses Claude Chrome extension market briefs into `market_context.json` — supports JSON and dense table formats |
| `macro_risk.py` | Regime → policy mapper (multipliers, position caps, hard blocks per macro regime) |
| `analytics_report.py` | Date-ranged performance report with execution/risk/attribution sections |
| `trade_matcher.py` | Builds `matched_trades` table via FIFO matching with entry-side context |
| `backfill_missing_fills.py` | One-off — queries Alpaca for NULL fill_price rows |
| `trades.db` | SQLite — trades, matched_trades, cooldowns, recent_sells, fill_events tables |
| `market_context.json` | Daily per-symbol bias/risk_level/entry_quality — loaded lazily by app.py (gitignored) |
| The bot also maintains an observe-and-tune pipeline around `live_features.py`, `label_features.py`, `setup_engine.py`, `setup_policy.py`, and `prediction_report.py` to improve setup/prediction gating over time.
---

## Database Schema Highlights

**trades table** includes full risk attribution columns populated at write time:
`macro_regime` · `risk_multiplier` · `market_bias` · `risk_level` · `entry_quality` · `trend_direction` · `trend_strength` · `momentum_direction` · `momentum_pct` · `correlation_cluster` · `cluster_exposure_pct`

**Supporting tables:** `matched_trades` · `cooldowns` · `recent_sells` · `fill_events`

---

## Cron Jobs

All times in America/Chicago (CDT):

```
*/2 * * * *    fill_poller.py              — fill price updates
0 8 * * 1-5    pre_market_research.py      — daily market research at 8 AM CT
0 16 * * 1-5   daily_summary.py            — end-of-day report at 4 PM CT
5 16 * * 5     daily_summary.py --week     — weekly rollup every Friday 4:05 PM CT
10 16 * * 1-5  trade_matcher.py            — FIFO matched trades rebuild at 4:10 PM CT
```

---

## Infrastructure

- **Ubuntu VM** at `192.168.99.250` (local desktop), user: `tradingbot`
- **Cloudflare Tunnel** — public HTTPS endpoint at `trading.tib0n3s.xyz`
- **Nginx** — reverse proxy
- **Gunicorn** — 3-worker WSGI server
- **systemd** — manages all services: `trading-bot`, `fill-stream`, `cloudflared`, `nginx`
- **Secrets** — stored in `/etc/trading-bot.env` (chmod 600), never in service files
- **Log rotation** — `/etc/logrotate.d/trading-bot` (daily, 7 days, copytruncate)

---

## Monitoring

| Endpoint | Description |
|---|---|
| `GET /health` | Basic health check |
| `GET /status?secret=` | Live positions with trend/bias/exposure, P&L, circuit breaker, macro risk, correlation exposure, pre-check state (DB-backed cross-worker), trend table summary for all 15 symbols |
| `GET /positions?secret=` | Detailed position snapshot with trend, bias, exposure cap hit, cooldown state |

**Live log monitoring:**
```bash
tail -f ~/trading-bot/trading_bot.log | grep --line-buffered \
  "APPROVED\|REJECTED\|ORDER\|Cooldown\|Exposure\|churn\|Trend\|bias\|chase\|momentum\|macro\|cluster"
```

Log level defaults to INFO. Override with `LOG_LEVEL=DEBUG` env var and service restart.

---

## Morning Routine

1. Check `/status` or `/positions` for overnight position state
2. Open Claude Chrome extension → navigate to financial news site → run structured market brief prompt
3. `python parse_market_brief.py --date YYYY-MM-DD /tmp/brief.txt`
4. Bot picks up `market_context.json` automatically via lazy mtime refresh — no restart needed
5. Automated `pre_market_research.py` also runs at 8:00 AM CT as backup
6. Trading window opens at **8:45 AM CT** (9:45 AM ET)

---

## Quick Start

**Prerequisites:** Python 3.10+, Alpaca paper trading account, Anthropic API key, TradingView account

```bash
git clone https://github.com/TiB0n3s/trading-bot.git
cd trading-bot
python3 -m venv venv
source venv/bin/activate
pip install flask anthropic alpaca-trade-api gunicorn pytz
```

**Environment variables** — store in `/etc/trading-bot.env` (chmod 600):
```
WEBHOOK_SECRET=your_webhook_secret
ANTHROPIC_API_KEY=your_anthropic_key
ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret
```

**Start services:**
```bash
sudo systemctl start trading-bot fill-stream
```

---

## Full Documentation

See [CLAUDE.md](./CLAUDE.md) for complete technical documentation including all known issues, data flow details, and implementation notes.
