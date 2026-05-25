# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

The project is an automated AI-assisted trading bot. It currently runs in paper trading with layered safety controls, pre-market intelligence, event scoring, prediction reporting, and observe-only strategy validation. Do not change live trading behavior unless explicitly instructed.

---

## Current Project Status

The bot is operational in paper trading.

Recent completed roadmap items:

- `/status` exposes read-only `symbol_intelligence`.
- `prediction_validation_report.py` exists.
- `ops_check.py prediction-validation DATE` works.
- `next_trading_date.py` uses holiday-aware market calendar helpers from `market_time.py`.
- `market_context.json` validation uses the expected trading session, so weekend/holiday context can target the next market day.
- `export_ml_dataset.py` can write an audit manifest with `--manifest-output`.
- `ml_platform` has a staged observe-only integration lane through `staged-readiness`.
- `retraining-readiness` reports current blockers and never promotes automatically.
- `ml/models/similarity_v0/` is research-only metadata with no trained artifact.
- `run_staged_tests.py` runs ahead-of-live staged integration tests separately from current behavior tests.
- `broker.py` has validation/unit coverage for core order-flow boundaries.
- `broker.py` now polls for Alpaca bracket-order cancellation before market
  sells instead of assuming cancellation completes after a fixed sleep.
- `ops/db_connection_audit.py` reports manual SQLite connection assignments for gradual cleanup.
- `db_migrations.py` tracks idempotent schema migrations.
- `feature_snapshots` includes ML leakage/audit fields:
  `feature_available_at`, `feature_generated_at`, `feature_age_seconds`,
  `source`, `is_stale`, and `staleness_reason`.
- Migrations are manual before deploy/restore, but pending migrations are
  surfaced by `morning_check.py`, `ops_check.py premarket`, and
  `ops_check.py migration-status`.
- App startup no longer owns schema `ALTER TABLE` migration work.
- Webhook/status secrets should use `X-Webhook-Secret` or
  `Authorization: Bearer ...`; query-string secrets are legacy fallback only.
- Prediction gate mode defaults to warn-only until labeled paper-session
  outcomes justify promotion to hard blocking.
- The prediction layer is observe-only and does not modify trade decisions.
- The intelligence pipeline is staged for the next live paper-trading session.

Current roadmap posture:

```text
Validate intelligence pipeline during live paper session first.
Expose and report prediction data.
Do not use predictions as live risk gates yet.
Safety Principles

This repo controls an automated trading system. Treat all changes as potentially high impact.

Safe changes

Prefer these while the market is closed:

Read-only reports
Operator dashboards
Validation scripts
Documentation
Cron/date targeting fixes
Schema-safe migrations
Non-behavioral refactors
Smoke-test wrappers
Risky changes

Avoid these unless the user explicitly asks and understands the behavior change:

Order execution logic
Broker behavior
Position sizing
Risk gates
Claude prompt policy
Webhook routing
Market-hours logic
Live/cash-mode behavior
Any prediction-driven trade blocking or sizing
Prediction layer rule

The prediction layer must remain observe-only until enough paper-session validation exists.

Do not convert these into live gates without explicit instruction:

prediction_score
probability_of_profit
expected_pnl
timing_score
recommended_entry_timing
trend_score
trend_label
trend_regime

ML platform rule

The ML platform is allowed to be one step ahead of live behavior only in staged
or observe-only paths. Do not import staged ML integration into `app.py`
webhook, `broker.py`, order execution, or hard risk-control paths without
explicit instruction.

Current staged/audit commands:

python3 run_staged_tests.py
python3 -m ml_platform.cli staged-readiness --start-date 2026-05-26 --end-date 2026-05-26 --candidate-model similarity_v0 --prediction-symbol AAPL
python3 -m ml_platform.cli retraining-readiness --start-date 2026-05-26 --end-date 2026-05-26 --trading-sessions-observed 0
python3 export_ml_dataset.py --date 2026-05-26 --output /tmp/ml_dataset_2026-05-26.csv --manifest-output /tmp/ml_dataset_2026-05-26.manifest.json

These commands are read-only with respect to `trades.db`, broker state, orders,
position sizing, and risk controls. `similarity_v0` is metadata-only until an
operator explicitly promotes a real artifact through review.

Correct roadmap path:

observe-only
→ validation report
→ warn-only
→ soft modifier
→ possible live gate later
Environment

Production path:

cd /home/tradingbot/trading-bot
source venv/bin/activate

Secrets:

/etc/trading-bot.env

Never commit secrets. Do not add API keys to source files, service files, README, or examples.

Expected secrets/env values include:

WEBHOOK_SECRET
ANTHROPIC_API_KEY
ALPACA_API_KEY
ALPACA_SECRET_KEY
LOG_LEVEL
EXECUTION_MODE
LIVE_TRADING_ENABLED

Cron jobs that need secrets should source the env file:

set -a && . /etc/trading-bot.env && set +a
Services

Systemd services:

trading-bot
fill-stream
cloudflared
nginx

Common service commands:

sudo systemctl status trading-bot --no-pager
sudo systemctl restart trading-bot

sudo systemctl status fill-stream --no-pager
sudo systemctl restart fill-stream

sudo systemctl status cloudflared --no-pager
sudo systemctl status nginx --no-pager

Do not restart services unnecessarily during active market hours unless fixing an urgent operational issue.

Core Architecture
TradingView alert
  → Cloudflare Tunnel
  → Nginx
  → Gunicorn
  → Flask app.py
  → pre-Claude risk stack
  → Claude Haiku decision_engine.py
  → broker.py
  → Alpaca paper account
  → fill_stream.py / fill_poller.py
  → trades.db
  → reports / intelligence / validation
Important Runtime Files
app.py

Main Flask/Gunicorn webhook app.

Key routes:

POST /webhook
GET  /health
GET  /status
GET  /positions
GET  /debug/symbol/<SYMBOL>

Responsibilities:

Validate webhook secret.
Validate incoming TradingView signal payloads.
Enforce approved symbols and price sanity checks.
Apply pre-Claude risk gates.
Build account state.
Call Claude decision engine.
Submit orders via broker.
Persist trades/rejections/fill metadata.
Expose operator dashboards.

The /status route now includes:

symbol_intelligence

This block is read-only and sourced from daily_symbol_predictions.

decision_engine.py

Claude Haiku decision engine.

It receives:

signal data
account state
trend table
momentum
macro risk
market bias
risk level
entry quality

It returns strict JSON:

{
  "approved": true,
  "reason": "reason",
  "position_size_pct": 1.5,
  "stop_loss_pct": 0.5,
  "take_profit_pct": 1.5,
  "confidence": "high"
}

On API errors or JSON parse errors, it rejects safely.

Do not loosen the system prompt without explicit approval.

broker.py

Alpaca execution wrapper.

Buy behavior:

Calculates quantity from balance and position_size_pct.
Uses latest Alpaca trade price.
Rejects if quantity rounds to zero.
Applies very_high risk quantity reduction.
Places bracket buys.

Sell behavior:

Fetches current Alpaca position.
Refuses sell if position quantity is zero or short.
Cancels open bracket orders.
Confirms available quantity after cancel.
Places market sell.

Do not change sell safety guards casually.

Broker boundary work:

- Validate and normalize symbol/action/sizing inputs before API calls.
- Invalid order requests should fail closed and return `None`.
- Preserve broker behavior unless explicitly asked to change execution policy.
- Keep unit coverage in `tests/test_broker.py` when modifying order logic.

exceptions.py

Structured exception types for expected boundaries:

ValidationError
BrokerError
BrokerAuthError
BrokerRateLimitError
BrokerTransientError
DataAccessError

fill_stream.py

Alpaca websocket fill listener.

Responsibilities:

Records every trade update event in fill_events.
Updates matching rows in trades.
Inserts synthetic exit rows for unmatched bracket sell fills.

Managed by:

sudo systemctl status fill-stream --no-pager
fill_poller.py

Fallback order fill reconciler.

Runs through cron every two minutes. Polls Alpaca for pending/new/partially-filled orders and updates trades.

market_time.py

Shared market-time helpers.

Responsibilities:

Eastern time helpers.
Market session labels.
Market-hours checks.
Holiday-aware trading-day helpers.
Shared next_trading_date().
Expected market_context trading-session date helper.

Keep calendar/date logic here rather than duplicating it across scripts.

next_trading_date.py

Small CLI wrapper around market_time.next_trading_date().

Usage:

python3 next_trading_date.py
python3 next_trading_date.py --from-date 2026-05-22

Used by after-hours/weekend cron jobs to target the next valid market session.

Approved Symbol Universe

Current symbol universe is maintained in symbols_config.py.

The current intelligence/reporting universe includes:

AAPL
ABBV
AMD
ASML
AVGO
BE
CAT
COST
CRDO
CRM
CRSP
CVX
GE
GEV
GLD
GOOGL
HWM
IWM
KO
LIN
LLY
LMT
MA
META
MRK
MRNA
MSFT
NFLX
NVDA
ORCL
QQQ
RKLB
RTX
SPY
TSCO
TSLA
UNH
V
VRT
VRTX
XOM

Do not hardcode approved symbols in prompts or reports if symbols_config.py can be used instead.

Database

Database path:

/home/tradingbot/trading-bot/trades.db

Important tables:

trades
matched_trades
fill_events
webhook_events
cooldowns
recent_sells
daily_symbol_context
daily_symbol_events
daily_symbol_predictions
historical_signal_outcomes
historical_trade_outcomes
historical_trend_context
session_momentum
position_momentum_actions
position_momentum_checks

Use db.get_connection() for SQLite connections. It applies row factory, WAL mode, busy timeout, and foreign keys.

List tables:

sqlite3 trades.db ".tables"

Check intelligence row counts:

TARGET_DATE=$(python3 next_trading_date.py)

sqlite3 trades.db "
SELECT 'context' AS table_name, COUNT(*)
FROM daily_symbol_context
WHERE market_date = '$TARGET_DATE'
UNION ALL
SELECT 'events', COUNT(*)
FROM daily_symbol_events
WHERE market_date = '$TARGET_DATE'
UNION ALL
SELECT 'predictions', COUNT(*)
FROM daily_symbol_predictions
WHERE market_date = '$TARGET_DATE';
"
Pre-Claude Risk Stack

The app applies a large stack of checks before Claude is called.

Current checks include:

webhook secret validation
payload validation
approved symbol validation
price sanity/range validation
duplicate webhook protection
operator symbol overrides
market-hours check
daily loss circuit breaker
ghost sell filter
cooldown check
sell-to-buy churn prevention
daily symbol buy limit
per-symbol exposure cap
correlation cluster cap
trend confirmation gate
macro-risk gate
macro position limit
fundamental score gate
market bias avoid gate
chase prevention gate
momentum check

After Claude:

confidence gate
broker-adjacent second-look check
order placement

Most rejections are written to trades.db with category prefixes.

Important rejection categories:

market_hours
duplicate_webhook
symbol_override
circuit_breaker
ghost_sell
cooldown
churn_window
churn_price
daily_symbol_buy_limit
exposure_cap
correlation_cap
trend_confirmation
macro_risk
macro_position_limit
fundamental_score
market_bias_avoid
chase_prevention
confidence_gate

Preserve category prefixes when adding rejection paths so reporting stays reliable.

Core Risk Rules

Current operating rules include:

Paper trading by default
Maximum open positions controlled by macro regime
Normal/risk-on max positions: 12
Caution max positions: 8
Defensive max positions: 5
Capital preservation max positions: 0
Per-symbol exposure cap: 4%
Daily loss circuit breaker: -3%
Cooldown: 15 minutes per symbol/action
Sell-to-buy churn window: 30 minutes
Sell-to-buy price improvement: 0.5%
Trend confirmation: 3 consecutive BUY alerts before BUYs
Market-hours enforcement in Eastern Time

Sells must remain allowed through many buy-side gates so the bot can reduce exposure.

Intelligence Pipeline

The bot maintains daily symbol intelligence.

Main tables:

daily_symbol_context
daily_symbol_events
daily_symbol_predictions
historical_signal_outcomes
historical_trade_outcomes
historical_trend_context

Main scripts:

pre_market_research_data.py
collect_and_score_events.py
apply_event_scores.py
predict_symbol_outcomes.py
intelligence_context_report.py
event_attribution_report.py
intelligence_prediction_report.py
trend_context_report.py
prediction_validation_report.py

Daily flow:

pre_market_research_data.py
  → daily_symbol_context

collect_and_score_events.py
  → daily_symbol_events
  → apply event aggregates to daily_symbol_context
  → optionally run predictions

predict_symbol_outcomes.py
  → daily_symbol_predictions

/status
  → symbol_intelligence

prediction_validation_report.py
  → validate predictions against later outcomes
Prediction Layer

Prediction fields include:

prediction_score
probability_of_profit
probability_of_approval
probability_of_order
expected_pnl
expected_win_rate
confidence
sample_size
reason
timing_score
recommended_entry_timing
recommended_exit_timing
historical_timing_sample_size
timing_reason
trend_score
trend_label
trend_regime
trend_confidence
trend_similarity_sample_size
trend_reason

Prediction confidence is expected to remain low or very low until more clean live paper sessions accumulate.

Do not treat predictions as proven until validated.

/status Intelligence

/status contains a read-only symbol_intelligence block.

Example structure:

{
  "symbol_intelligence": {
    "available": true,
    "market_date": "2026-05-26",
    "symbol_count": 41,
    "observe_only": true,
    "symbols": {
      "AAPL": {
        "prediction_score": 53.93,
        "probability_of_profit": null,
        "probability_of_order": null,
        "expected_pnl": null,
        "expected_win_rate": null,
        "prediction_confidence": "very_low",
        "prediction_decision": "observe_only",
        "sample_size": 0,
        "prediction_reason": "...",
        "timing_score": 62,
        "recommended_entry_timing": "prefer_wait_for_confirmation",
        "recommended_exit_timing": null,
        "historical_timing_sample_size": 0,
        "timing_reason": "...",
        "trend_score": 64,
        "trend_label": "confirmed_uptrend",
        "trend_regime": "bullish",
        "trend_confidence": "high",
        "trend_similarity_sample_size": 0,
        "trend_reason": "...",
        "updated_at": "..."
      }
    }
  }
}

Validation:

set -a
. /etc/trading-bot.env
set +a

curl -s -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  "https://trading.tib0n3s.xyz/status" \
  | jq '.symbol_intelligence | {
      available,
      market_date,
      symbol_count,
      observe_only,
      sample_symbols: (.symbols | keys[:5])
    }'

Spot-check:

curl -s -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  "https://trading.tib0n3s.xyz/status" \
  | jq '.symbol_intelligence.symbols.AAPL'
Operator Check Wrapper

ops_check.py wraps common operational reports.

Usage:

python3 ops_check.py morning
python3 ops_check.py positions
python3 ops_check.py alignment
python3 ops_check.py adaptive
python3 ops_check.py filters
python3 ops_check.py drawdown
python3 ops_check.py post
python3 ops_check.py intelligence
python3 ops_check.py events
python3 ops_check.py context
python3 ops_check.py learning
python3 ops_check.py predictions
python3 ops_check.py signal-lessons
python3 ops_check.py trends
python3 ops_check.py prediction-validation
python3 ops_check.py historical-backfill START_DATE END_DATE
python3 ops_check.py all

Next-session readiness:

cd ~/trading-bot
source venv/bin/activate

TARGET_DATE=$(python3 next_trading_date.py)
echo "$TARGET_DATE"

python3 ops_check.py intelligence "$TARGET_DATE"
python3 ops_check.py events "$TARGET_DATE"
python3 ops_check.py predictions "$TARGET_DATE"
python3 ops_check.py trends "$TARGET_DATE"
python3 ops_check.py prediction-validation "$TARGET_DATE"
python3 ops/db_connection_audit.py
python3 db_migrations.py status

Current tracked migrations cover feature leakage/audit fields,
`rejected_signal_outcomes`, webhook-event lifecycle/status columns, and trade
decision-context columns that used to be added during app startup.

Staged ML/ahead-of-live checks:

python3 run_staged_tests.py
python3 -m ml_platform.cli staged-readiness \
  --start-date "$TARGET_DATE" \
  --end-date "$TARGET_DATE" \
  --candidate-model similarity_v0 \
  --prediction-symbol AAPL \
  --output /tmp/staged_ml_readiness_"$TARGET_DATE".json
python3 -m ml_platform.cli retraining-readiness \
  --start-date "$TARGET_DATE" \
  --end-date "$TARGET_DATE" \
  --trading-sessions-observed 0 \
  --output /tmp/retraining_readiness_"$TARGET_DATE".json
Prediction Validation Report

prediction_validation_report.py is read-only.

Usage:

python3 prediction_validation_report.py
python3 prediction_validation_report.py 2026-05-26
python3 prediction_validation_report.py --date 2026-05-26
python3 ops_check.py prediction-validation 2026-05-26

Before the session, expected state:

Predictions          : 41
Symbols with signals : 0
Symbols with trades  : 0
Symbols with matches : 0

After the session, it should help answer:

Did high prediction_score symbols outperform low-score symbols?
Did timing recommendations match actual outcomes?
Did trend labels identify risk?
Did weak/negative setups lose, get blocked, or avoid orders?
Common Reports
Morning readiness
python3 ops_check.py morning
Position review
python3 ops_check.py positions
Market alignment
python3 ops_check.py alignment
Adaptive confirmation report
python3 ops_check.py adaptive
Filter effectiveness
python3 ops_check.py filters $(date +%F)
python3 filter_report.py --date 2026-05-26
python3 filter_report.py --week
Drawdown report
python3 ops_check.py drawdown $(date +%F)
Post-session check
python3 ops_check.py post $(date +%F)
Intelligence context
python3 ops_check.py intelligence 2026-05-26
Event attribution
python3 ops_check.py events 2026-05-26
Prediction report
python3 ops_check.py predictions 2026-05-26
Trend context
python3 ops_check.py trends 2026-05-26
Prediction validation
python3 ops_check.py prediction-validation 2026-05-26
Daily Summary and Analytics

Daily summary:

python3 daily_summary.py
python3 daily_summary.py 2026-05-26
python3 daily_summary.py --week

Analytics:

python3 analytics_report.py
python3 analytics_report.py --date 2026-05-26
python3 analytics_report.py --week
python3 analytics_report.py --all

Trade matcher:

python3 trade_matcher.py

Backfill fills:

python3 backfill_missing_fills.py --dry-run
python3 backfill_missing_fills.py
Cron Jobs

Cron runs as tradingbot.

View cron:

crontab -l

Important cron categories:

fill_poller.py
pre_market_research_data.py
collect_and_score_events.py --apply-context --predict
daily_summary.py
daily_summary.py --week
trade_matcher.py
rolling_momentum.py
session_momentum.py
position_momentum_monitor.py
run_position_manager.sh
run_after_close_learning.sh
portfolio replacement / rotation reports
after-hours event collection
weekend event collection

Cron jobs that use APIs should source:

set -a && . /etc/trading-bot.env && set +a

After-hours and weekend event collection should use:

TARGET_DATE=$(python3 next_trading_date.py)

next_trading_date.py is holiday-aware through market_time.py.

Market Calendar

Use market_time.py for shared market calendar logic.

Do not duplicate holiday logic in random scripts.

Relevant helpers:

now_et()
is_market_hours()
market_session()
is_market_holiday()
is_trading_day()
next_trading_date()

Test examples:

python3 next_trading_date.py --from-date 2026-05-22
python3 next_trading_date.py --from-date 2026-05-23
python3 next_trading_date.py --from-date 2026-05-24
python3 next_trading_date.py --from-date 2026-05-25

Memorial Day 2026 should resolve to:

2026-05-26
Logs

Common logs:

trading_bot.log
fill_stream.log
fill_poller.log
pre_market_research.log
event_collection.log
daily_summary.log
after_close_learning.log
position_manager.log
portfolio_rotation.log
rolling_momentum.log
session_momentum.log
position_momentum_monitor.log

Tail app log:

tail -f trading_bot.log

Useful filtered tail:

tail -f ~/trading-bot/trading_bot.log \
  | grep --line-buffered "APPROVED\|REJECTED\|ORDER\|Cooldown\|Exposure\|churn\|Trend\|bias\|chase\|momentum\|prediction"
Health Checks

Basic app health:

curl http://localhost:5000/health

Remote status:

set -a
. /etc/trading-bot.env
set +a

curl -s -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  "https://trading.tib0n3s.xyz/status" | jq

Positions:

curl -s -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  "https://trading.tib0n3s.xyz/positions" | jq

Debug symbol:

curl -s -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  "https://trading.tib0n3s.xyz/debug/symbol/AAPL" | jq
Development Workflow

Activate:

cd ~/trading-bot
source venv/bin/activate

Compile changed files:

python3 -m py_compile app.py broker.py decision_engine.py

Compile specific new reports:

python3 -m py_compile prediction_validation_report.py ops_check.py market_time.py next_trading_date.py

Compile all:

python3 -m compileall .

Git status:

git status --short

Commit:

git add <files>
git commit -m "Message"

Restart app after runtime app changes:

sudo systemctl restart trading-bot
sudo systemctl status trading-bot --no-pager

Do not restart just for read-only report changes unless required.

Testing Pattern for Code Changes

Preferred patch flow:

1. Backup file with timestamp.
2. Patch file.
3. Run py_compile.
4. Run script/report smoke test.
5. If app.py changed, restart trading-bot.
6. Validate endpoint/report.
7. Commit.

Example:

cp app.py app.py.bak_change_name_$(date +%Y%m%d_%H%M%S)

python3 -m py_compile app.py

sudo systemctl restart trading-bot
sudo systemctl status trading-bot --no-pager

git status --short
git add app.py
git commit -m "Describe change"
Documentation Expectations

When changing behavior, update:

README.md
CLAUDE.md
Relevant script docstrings
Any operator command examples

When adding a new report, consider wiring it into:

ops_check.py
README.md
CLAUDE.md
Roadmap
2. Validate during next real paper-trading session

Status: Ready.

Need to confirm:

8:00 pre-market data job creates daily_symbol_context
8:05 event collector applies context and runs --predict
daily_symbol_predictions exists before trading
post_session_check includes prediction/timing/trend reports
prediction_score correlates at least directionally with outcomes

Useful commands:

TARGET_DATE=$(python3 next_trading_date.py)

python3 ops_check.py intelligence "$TARGET_DATE"
python3 ops_check.py events "$TARGET_DATE"
python3 ops_check.py predictions "$TARGET_DATE"
python3 ops_check.py trends "$TARGET_DATE"
python3 ops_check.py prediction-validation "$TARGET_DATE"
3. Add prediction/timing/trend fields to /status

Status: Complete.

/status now includes read-only symbol_intelligence.

4. Build prediction validation report

Status: Initial complete.

prediction_validation_report.py exists and is wired into ops_check.py.

5. Formal sector/index models

Status: Later.

Potential future files:

market_intelligence/sector_model.py
market_intelligence/index_model.py

Goals:

sector strength
theme strength
benchmark alignment
QQQ/SPY/IWM/GLD support/conflict
6. app.py decomposition

Status: Later.

Possible extraction targets:

signal_router.py
risk_engine.py
execution_engine.py
market_state.py
state_store.py

Safest first extraction:

signal_router.py

Initial mode should be observe-only beside current /webhook logic.

7. Risk engine skeleton

Status: Later.

Future concepts:

risk_engine.py
RiskCheckResult
RiskDecision
layered risk checks
observe-only compare against current app.py decisions
8. Soft risk modifier / live use of predictions

Status: Not ready.

Potential future behavior, not enabled:

prediction_score < 35 → require extra confirmation or reduce size
expected_pnl negative + weak trend_score → avoid/chase block
recommended_entry_timing = prefer_wait_for_confirmation → require confirmation
trend_label = extended_uptrend + weak expectancy → reduce size or block chase

Do not implement until there are several clean paper sessions and validation reports support the change.

Known Watch Items
Prediction confidence is still very_low due to limited clean historical samples.
Some outcome data was reconstructed and should not be over-weighted.
Early market closes are not currently modeled in the shared calendar.
Event collection can surface low-quality or loosely relevant financial news.
Large share-price symbols can hit affordability limits.
Prediction layer is observe-only and must remain so until validated.
Current Best Next Operational Step

Before the next trading session:

cd ~/trading-bot
source venv/bin/activate

TARGET_DATE=$(python3 next_trading_date.py)
echo "$TARGET_DATE"

python3 ops_check.py intelligence "$TARGET_DATE"
python3 ops_check.py events "$TARGET_DATE"
python3 ops_check.py predictions "$TARGET_DATE"
python3 ops_check.py trends "$TARGET_DATE"
python3 ops_check.py prediction-validation "$TARGET_DATE"

After the next trading session:

python3 ops_check.py post $(date +%F)
python3 ops_check.py prediction-validation $(date +%F)
python3 analytics_report.py --date $(date +%F)
python3 filter_report.py --date $(date +%F)

The next development decision should be based on whether prediction scores and timing/trend recommendations correlate directionally with real paper-trading outcomes.

Final Guardrail

When in doubt, preserve current trading behavior and add read-only visibility first.
