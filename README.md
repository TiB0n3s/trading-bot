# AI Trading Bot

An automated paper trading system that receives signals from TradingView, evaluates them using Claude AI, and executes approved orders via the Alpaca broker API.

---

## What It Does

- Receives webhook alerts from TradingView (TradingPilotAI V2 indicator)
- Evaluates each signal using Claude Haiku against a strict set of risk rules
- Executes approved buy/sell orders on an Alpaca paper trading account
- Logs all activity to SQLite for performance analysis

---

## Architecture

```
TradingView Alert
      │
      ▼
Cloudflare Tunnel (trading.tib0n3s.xyz)
      │
      ▼
Nginx → Gunicorn → Flask (app.py)
      │
      ├── Webhook validation (secret, symbol whitelist, price sanity)
      ├── Pre-checks (market hours, circuit breaker, ghost sell)
      │
      ▼
Claude Haiku (decision_engine.py)
      │
      ▼
Alpaca Paper Trading (broker.py)
      │
      ▼
trades.db (SQLite)
```

---

## Risk Rules

| Rule | Value |
|---|---|
| Approved symbols | AAPL, SPY, QQQ, MSFT, NVDA, TSLA, META, AMD, ORCL, TSCO |
| Max open positions | 5 |
| Max position size | 2% of account balance per order |
| Max symbol exposure | 4% of account balance |
| Daily loss limit | 3% (hard circuit breaker) |
| Trading hours | 9:45 AM – 3:45 PM Eastern |

---

## Infrastructure

- **Ubuntu VM** at `192.168.99.250` (local desktop)
- **Cloudflare Tunnel** — public HTTPS endpoint
- **Nginx** — reverse proxy
- **Gunicorn** — 3-worker WSGI server
- **systemd** — manages all services (`trading-bot`, `fill-stream`, `cloudflared`, `nginx`)

---

## Key Files

| File | Purpose |
|---|---|
| `app.py` | Flask webhook receiver, validation, pre-checks, DB writes |
| `decision_engine.py` | Claude Haiku signal evaluator |
| `broker.py` | Alpaca order placement (bracket buys, market sells) |
| `fill_stream.py` | Alpaca websocket listener — real-time fill updates |
| `fill_poller.py` | Cron fallback — polls Alpaca for missed fills every 2 min |
| `daily_summary.py` | Daily and weekly P&L reports |
| `trades.db` | SQLite trade history |

---

## Quick Start

**Prerequisites:**
- Python 3.10+
- Alpaca paper trading account
- Anthropic API key (Claude Haiku access)
- TradingView account with webhook alerts

**Setup:**
```bash
git clone https://github.com/TiB0n3s/trading-bot.git
cd trading-bot
python3 -m venv venv
source venv/bin/activate
pip install flask anthropic alpaca-trade-api gunicorn pytz
```

**Environment variables** (store in `/etc/trading-bot.env`, chmod 600):
```
WEBHOOK_SECRET=your_webhook_secret
ANTHROPIC_API_KEY=your_anthropic_key
ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret
```

**Start services:**
```bash
sudo systemctl start trading-bot
sudo systemctl start fill-stream
```

**Check status:**
```bash
curl "http://localhost:5000/status?secret=YOUR_SECRET"
```

---

## Monitoring

| Endpoint | Description |
|---|---|
| `GET /health` | Basic health check |
| `GET /status?secret=` | Live positions, P&L, circuit breaker state |

**Logs:**

| File | Contents |
|---|---|
| `trading_bot.log` | Full application logs (DEBUG level) |
| `signals.log` | Per-signal audit trail |
| `fill_stream.log` | Real-time fill events from Alpaca websocket |
| `fill_poller.log` | Cron poll run output |
| `daily_summary.log` | Daily and weekly P&L summaries |

Log rotation is configured at `/etc/logrotate.d/trading-bot` — daily, 7 days retained, compressed.

---

## Cron Jobs

```
*/2 * * * *   fill_poller.py              — fill price updates
0 16 * * 1-5  daily_summary.py           — daily report at 4 PM CDT
5 16 * * 5    daily_summary.py --week    — weekly report every Friday
```

---

## Full Documentation

See [CLAUDE.md](./CLAUDE.md) for complete technical documentation including all known issues, data flow diagrams, and implementation details.
