# Trading Bot

Automated AI-assisted trading bot for Alpaca paper/cash-safe trading using TradingView webhook signals, live market context, session momentum, setup classification, and AI decisioning.

> This project is for experimental trading automation and risk-control research. It is not financial advice.

---

## Current Status

As of the latest project state, the bot is operational with:

- Flask webhook server behind Gunicorn, Nginx, and Cloudflare Tunnel
- TradingView alerts from TradingPilotAI V3
- Claude Haiku decision engine
- Alpaca order execution
- SQLite trade/rejection/fill attribution
- Session-aware momentum risk controls
- Live-bias override framework
- Setup policy filtering
- Position momentum monitor with optional auto-sell
- Daily/weekly performance reports
- Cron-based fill polling, market research, summaries, session momentum refresh, and position momentum checks

Repository:

```text
github.com/TiB0n3s/trading-bot

Primary VM:

Host: 192.168.99.250
User: tradingbot
Project path: /home/tradingbot/trading-bot
Infrastructure

Production stack:

Cloudflare Tunnel
        ↓
Nginx reverse proxy
        ↓
Gunicorn
        ↓
Flask app.py webhook server
        ↓
Alpaca / Claude / SQLite

Systemd services:

trading-bot    Flask/Gunicorn webhook server
fill-stream    Alpaca websocket fill listener
cloudflared    Cloudflare tunnel
nginx          Reverse proxy

Project directory:

cd ~/trading-bot

Secrets are stored in:

/etc/trading-bot.env

Permissions should remain:

sudo chmod 600 /etc/trading-bot.env

Secrets should never be placed directly in service files or committed to Git.

Approved Symbols

Current approved symbols:

AAPL
SPY
QQQ
MSFT
NVDA
ORCL
TSCO
TSLA
META
AMD
CVX
XOM
GOOGL
GLD
IWM
AVGO
CRDO
GEV
BE
CAT
VRT
RKLB
RTX
LMT
HWM
VRTX
MRNA
CRSP
V
MA
LLY
LIN
GE

Total:

33 approved symbols
Core Trading Flow

TradingView sends webhook alerts to:

https://trading.tib0n3s.xyz/webhook

The Flask app receives signals shaped roughly like:

{
  "symbol": "NVDA",
  "action": "buy",
  "price": 235.44,
  "source": "TradingPilotAI"
}

Supported actions:

buy
sell

The bot validates the payload, applies pre-checks, optionally calls Claude Haiku, and then routes approved orders through Alpaca.

Execution Modes

The bot supports multiple execution/risk modes through environment config.

Common env flags:

EXECUTION_MODE=paper
LIVE_TRADING_ENABLED=false
ENFORCE_SESSION_MOMENTUM_GATE=true
POSITION_MOMENTUM_AUTO_SELL=true
POSITION_MOMENTUM_SELL_CANDIDATES_ONLY=true

Recommended safety defaults:

LIVE_TRADING_ENABLED=false
POSITION_MOMENTUM_SELL_CANDIDATES_ONLY=true

For cash-safe/live-style deployments, make sure cash-safe controls and max order limits are configured before enabling live trading.

Main Trading Rules

Current core rules include:

Max open positions: 8
Max buy size: 2% of account balance
Bullish/confirmed buy size: up to 2.5%
Max total exposure per symbol: 4%
Daily loss circuit breaker: -3%
Trading window: 9:45 AM – 3:45 PM ET
Cooldown: 15 minutes per symbol/action pair
Sell→buy churn window: 30 minutes
Minimum sell→buy price improvement: 0.5%
Very-high-risk symbols: broker.py halves quantity

Sells are generally allowed even when buy-side gates are restrictive so the bot can reduce exposure.

Buy Signal Gate Order

A BUY signal moves through the following major stages:

Webhook validation
→ webhook event persistence / dedupe
→ market context refresh
→ account state build
→ stale signal check
→ setup observation
→ setup policy
→ cash-safe gates
→ duplicate webhook check
→ symbol override check
→ trend table update
→ market hours check
→ circuit breaker check
→ current position lookup
→ cooldown check
→ sell→buy churn window check
→ sell→buy price improvement check
→ daily symbol buy limit
→ per-symbol exposure cap
→ correlation cluster cap
→ macro risk gate
→ macro max position limit
→ trend confirmation gate
→ fundamental score gate
→ market-bias context injection
→ chase-prevention / entry-quality gate
→ short-term 1-minute momentum
→ add-on momentum gate
→ prediction gate
→ live-bias override
→ hard/soft/live-downgrade bias enforcement
→ prediction block/watch enforcement
→ session momentum gate
→ Claude Haiku decision engine
→ decision consistency guard
→ cash-safe confidence gate
→ low-confidence buy gate
→ second-look market check
→ Alpaca broker order
→ cooldown/recent state persistence
→ trade log
Sell Signal Gate Order

A SELL signal follows a lighter path because sells reduce exposure:

Webhook validation
→ webhook event persistence / dedupe
→ market context refresh
→ account state build
→ stale signal check
→ setup observation skipped/not applicable
→ duplicate webhook check
→ symbol override check
→ trend table update
→ market hours check
→ ghost sell filter
→ current position lookup
→ cooldown check
→ sell trend confirmation
→ Claude Haiku decision engine
→ broker sell path
→ cooldown write
→ recent sell write
→ trade log

Buy-only gates skipped for sells include:

circuit breaker blocking
sell→buy churn
daily buy limit
exposure cap
correlation cap
macro buy block
market bias avoid
chase prevention
prediction gate
session momentum buy gate
low-confidence buy gate
second-look buy checks
Live-Bias Override Framework

Pre-market research is no longer treated as an unconditional early blocker in all cases.

Instead:

market_context.json provides original bias
live features / setup / prediction / momentum update intraday context
_live_bias_override() computes effective intraday bias
effective bias is enforced after prediction evidence exists

Tracked fields:

market_bias_original
market_bias_effective
market_bias_override_reason
avoid_type

Possible effective states include:

avoid_hard
avoid_soft
live_override_buy
live_override_neutral
neutral
buy

Hard avoids remain protective. Soft avoids may be overridden only when live evidence is strong enough.

Market Context

Daily market context is stored in:

market_context.json

Generated from structured brief parsing:

python3 parse_market_brief.py --date YYYY-MM-DD /tmp/market_brief.json

Typical symbol fields:

{
  "bias": "buy",
  "confidence": "medium",
  "reason": "Strong relative strength with supportive macro tape",
  "avoid_type": null,
  "fundamental_score": "bullish",
  "risk_level": "medium",
  "entry_quality": "good_on_pullbacks"
}

For avoid names:

{
  "bias": "avoid",
  "avoid_type": "soft"
}

or:

{
  "bias": "avoid",
  "avoid_type": "hard"
}

The app lazily reloads market_context.json when the file changes.

Setup Policy

Setup policy is active.

The log line should read:

Setup policy evaluated:

Current behavior:

boost   → signal continues with favorable setup context
allow   → signal continues
neutral → signal continues
block   → signal rejected as setup_policy

Example hard-avoid setup label:

avoid_stretched_above_vwap_strength

Example favorable setup labels:

confirmed_near_vwap_recovery
near_vwap_weak_strength_followthrough
above_vwap_strength_continuation

Unknown setup labels are treated as neutral unless explicitly added to policy lists.

Prediction Gate

The prediction gate scores buy quality before Claude.

Inputs include:

trend direction
trend strength
market bias
setup label
setup policy action
short-term momentum direction
short-term momentum percent
consecutive buy count
recent favorable setup memory

The gate can reject weak BUYs before Claude, saving API cost.

Common result fields:

prediction_score
prediction_decision
prediction_reason
Momentum Systems

The project now has two momentum systems.

1. Short-Term Signal Momentum

This is the original event-driven momentum check.

It runs during BUY signal processing.

It fetches recent Alpaca 1-minute bars and computes:

momentum_5m_pct
momentum_15m_pct
direction = rising / falling / flat

Primary direction is based on recent 5-minute movement:

> +0.10% = rising
< -0.10% = falling
otherwise = flat

This feeds:

confidence hints
prediction gate
add-on momentum gate
live-bias override
Claude account_state
2. Session Momentum

Session momentum is continuously refreshed and stored in SQLite.

Script:

session_momentum.py

Table:

session_momentum

It calculates, per symbol:

bar_count
session_open_price
latest_price
session_return_pct
momentum_5m_pct
momentum_15m_pct
momentum_30m_pct
vwap
distance_from_vwap_pct
trend_label
trend_score
reason
updated_at

Trend labels:

strong_uptrend
developing_uptrend
reversal_attempt
rangebound
fading
downtrend
insufficient_data

Manual refresh:

python3 session_momentum.py --all

Via ops helper:

python3 ops_check.py session

Current values can also be viewed through /status.

Session Momentum Gate

Session momentum is now an active BUY risk gate.

Controlled by:

ENFORCE_SESSION_MOMENTUM_GATE=true

The gate can block BUYs when broader session conditions are weak.

High-level rule:

Block BUY if:
  session_label is downtrend
  OR trend_score <= -5

Block BUY if:
  session_label is fading / score <= -2
  AND prediction_score < 8
  AND not bullish/confirmed with boost setup

This helps prevent buying short-term bounces inside broader fading/downtrend sessions.

Rejection category:

session_momentum_gate
Position Momentum Monitor

The bot now includes a proactive position risk monitor that does not require TradingView sell alerts.

Script:

position_momentum_monitor.py

Tables:

position_momentum_checks
position_momentum_actions

Purpose:

Read current Alpaca positions
Read latest session_momentum
Classify held positions as hold / watch / sell_candidate
Persist every check
Optionally auto-sell severe sell candidates

Manual run:

python3 position_momentum_monitor.py

Via ops helper:

python3 ops_check.py position-momentum

Example output:

Symbol Action          Severity         Label            Score    Sess%     15m%     30m%    VWAP%
------ --------------- ---------------- ---------------- ----- -------- -------- -------- --------
LIN    hold            pass             rangebound           0   -0.305   -0.032    0.171    0.082
Position Momentum Auto-Sell

Auto-sell is now available behind environment flags.

Current live controls:

POSITION_MOMENTUM_AUTO_SELL=true
POSITION_MOMENTUM_SELL_CANDIDATES_ONLY=true

Auto-sell only considers positions classified as:

sell_candidate

Current safety layers include:

market must be open
position must be long
session momentum must be fresh
minimum 1-minute bar count required
decision must be sell_candidate
profit/loss-aware guard
minimum hold-time guard
auto-sell cooldown/dedupe
broker.py sell path cancels brackets before selling
position_momentum_actions records submitted auto-sells

Cooldown table:

position_momentum_actions

Auto-sell audit table:

position_momentum_checks

Emergency disable:

sudo sed -i 's/^POSITION_MOMENTUM_AUTO_SELL=.*/POSITION_MOMENTUM_AUTO_SELL=false/' /etc/trading-bot.env
grep POSITION_MOMENTUM_AUTO_SELL /etc/trading-bot.env

Cron scripts reload /etc/trading-bot.env each run, so no service restart is needed for this flag.

Broker Behavior

File:

broker.py

Function:

place_order(symbol, action, position_size_pct, stop_loss_pct, take_profit_pct, risk_level=None, client_order_id=None)

Buy path:

calculates qty from account balance and position_size_pct
applies very_high risk halving
rejects qty < 1
submits market bracket order

Sell path:

fetches existing Alpaca position
rejects non-long qty
cancels open bracket orders for symbol
waits 1 second
re-fetches position and verifies qty
submits market sell

For sell orders, stop/take-profit values are not meaningful and are passed as zero by bot logic where appropriate.

Main Files
app.py

Main Flask webhook server.

Responsibilities:

webhook validation
signal processing
pre-check stack
trend table
market context refresh
setup policy handling
prediction gate
live-bias override
session momentum gate
Claude decision call
broker order routing
trade/rejection logging
/status endpoint
/positions endpoint
/health endpoint
decision_engine.py

Claude Haiku decision engine.

Responsibilities:

construct prompt
send signal/account_state to Claude
parse JSON decision
apply trading rules
return approved/rejected decision

Includes guidance for:

trend table
market bias
live bias override
fundamental score
risk level
entry quality
short-term momentum
session momentum
cash-safe mode
sell handling
broker.py

Alpaca order placement.

Responsibilities:

buy quantity sizing
bracket buy submission
sell position lookup
bracket cancel before sell
market sell submission
cash-mode live guard
very_high risk quantity halving
session_momentum.py

Session-aware momentum refresher.

Responsibilities:

fetch Alpaca 1-minute bars
calculate 5m / 15m / 30m momentum
calculate VWAP distance
classify session trend
upsert session_momentum table
position_momentum_monitor.py

Held-position momentum monitor.

Responsibilities:

read current Alpaca positions
read session_momentum
classify hold/watch/sell_candidate
persist checks
optionally auto-sell severe candidates
dedupe/cooldown auto-sells
parse_market_brief.py

Parses structured daily market research into:

market_context.json

Supports:

bias
avoid_type
confidence
fundamental_score
risk_level
entry_quality
macro context
symbol table parsing
pre_market_research.py

Automated pre-market research script.

Generates structured market context using Claude/web research.

Runs via cron as backup to manual Chrome/Claude brief workflow.

fill_stream.py

Alpaca websocket listener for fills.

Tracks real-time fill updates and writes fill data.

Uses runtime-configured Alpaca base URL.

fill_poller.py

Cron fallback for missed fills.

Runs every 2 minutes.

daily_summary.py

Daily and weekly reports.

Includes:

signal counts
rejection breakdown
orders by symbol
realized P&L
win rate
profit factor
session momentum gate summary

Run:

python3 daily_summary.py
python3 daily_summary.py --week
analytics_report.py

Broader analytics report.

Includes:

execution summary
risk filters
session momentum attribution
performance
per-symbol performance
matched trade attribution
data quality

Run:

python3 analytics_report.py --week
blocked_signal_outcome_report.py

Blocked signal analysis.

Includes:

prediction reasons
setup labels
setup policy actions
effective market bias
original market bias
session momentum labels
session momentum gate rows
recent blocked BUY samples

Run:

python3 blocked_signal_outcome_report.py --date $(date +%F)
ops_check.py

Convenience command runner.

Common commands:

python3 ops_check.py session
python3 ops_check.py position-momentum
python3 ops_check.py blocked
python3 ops_check.py filters
python3 ops_check.py drawdown
db.py

SQLite connection utilities.

Used to centralize DB connection behavior.

market_time.py

Market-hours helpers.

Used for regular-session checks and Eastern-time handling.

SQLite Tables

Key tables include:

trades
cooldowns
recent_sells
matched_trades
session_momentum
position_momentum_checks
position_momentum_actions

Important trade attribution columns include:

macro_regime
risk_multiplier
market_bias
market_bias_effective
market_bias_override_reason
fundamental_score
risk_level
entry_quality
trend_direction
trend_strength
momentum_direction
momentum_pct
session_trend_label
session_trend_score
session_return_pct
session_momentum_5m_pct
session_momentum_15m_pct
session_momentum_30m_pct
session_distance_from_vwap_pct
session_momentum_reason
setup_label
setup_policy_action
prediction_score
prediction_decision
API Endpoints
Health
curl -s "https://trading.tib0n3s.xyz/health" | jq
Status
curl -s "https://trading.tib0n3s.xyz/status?secret=$WEBHOOK_SECRET" | jq

Useful slices:

curl -s "https://trading.tib0n3s.xyz/status?secret=$WEBHOOK_SECRET" \
  | jq '.execution_mode, .market_session, .macro_risk'

Session momentum summary:

curl -s "https://trading.tib0n3s.xyz/status?secret=$WEBHOOK_SECRET" \
  | jq '.session_momentum_gate_enabled, .session_momentum_summary'

Held positions with session momentum:

curl -s "https://trading.tib0n3s.xyz/status?secret=$WEBHOOK_SECRET" \
  | jq '.positions[] | {symbol, session_momentum}'
Positions
curl -s "https://trading.tib0n3s.xyz/positions?secret=$WEBHOOK_SECRET" | jq
Cron Jobs

Current important cron jobs:

*/2 * * * *       fill_poller.py
0 8 * * 1-5      pre_market_research.py
0 16 * * 1-5     daily_summary.py
5 16 * * 5       daily_summary.py --week
*/2 8-15 * * 1-5 session_momentum.py --all
*/2 8-15 * * 1-5 position_momentum_monitor.py

Cron lines that need secrets should source /etc/trading-bot.env:

*/2 8-15 * * 1-5 cd /home/tradingbot/trading-bot && set -a && . /etc/trading-bot.env && set +a && /home/tradingbot/trading-bot/venv/bin/python session_momentum.py --all >> session_momentum.log 2>&1

*/2 8-15 * * 1-5 cd /home/tradingbot/trading-bot && set -a && . /etc/trading-bot.env && set +a && /home/tradingbot/trading-bot/venv/bin/python position_momentum_monitor.py >> position_momentum_monitor.log 2>&1

View crontab:

crontab -l
Log Files

Important logs:

trading_bot.log
fill_stream.log
session_momentum.log
position_momentum_monitor.log

Useful live monitor:

tail -f ~/trading-bot/trading_bot.log \
  | grep --line-buffered "APPROVED\|REJECTED\|ORDER\|Cooldown\|Exposure\|churn\|Trend\|bias\|momentum"

Position momentum monitor:

tail -f ~/trading-bot/position_momentum_monitor.log \
  | grep --line-buffered "AUTO-SELL\|SELL_CANDIDATE\|WATCH\|POSITION MOMENTUM"

Runtime logs should be ignored by Git.

Recommended .gitignore patterns:

*.log
*.log.*
*.gz
session_momentum.log*
position_momentum_monitor.log*
Common Commands

Activate project:

cd ~/trading-bot
source venv/bin/activate
set -a
source /etc/trading-bot.env
set +a

Compile key files:

python3 -m py_compile \
  app.py \
  decision_engine.py \
  broker.py \
  session_momentum.py \
  position_momentum_monitor.py \
  ops_check.py \
  daily_summary.py \
  analytics_report.py \
  blocked_signal_outcome_report.py

Run tests:

python3 run_tests.py

Restart services:

sudo systemctl restart trading-bot
sudo systemctl restart fill-stream

Check services:

sudo systemctl status trading-bot --no-pager -l
sudo systemctl status fill-stream --no-pager -l
Reviewing Session Momentum

All symbols:

python3 ops_check.py session

SQLite:

sqlite3 -cmd ".headers on" -cmd ".mode column" trades.db "
SELECT symbol, updated_at, trend_label, trend_score,
       session_return_pct, momentum_5m_pct, momentum_15m_pct,
       momentum_30m_pct, distance_from_vwap_pct, bar_count, reason
FROM session_momentum
ORDER BY trend_score DESC;
"

Weak names:

sqlite3 -cmd ".headers on" -cmd ".mode column" trades.db "
SELECT symbol, trend_label, trend_score,
       session_return_pct, momentum_5m_pct, momentum_15m_pct,
       momentum_30m_pct, distance_from_vwap_pct, reason
FROM session_momentum
WHERE trend_label IN ('fading', 'downtrend')
ORDER BY trend_score ASC;
"

Strong names:

sqlite3 -cmd ".headers on" -cmd ".mode column" trades.db "
SELECT symbol, trend_label, trend_score,
       session_return_pct, momentum_5m_pct, momentum_15m_pct,
       momentum_30m_pct, distance_from_vwap_pct, reason
FROM session_momentum
WHERE trend_label IN ('strong_uptrend', 'developing_uptrend')
ORDER BY trend_score DESC;
"
Reviewing Position Momentum

Manual check:

python3 position_momentum_monitor.py

Via ops:

python3 ops_check.py position-momentum

Today’s checks:

sqlite3 -cmd ".headers on" -cmd ".mode column" trades.db "
SELECT symbol, action, severity, trend_label, COUNT(*) AS n
FROM position_momentum_checks
WHERE timestamp >= date('now')
GROUP BY symbol, action, severity, trend_label
ORDER BY n DESC;
"

Watch/sell candidates:

sqlite3 -cmd ".headers on" -cmd ".mode column" trades.db "
SELECT timestamp, symbol, action, severity, trend_label, trend_score,
       session_return_pct, momentum_15m_pct, momentum_30m_pct,
       distance_from_vwap_pct, reason
FROM position_momentum_checks
WHERE action IN ('watch', 'sell_candidate')
ORDER BY id DESC
LIMIT 20;
"

Auto-sell audit:

sqlite3 -cmd ".headers on" -cmd ".mode column" trades.db "
SELECT timestamp, symbol, action, severity,
       auto_sell_enabled, order_submitted, order_id, reason
FROM position_momentum_checks
ORDER BY id DESC
LIMIT 20;
"

Auto-sell action cooldowns:

sqlite3 -cmd ".headers on" -cmd ".mode column" trades.db "
SELECT *
FROM position_momentum_actions;
"
Reports

Filter report:

python3 filter_report.py --date $(date +%F)

Blocked signal report:

python3 blocked_signal_outcome_report.py --date $(date +%F)

Session momentum gate rows:

python3 blocked_signal_outcome_report.py --date $(date +%F) \
  | grep -A45 -E "Top session momentum labels|Session momentum gate rows"

Daily summary:

python3 daily_summary.py

Weekly summary:

python3 daily_summary.py --week

Analytics report:

python3 analytics_report.py --week

Session momentum attribution:

python3 analytics_report.py --week \
  | sed -n '/SESSION MOMENTUM ATTRIBUTION/,/PERFORMANCE/p'
Git Workflow

Check changes:

git status --short
git diff --stat

Run tests before commit:

python3 run_tests.py

Stage code only:

git add app.py decision_engine.py broker.py session_momentum.py position_momentum_monitor.py ops_check.py daily_summary.py analytics_report.py blocked_signal_outcome_report.py .gitignore

Commit:

git commit -m "Describe change"

If push is rejected due to non-fast-forward:

git pull --rebase origin live-bias-override-framework
git push origin live-bias-override-framework

Do not force-push unless you intentionally want to overwrite remote commits.

Known Issues / Watch Items

Current known items:

Some TradingView ghost sell signals still occur; ghost_sell filter handles them.
Bracket stop-loss exits are not fully represented as bot-initiated sells in trades.db.
market_context.json must be kept fresh daily.
Session momentum depends on cron successfully loading /etc/trading-bot.env.
Position momentum auto-sell is live and should be monitored closely after rollout.
Startup reconciliation can reveal mismatches between Alpaca positions and trades.db.

Recent reconciliation examples have included:

held in Alpaca but no open position tracked in trades.db
tracked as open in trades.db but not found in Alpaca

These should be reviewed when they occur.

Morning Routine
SSH into the VM.
Activate environment.
Check /status and /positions.
Generate or parse market brief.
Confirm market_context.json.
Refresh/check session momentum.
Confirm cron health.
Watch logs near open.

Commands:

cd ~/trading-bot
source venv/bin/activate
set -a
source /etc/trading-bot.env
set +a

curl -s "https://trading.tib0n3s.xyz/status?secret=$WEBHOOK_SECRET" \
  | jq '.market_session, .macro_risk, .session_momentum_summary'

python3 ops_check.py session
python3 ops_check.py position-momentum

Parse daily market context:

python3 parse_market_brief.py --date YYYY-MM-DD /tmp/market_brief.json

Verify:

jq '.market_date, .macro_sentiment, .symbols | keys | length' market_context.json
Emergency Controls

Disable session momentum buy gate:

sudo sed -i 's/^ENFORCE_SESSION_MOMENTUM_GATE=.*/ENFORCE_SESSION_MOMENTUM_GATE=false/' /etc/trading-bot.env
sudo systemctl restart trading-bot

Disable position momentum auto-sell:

sudo sed -i 's/^POSITION_MOMENTUM_AUTO_SELL=.*/POSITION_MOMENTUM_AUTO_SELL=false/' /etc/trading-bot.env
grep POSITION_MOMENTUM_AUTO_SELL /etc/trading-bot.env

Stop trading bot:

sudo systemctl stop trading-bot

Restart trading bot:

sudo systemctl restart trading-bot

Check errors:

sudo journalctl -u trading-bot -n 120 --no-pager
tail -n 120 ~/trading-bot/trading_bot.log
Development Notes

Before enabling any new gate or execution behavior:

1. Add observe-only logging.
2. Persist attribution to SQLite.
3. Add report visibility.
4. Add tests or smoke tests.
5. Run during market hours in observe-only mode.
6. Review candidates.
7. Add env flag.
8. Enable only after guardrails are verified.

Current philosophy:

Prefer pre-Claude deterministic filters for cost control.
Use Claude only after hard gates and live context are populated.
Keep sell-side controls conservative but able to reduce exposure.
Persist every meaningful reject/action with category prefixes.
Make every new gate observable before making it enforceable.
Test Suite

Targeted tests include:

trend tests
fast-lane buy tests
fast-lane sell tests
FIFO trade matcher tests
live-bias override tests

Run:

python3 run_tests.py

Expected:

[OK] all test file(s) passed
Disclaimer

This bot automates experimental trading decisions in a paper/cash-safe environment. It can make mistakes, reject good trades, approve poor trades, or fail due to third-party APIs, stale data, software bugs, or market conditions.

Use at your own risk.