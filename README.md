# Trading Bot

Automated AI-assisted paper trading bot using TradingView webhooks, a Flask/Gunicorn webhook server, service-owned signal orchestration, Alpaca paper trading, pre-market intelligence, event scoring, prediction reports, and layered risk controls.

This project is currently operated as a paper-trading system. Several live-safe controls are present in the codebase. ML prediction authority remains conservative: weak prediction evidence can apply explicitly logged downside size caps, while hard prediction blocking remains disabled unless promoted through paper-session validation and operator review.

---

## Current Status

As of the latest roadmap work:

- Bot is operational in paper trading.
- `app.py` is a Flask composition root: app creation, startup entry point, container selection, route registration, and the public `process_signal()` compatibility wrapper.
- Live signal orchestration is owned by `services/live_signal_processor.py`; approval gates, sizing, execution adapters, audit persistence, runtime context, and repositories are service-owned.
- The legacy live signal processor, `execute_legacy`, `run_legacy_*` service functions, and app-level audit shims have been removed.
- Architecture boundary tests enforce DB access through `db.py`, repositories, and migrations; broker/market-data access through approved adapter boundaries; and no temporary architecture allowlists remain.
- Runtime and report DB/market-data cleanup has moved most scripts through repositories/services, including fill stream/poller, session momentum, pre-market research, live features, prediction cache, bot events, reports, ops checks, and ML/backfill paths.
- `/status` exposes `symbol_intelligence`, prediction-cache status, policy-artifact status, runtime config, and service-owned status payloads.
- Daily intelligence pipeline creates `daily_symbol_context`, `daily_symbol_events`, `daily_symbol_predictions`, `strong_day_participation`, trend context, and prediction-validation reports.
- `ops_check.py` includes performance, runtime, resource, and persistence diagnostics such as `runtime-health`, `resource-readiness`, `lifecycle-analysis`, `setup-breakdown`, `conviction-stack-report`, `conviction-persistence-health`, `peak-bucket-report`, `winner-became-loser`, and prediction validation.
- Approved BUY audit persistence records final sizing attribution, dominant limiter, active cap-derived effective cap, ML prediction bucket/score, buy-opportunity recommendation, strategy score, session label, and setup policy action.
- `db_migrations.py` provides the idempotent migration runner; app startup no longer owns schema `ALTER TABLE` work.
- `feature_snapshots`, `decision_snapshots`, `rejected_signal_outcomes`, `exit_snapshots`, `matched_trades`, and related report tables support ML governance, counterfactual coverage, lifecycle analysis, and replay validation.
- `decision_snapshots` now use feature semantic version `decision_snapshot_features_v4`; canonical intelligence includes observe-only `analytics_state` from the predictive/descriptive/diagnostic/prescriptive toolkit.
- `ml_platform` remains a staged, ahead-of-live research lane with read-only readiness, replay, governance, manifest, and retraining reports.
- `ml/models/similarity_v0/` remains a research-only metadata placeholder, while optional supervised and HMM artifacts can be trained under `ml/models/` for offline review only.
- Research export support now includes DuckDB and Parquet/PyArrow so daily review datasets can be exported without changing live trading behavior.
- Optional TimescaleDB storage can mirror compact live feature ticks into `stock_ticks` when `TIMESCALE_DB_URI` is configured. This storage path has no trade authority.
- Auto-buy paper execution can run from internal Alpaca-bar candidates across the approved universe when `AUTO_BUY_SIGNAL_MODE=internal_all` and `AUTO_BUY_LIVE_BUYS=true`. Candidate capture stores scored/taken/not-taken rows for learning and counterfactual review.
- Auto-buy scoring now distinguishes early constructive build opportunities from mature chase/extension states. Early build is a ranking/learning boost; mature/extreme chase is penalized or blocked so the bot is not simply buying peak momentum.
- Position-manager partial exits now fail safe when open-order cancellation or Alpaca available-quantity state has not settled; the job records a failed/queued action instead of crashing on stale quantity.
- The trading education corpus is versioned and non-authoritative. `ops_check.py trading-education-health` reports curated source and concept coverage for SEC/FINRA/CFTC/CME/NerdWallet/Investopedia plus normalized strategy, risk, backtesting, and overfitting-control concepts; `ops_check.py trading-education-ingest --max-pages 6 --no-follow` stores compact approved-source concept metadata with URL, timestamp, content hash, and corpus version.
- Webhook/status secrets should be supplied by `X-Webhook-Secret` or `Authorization: Bearer ...`; query-string secrets are rejected unless `ALLOW_QUERY_STRING_SECRET=true` is explicitly set for temporary compatibility.
- Prediction gate mode defaults to warn-only for hard blocking. Weak ML predictions can only reduce risk through explicit size caps; they do not place orders, loosen gates, or override broker/order safeguards.

---

## High-Level Architecture

```text
TradingView Alerts / Internal Bar Candidates
        |
        v
Cloudflare Tunnel
        |
        v
Nginx Reverse Proxy
        |
        v
Gunicorn + Flask app.py
        |
        v
Pre-check stack
        |
        v
Claude Haiku decision engine
        |
        v
Alpaca paper trading
        |
        v
Fill stream / fill poller
        |
        v
SQLite trades.db
        |
        v
Reports, intelligence, validation
```

TradingView alerts are now one possible signal source, not the only source.
When configured for paper-mode breadth, `auto_buy_manager.py --scope all --live`
can evaluate the full approved universe from internal bar/session/setup data and
submit only candidates that pass the same capacity, cooldown, risk, and broker
safety checks.

## Runtime Environment

Production VM:

Host/IP: local Ubuntu VM
User: tradingbot
Project path: /home/tradingbot/trading-bot
Python venv: /home/tradingbot/trading-bot/venv
Reverse proxy: Nginx
App server: Gunicorn
Webhook app: Flask
Tunnel: Cloudflare Tunnel
Database: SQLite trades.db

Systemd services:

trading-bot
fill-stream
cloudflared
nginx

Secrets are stored in:

/etc/trading-bot.env

Never store secrets in systemd service files, source code, README examples, or committed config.

Expected env vars include:

WEBHOOK_SECRET
ANTHROPIC_API_KEY
ALPACA_API_KEY
ALPACA_SECRET_KEY
LOG_LEVEL
EXECUTION_MODE
LIVE_TRADING_ENABLED
TIMESCALE_DB_URI

## Fresh Checkout Bootstrap

For local development or audit from a fresh checkout:

```bash
cd /home/tradingbot/trading-bot
python3 -m venv venv
. venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -e '.[dev]'
python run_tests.py
```

`requirements.txt` includes the core runtime stack plus optional research
dependencies used by checked-in commands: DuckDB/PyArrow research exports,
scikit-learn/joblib supervised prediction artifacts, and hmmlearn HMM regime
experiments. These packages do not grant live trading authority by themselves.

Additional validation commands:

```bash
bash safe_repo_check.sh
python tests/test_architecture_boundaries.py
python run_staged_tests.py
python tests/test_cron_contract.py
```

Runtime secrets still belong in `/etc/trading-bot.env`; do not commit them.

## Approved Symbols

Current intelligence/reporting universe:

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

Symbol definitions and price ranges are maintained in symbols_config.py and imported through config.py.

## Main Runtime Files

### app.py

Flask composition root and compatibility entrypoint.

Exposes:

POST /webhook
GET  /health
GET  /status
GET  /positions
GET  /debug/symbol/<SYMBOL>

Core responsibilities:

- Create Flask app instances.
- Select and attach the `ApplicationContainer`.
- Register API routes.
- Run explicit startup orchestration.
- Expose `process_signal()` as a compatibility wrapper around `SignalPipeline`.
- Avoid owning trading behavior, broker access, direct DB access, or report logic.

### services/live_signal_processor.py

Service-owned live signal orchestration.

Responsibilities:

- Consume `SignalContext`, `SignalRuntimeState`, and context runtime objects.
- Run staged deterministic gates.
- Call approval, sizing, and execution services.
- Preserve audit behavior and webhook status updates.
- Keep app-level code out of trading decisions.

### decision_engine.py

Claude Haiku decision layer.

The bot sends signal data and account state to Claude after pre-checks pass. Claude returns JSON with:

{
  "approved": true,
  "reason": "reason",
  "position_size_pct": 1.5,
  "stop_loss_pct": 0.5,
  "take_profit_pct": 1.5,
  "confidence": "high"
}

Errors or parse failures default to rejection for safety.

broker.py

Alpaca order execution wrapper.

Buy path:

Computes quantity from cash balance, position_size_pct, and latest trade price.
Applies very-high-risk quantity reduction.
Blocks too-small orders.
Places bracket buy orders with stop-loss and take-profit.

Sell path:

Fetches current Alpaca position.
Refuses sells if quantity is zero or short.
Cancels open bracket orders.
Confirms available quantity after cancel.
Places market sell order.

Live/cash safety guards are present for future use.
Inputs are normalized and validated before broker/API calls. Invalid order
requests fail closed and return `None`.

exceptions.py

Structured exception types for expected bot boundaries:

ValidationError
BrokerError
BrokerAuthError
BrokerRateLimitError
BrokerTransientError
DataAccessError

These are currently used to make validation and broker failures easier to
classify without changing live order behavior.

fill_stream.py

Alpaca websocket listener.

Responsibilities:

Subscribes to Alpaca trade updates.
Records fill events to fill_events.
Updates matching rows in trades.
Inserts synthetic exit rows for unmatched sell-side bracket exits.

Managed by systemd:

sudo systemctl status fill-stream
sudo systemctl restart fill-stream
fill_poller.py

Fallback fill reconciler.

Runs every 2 minutes through cron and updates pending orders from Alpaca in case websocket events are missed.

market_time.py

Shared market-time and trading-calendar helpers.

Responsibilities:

Eastern-time session helpers.
Market open/closed labeling.
Trading day detection.
Common NYSE full-day holiday handling.
Shared next_trading_date() helper.
Expected market_context trading-session date selection.

This is now the source of truth for holiday-aware trading date selection.

next_trading_date.py

Small CLI wrapper around market_time.next_trading_date().

Usage:

python3 next_trading_date.py
python3 next_trading_date.py --from-date 2026-05-22

Used by cron jobs to target the next valid market session.

Pre-Check Stack

The bot performs a large stack of zero-API-cost checks before calling Claude.

Current buy/sell signal flow includes:

Webhook validation
Duplicate webhook protection
Symbol override checks
Market-hours check
Circuit breaker
Ghost sell filter
Cooldown check
Sell-to-buy churn prevention
Daily symbol buy limit
Per-symbol exposure cap
Correlation cluster cap
Trend confirmation gate
Macro-risk gate
Macro position limit
Fundamental score gate
Market bias avoid gate
Chase prevention gate
Momentum check
Claude decision
Confidence gate
Final broker-adjacent safety check
Order placement

Most rejection paths persist rows to trades.db with category-prefixed rejection reasons, such as:

market_hours:
duplicate_webhook:
symbol_override:
circuit_breaker:
ghost_sell:
cooldown:
churn_window:
churn_price:
daily_symbol_buy_limit:
exposure_cap:
correlation_cap:
trend_confirmation:
macro_risk:
macro_position_limit:
fundamental_score:
market_bias_avoid:
chase_prevention:
confidence_gate:

These prefixes are used by reports and daily summaries.

Core Risk Rules

Current core paper-trading risk framework:

Max open positions: controlled by macro regime, up to 12 in normal/risk-on context
Macro caution max positions: usually 8
Macro defensive max positions: usually 5
Per-symbol exposure cap: 4%
Daily loss circuit breaker: -3%
Cooldown: 15 minutes per symbol/action after successful order
Sell-to-buy churn window: 30 minutes
Sell-to-buy price improvement requirement: 0.5%
Trend confirmation: 3 consecutive BUY alerts required for BUY
Market hours: regular trading window, Eastern Time

Risk is layered. Sells remain allowed through many buy-side risk restrictions so the bot can reduce exposure.

Market Context and Intelligence Pipeline

The bot maintains a daily intelligence layer.

Key tables:

daily_symbol_context
daily_symbol_events
daily_symbol_predictions
historical_signal_outcomes
historical_trade_outcomes
historical_trend_context
matched_trades

Key scripts:

pre_market_research_data.py
collect_and_score_events.py
apply_event_scores.py
predict_symbol_outcomes.py
intelligence_context_report.py
event_attribution_report.py
intelligence_prediction_report.py
trend_context_report.py
prediction_validation_report.py

Daily intelligence flow:

pre_market_research_data.py
        |
        v
daily_symbol_context
        |
        v
collect_and_score_events.py
        |
        v
daily_symbol_events
        |
        v
apply event aggregates to context
        |
        v
predict_symbol_outcomes.py
        |
        v
daily_symbol_predictions
        |
        v
/status symbol_intelligence
ops_check.py prediction-validation
## Prediction Layer

The prediction layer is conservative and risk-reducing only.

It produces fields such as:

prediction_score
probability_of_profit
probability_of_order
expected_pnl
expected_win_rate
confidence
sample_size
reason
timing_score
recommended_entry_timing
recommended_exit_timing
timing_reason
trend_score
trend_label
trend_regime
trend_confidence
trend_reason

Current behavior:

Predictions are visible in /status.
Predictions are reported by intelligence_prediction_report.py.
Predictions are validated by prediction_validation_report.py.
Weak ML buckets can apply explicit downside size caps when sample-size and
setup-quality conditions are met.
Predictions do not place orders.
Predictions do not loosen gates.
Predictions do not increase sizing.
Hard prediction blocking remains disabled unless `PREDICTION_GATE_MODE=hard`
is explicitly promoted after paper-session validation.

The correct roadmap path is:

observe-only
→ validation report
→ warn-only
→ soft modifier
→ possible hard gate much later

## ML Platform and Staged Integration

The ML platform is a research/audit layer. It is intentionally separate from
live webhook, broker, order, and hard risk-control paths.

Current staged pieces:

ai_dependency_status.py
score_financial_sentiment.py
timescale_smoke_test.py
train_regime_model.py
train_supervised_predictions.py
risk_lockout.py
ml_platform/brain_features.py
ml_platform/governance.py
ml_platform/readiness.py
ml_platform/replay.py
ml_platform/serving.py
ml_platform/staged.py
ml/models/similarity_v0/
prediction_cache.py
run_staged_tests.py
tests/staged/

Useful read-only commands:

python3 ai_dependency_status.py
python3 score_financial_sentiment.py --text "Example headline text"
python3 score_financial_sentiment.py --text "Example headline text" --finbert
python3 risk_lockout.py status
python3 timescale_smoke_test.py --symbol AAPL --price 123.45 --volume 100
python3 train_supervised_predictions.py \
  --limit 5000 \
  --artifact-output ml/models/supervised_entry_v1/model.joblib
python3 train_regime_model.py \
  --limit 1000 \
  --artifact-output ml/models/regime_hmm_v1/model.joblib
python3 run_staged_tests.py
python3 -m ml_platform.cli staged-readiness \
  --start-date 2026-05-26 \
  --end-date 2026-05-26 \
  --candidate-model similarity_v0 \
  --prediction-symbol AAPL \
  --output /tmp/staged_ml_readiness_2026-05-26.json
python3 -m ml_platform.cli retraining-readiness \
  --start-date 2026-05-26 \
  --end-date 2026-05-26 \
  --trading-sessions-observed 0 \
  --output /tmp/retraining_readiness_2026-05-26.json

The staged readiness report composes dataset profile, dataset manifest, brain
feature manifest, replay decision-delta audit, prediction-provider contract,
retraining readiness, and promotion gates. It reports `runtime_effect: none`.

Prediction drift automation is warning/candidate-artifact only:

```bash
python3 pipeline/validate_predictions.py --date 2026-06-03 --sessions 5
python3 pipeline/retrain.py --date 2026-06-03 --sessions 5
```

`pipeline/validate_predictions.py` is part of the pre-market pipeline and
warns when recent `prediction_score` correlation is flat or negative for 3+
sessions. `pipeline/retrain.py` can train a candidate supervised artifact and
write registry metadata only when validation and `retraining-readiness` pass.
It cannot load a model into runtime or promote beyond `warn_only` without
explicit operator approval. Drift validation uses the last available joined
prediction/outcome sessions, so weekends and market holidays do not count as
bad sessions. Empty or partial data is reported through `coverage_status`
instead of triggering retraining. Retraining uses a nonblocking lock
(`/tmp/tradingbot_ml_retrain.lock` by default) and a max runtime guard
(`--max-runtime-seconds`, default 1800) so long training runs do not overlap
silently with later automation. It also runs at low priority
(`nice -n 19` in the post-session wrapper and `--nice-increment 19` inside the
Python process) and applies a default 4 GB address-space cap via
`--memory-limit-mb 4096`.

Retraining is idempotent by target date. A completed run marker is written under
`ml/models/supervised_entry_v1/candidates/retrain_runs/`; later runs for the
same date exit cleanly unless `--rerun-completed` is supplied. Each trained
candidate writes a human-readable `.diagnostic.json` next to the model artifact
with validation correlation, training row counts, Python version, platform, Git
SHA, resource guard settings, and promotion blockers. Training rows are fetched
with a point-in-time guard using `feature_available_at <=
--prediction-time-cutoff` so historical metrics cannot use features that were
unavailable at the decision cutoff. Retraining also prunes unprotected old
binary artifacts after the run while preserving diagnostic JSON files.

The pre-market pipeline includes an observe-only shadow scoring step. If a
candidate model exists in the registry, `pipeline.shadow_predictions` scores the
latest feature snapshots and writes `shadow_predictions` rows. Those rows are
for post-session comparison only and are not read by the live execution path.
Use `python3 ops_check.py shadow-predictions YYYY-MM-DD` after labels are
available to compare candidate score buckets against forward outcomes.

If `ML_MODEL_ID` and `ML_MODEL_MAX_AGE_SECONDS` are configured, runtime ML
authority checks the model registry and artifact mtime before enforcing ML
size-down/block behavior. Missing or stale model metadata forces
`deterministic_policy_no_ml_authority`; deterministic hard gates and existing
non-ML policy still run.

The newer AI analytics services add structured observe-only context around the
same trading decisions: dependency status, technical features, portfolio/risk
analytics, sentiment scoring, async-pipeline architecture notes, regime-risk
protocols, dashboard alerts, persistent lockout state, and optional storage.
`services/canonical_intelligence_service.py` includes the compact
`analytics_state` payload inside canonical decision intelligence. The payload is
intended for replay, audit, and future dataset features; it cannot submit
orders, increase sizing, bypass gates, or override broker controls.

`TIMESCALE_DB_URI` enables optional asynchronous tick mirroring from
`services/live_features_service.py` through
`services/timescale_tick_writer_service.py`. The writer creates/verifies the
`stock_ticks` hypertable and writes compact symbol/price/volume rows for later
feature engineering. Leave the env var unset to disable this path cleanly.

`prediction_cache.py` is the runtime-safe bridge for ML prediction reads. It
preloads `daily_symbol_predictions` into an in-memory dict keyed by symbol,
refreshes on a 60-second TTL, and exposes memory-only lookups to the live signal
path. The serving contract remains target 25 ms / hard timeout 50 ms,
fail-open to no prediction. The existing deterministic `prediction_gate` is
documented as the deterministic signal-quality gate; cached ML predictions are
recorded beside it as `ml_prediction_*` fields. Weak buckets can reduce size
through explicit cap logic only. Numeric prediction outputs are hard-clipped at
the cache boundary (`0..100` for score fields, `0..1` for probabilities) before
they can enter runtime context.

`python3 -m ml_platform.cli replay-decisions` is read-only. It re-runs
`decision_policy` against stored `decision_snapshots`, joins changed decisions
to realized `matched_trades` or counterfactual `rejected_signal_outcomes`, and
reports avoided losers, missed winners, recovered missed winners, introduced
losers, friction-adjusted simulated delta, and best/worst changed decisions.

Runtime learning artifacts are governed as policy artifacts:
`strategy_memory.json`, `portfolio_replacement_memory.json`,
`excursion_memory.json`, `missed_opportunity_memory.json`, and
`policy_backtest_summary.json`. `policy_artifacts.py register` snapshots the
current set, `--known-good` advances the rollback pointer, and
`policy_artifacts.py rollback` restores the known-good set. `/status`,
`ops_check.py policy-artifacts`, and dataset manifests expose artifact hashes,
registry hash, known-good id, mtimes, generated timestamps, and runtime effect.

Decision policy authority is explicit and conservative. Defaults are
`DECISION_POLICY_AUTHORITY_MODE=paper_only`, `DECISION_POLICY_LIVE_BLOCK=true`,
and `DECISION_POLICY_LIVE_SIZE_DOWN=true`, which means block/size-down authority
is available in paper/dry-run modes only. The policy never increases size,
submits orders, or overrides hard gates; it can only reduce risk before Claude
when the explicit authority settings allow it. If `policy_backtest_summary.json`
reports `policy_too_loose`, keep this layer under review and do not promote it.

`similarity_v0` is metadata-only. It has no trained artifact, no runtime import,
and no authority to place orders, loosen risk controls, or change sizing.

Dataset Export and Manifest

The supervised dataset exporter is read-only and can write an audit manifest:

python3 export_ml_dataset.py \
  --date 2026-05-26 \
  --output /tmp/ml_dataset_2026-05-26.csv \
  --manifest-output /tmp/ml_dataset_2026-05-26.manifest.json

Dataset manifests include DB hash, query version, label version, feature
version, row/symbol counts, git SHA, override-file hashes, and policy-artifact
hashes. They are intended for auditability, not promotion by themselves.

By default, `export_ml_dataset.py` writes only complete fixed-horizon label
rows. Incomplete, unlabeled, and near-close partial rows are excluded from the
CSV and counted in the manifest under `excluded_rows_reason_counts`. Use
`--include-incomplete-labels` only for audit exports, not first-pass training.
Realized-PnL labels are not part of the default training export; any future
realized-exit label export must carry `exit_policy_version` and
`position_manager_version`.

Initial safe training targets are fixed-horizon fields such as `ret_fwd_15m`,
`ret_fwd_30m`, `max_up_15m`, and `max_down_15m`. `ret_fwd_60m`,
`max_favorable_excursion`, and `max_adverse_excursion` remain pending for the
feature-snapshot label schema.

Feature leakage fields now live in `feature_snapshots` and are exported in ML
datasets:

feature_available_at
feature_generated_at
feature_age_seconds
source
is_stale
staleness_reason

Use `python3 db_migrations.py status` and `python3 db_migrations.py apply` to
check or apply idempotent schema migrations.

Migrations are manual before deployment or DB restore. Pending migrations are
also surfaced by `morning_check.py`, `ops_check.py migration-status`, and the
premarket/all ops check bundles.

Current tracked migrations cover feature leakage/audit fields,
`rejected_signal_outcomes`, webhook-event lifecycle/status columns, and trade
decision-context columns that used to be added during app startup, plus the
append-only `decision_snapshots` audit table, `strong_day_participation`, and
`auto_buy_decision_snapshots`.

Fixed-horizon label v1 generation is routed through `label_v1_builder.py`.
It verifies the feature-snapshot leakage/audit contract before delegating to
the existing label feature builder. Use `--check-only` for a read-only contract
check.

Rejected-signal counterfactual outcomes can be populated and checked with:

```bash
python3 rejected_signal_outcome_builder.py --date YYYY-MM-DD
python3 ops_check.py rejected-outcomes YYYY-MM-DD
python3 ops_check.py decision-snapshots YYYY-MM-DD
python3 ops_check.py lifecycle-analysis YYYY-MM-DD
python3 ops_check.py ai-intelligence-review YYYY-MM-DD
python3 auto_buy_outcome_report.py --date YYYY-MM-DD
```
/status Symbol Intelligence

GET /status includes:

"symbol_intelligence": {
  "available": true,
  "market_date": "YYYY-MM-DD",
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

Spot-check one symbol:

curl -s -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  "https://trading.tib0n3s.xyz/status" \
  | jq '.symbol_intelligence.symbols.AAPL'
Operator Check Wrapper

ops_check.py wraps common reports.

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
python3 ops_check.py runtime-health YYYY-MM-DD
python3 ops_check.py resource-readiness
python3 ops_check.py lifecycle-analysis YYYY-MM-DD
python3 ops_check.py lifecycle-analysis YYYY-MM-DD --symbol AAPL --samples 25
python3 ops_check.py ai-intelligence-review YYYY-MM-DD
python3 ops_check.py all

Useful next-session validation:

cd ~/trading-bot
source venv/bin/activate

TARGET_DATE=$(python3 next_trading_date.py)
echo "$TARGET_DATE"

python3 ops_check.py intelligence "$TARGET_DATE"
python3 ops_check.py events "$TARGET_DATE"
python3 ops_check.py predictions "$TARGET_DATE"
python3 ops_check.py trends "$TARGET_DATE"
python3 ops_check.py prediction-validation "$TARGET_DATE"

Resource readiness:

`ops_check.py resource-readiness` inventories optional VM integrations without
loading provider SDKs or making network calls. It reports whether credentials
and Python packages are present for future resource adapters such as Polygon or
Databento market data, SEC EDGAR disclosures, premium news APIs, local
embedding/vector search, DuckDB/Parquet research exports, and Prometheus-style
metrics. A configured resource is still observe-only until explicitly wired
through a service boundary and validated by reports/tests.

Common resource environment variables:

```text
POLYGON_API_KEY
DATABENTO_API_KEY
SEC_EDGAR_USER_AGENT
NEWS_API_KEY
ANTHROPIC_API_KEY
```

SEC EDGAR does not require an account or login. Configure a responsible user
agent string instead:

```bash
SEC_EDGAR_USER_AGENT="trading-bot your-email@example.com"
```

Polygon market-data validation requires only the API key:

```bash
POLYGON_API_KEY="..."
```

Both adapters are report/research resources by default. Adding these variables
does not replace Alpaca market data and does not grant live trading authority.
Prediction Validation Report

prediction_validation_report.py compares predictions to later signal/trade
outcomes and, after `strong_day_participation_report.py --write-db` runs,
strong-session participation/coverage outcomes. It also reports agreement and
disagreement between the deterministic signal-quality gate and cached
`ml_prediction_*` fields from decision snapshots.

Usage:

python3 prediction_validation_report.py
python3 prediction_validation_report.py 2026-05-26
python3 prediction_validation_report.py --date 2026-05-26
python3 ops_check.py prediction-validation 2026-05-26
python3 strong_day_participation_report.py --date 2026-05-26 --write-db

Pre-session mode is expected to show:

Predictions          : 41
Symbols with signals : 0
Symbols with trades  : 0
Symbols with matches : 0

After the trading session, the report should answer:

Did higher prediction_score buckets outperform lower-score buckets?
Did recommended_entry_timing align with better outcomes?
Did trend_label / trend_regime identify risk?
Did weak predictions avoid losses or correlate with blocked signals?
Did predicted symbols participate in strong sessions or miss them?
Common Reports
Morning readiness
python3 ops_check.py morning

Checks:

Market context freshness
Services
Alpaca account access
Market alignment
Debug endpoint
Filter effectiveness
python3 ops_check.py filters $(date +%F)
python3 filter_report.py --date 2026-05-26
python3 filter_report.py --week

Summarizes rejection categories and symbols.

Daily summary
python3 daily_summary.py
python3 daily_summary.py 2026-05-26
python3 daily_summary.py --week

Includes:

Signal counts
Rejection breakdown
Orders by symbol
Matched-trade P&L
Win rate
Profit factor
Claude cost estimate
Analytics report
python3 analytics_report.py
python3 analytics_report.py --date 2026-05-26
python3 analytics_report.py --week
python3 analytics_report.py --all

Includes:

Execution
Risk filters
Performance
Per-symbol performance
Matched-trade attribution
Data quality
Trend context
python3 ops_check.py trends 2026-05-26
python3 trend_context_report.py --date 2026-05-26

Shows trend-label and trend-regime distributions.

Event attribution
python3 ops_check.py events 2026-05-26
python3 event_attribution_report.py --date 2026-05-26

Shows daily event counts by type, impact, relevance, and outcome attribution.

Cron Jobs

Cron runs as user tradingbot.

View cron:

crontab -l

Current major cron categories:

*/2 * * * *          fill_poller.py
0 8 * * 1-5          pre_market_research_data.py
5 8 * * 1-5          collect_and_score_events.py --apply-context --predict
0 16 * * 1-5         daily_summary.py
5 16 * * 5           daily_summary.py --week
10 16 * * 1-5        trade_matcher.py
*/2 8-15 * * 1-5     rolling/session/position momentum jobs
*/2 8-15 * * 1-5     position manager
30 16 * * 1-5        after-close learning
0 18 * * 1-4         after-hours event collection for next session
0 18 * * 5           Friday after-hours event collection
0 10,18 * * 6,0      weekend event collection

Cron jobs that require secrets should source:

set -a && . /etc/trading-bot.env && set +a

Write-heavy cron jobs should run through `job_runner.py`. The runner owns
non-blocking lock acquisition, lock-busy logging, command output redirection,
and durable `job_runs` ledger rows with start/end time, duration, exit code,
lock state, optional row counts, warning counts, and artifact hashes.

Example:

```bash
/home/tradingbot/trading-bot/venv/bin/python job_runner.py \
  --job-name run_position_manager \
  --lock-file /tmp/tradingbot_position_manager.lock \
  --log-file /home/tradingbot/trading-bot/position_manager.log \
  -- bash /home/tradingbot/trading-bot/run_position_manager.sh
```
Services

Check services:

sudo systemctl status trading-bot
sudo systemctl status fill-stream
sudo systemctl status cloudflared
sudo systemctl status nginx

Restart app:

sudo systemctl restart trading-bot

Restart fill stream:

sudo systemctl restart fill-stream

Tail logs:

tail -f trading_bot.log
tail -f fill_stream.log
tail -f fill_poller.log
tail -f pre_market_research.log
tail -f event_collection.log
tail -f daily_summary.log
tail -f after_close_learning.log

Useful filtered app log:

tail -f ~/trading-bot/trading_bot.log \
  | grep --line-buffered "APPROVED\|REJECTED\|ORDER\|Cooldown\|Exposure\|churn\|Trend\|bias\|chase\|momentum\|prediction"
Health and Operator Endpoints

Health:

curl http://localhost:5000/health

Status:

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
Database

Database path:

/home/tradingbot/trading-bot/trades.db

List tables:

sqlite3 trades.db ".tables"

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
strong_day_participation
historical_signal_outcomes
historical_trade_outcomes
historical_trend_context
session_momentum
position_momentum_actions
position_momentum_checks

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
WHERE market_date = '$TARGET_DATE'
UNION ALL
SELECT 'strong_day', COUNT(*)
FROM strong_day_participation
WHERE market_date = '$TARGET_DATE';
"
Manual Validation Workflow
Before next market session
cd ~/trading-bot
source venv/bin/activate

TARGET_DATE=$(python3 next_trading_date.py)
echo "$TARGET_DATE"

python3 ops_check.py intelligence "$TARGET_DATE"
python3 ops_check.py events "$TARGET_DATE"
python3 ops_check.py predictions "$TARGET_DATE"
python3 ops_check.py trends "$TARGET_DATE"
python3 ops_check.py prediction-validation "$TARGET_DATE"
During session

Monitor logs:

tail -f trading_bot.log \
  | grep --line-buffered "Signal received\|Processing\|blocked\|APPROVED\|ORDER\|prediction\|momentum"

Check live operator view:

curl -s -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  "https://trading.tib0n3s.xyz/status" | jq '.symbol_intelligence'
After close
python3 ops_check.py post $(date +%F)
python3 ops_check.py predictions $(date +%F)
python3 ops_check.py trends $(date +%F)
python3 strong_day_participation_report.py --date $(date +%F) --write-db
python3 ops_check.py prediction-validation $(date +%F)
python3 analytics_report.py --date $(date +%F)
python3 filter_report.py --date $(date +%F)
Development Workflow

Activate environment:

cd ~/trading-bot
source venv/bin/activate

Compile changed Python files:

python3 -m py_compile app.py broker.py decision_engine.py

Compile all Python files:

python3 -m compileall .

Check git status:

git status --short

Commit:

git add <files>
git commit -m "Description"

Restart service after app changes:

sudo systemctl restart trading-bot
sudo systemctl status trading-bot --no-pager
Safety Rules for Changes

Do not change live trading behavior unless explicitly intended.

Preferred safe work while market is closed:

Read-only reports
Operator visibility
Validation reports
Schema-safe migrations
Holiday/date targeting
Documentation
Ops checks

Avoid during active trading unless necessary:

Order execution changes
Risk gate changes
Sizing changes
Claude prompt changes
Webhook processing changes
Broker behavior changes
Roadmap Status
2. Validate next real paper-trading session

Status: Ready.

Need to confirm next market session:

8:00 pre-market data job creates daily_symbol_context
8:05 event collector applies context and runs predictions
daily_symbol_predictions exists before trading
post-session checks include prediction/timing/trend reports
prediction_score correlates directionally with outcomes

Useful commands:

TARGET_DATE=$(python3 next_trading_date.py)

python3 ops_check.py intelligence "$TARGET_DATE"
python3 ops_check.py events "$TARGET_DATE"
python3 ops_check.py predictions "$TARGET_DATE"
python3 ops_check.py trends "$TARGET_DATE"
python3 ops_check.py prediction-validation "$TARGET_DATE"
3. Add prediction/timing/trend fields to /status

Status: Complete.

/status now exposes read-only symbol_intelligence.

4. Build prediction validation report

Status: Initial complete.

prediction_validation_report.py exists and is wired into:

python3 ops_check.py prediction-validation DATE

The report is useful pre-session and post-session.

5. Formal sector/index models

Status: Later.

Potential future files:

market_intelligence/sector_model.py
market_intelligence/index_model.py

Goals:

sector strength
theme strength
benchmark alignment
QQQ/SPY/IWM/GLD support or conflict
6. app.py decomposition

Status: Complete for the live signal path.

Current ownership:

app.py remains the Flask composition root.
SignalPipeline owns runtime flow entry.
LiveSignalProcessor owns live signal orchestration.
ApprovalService owns deterministic and Claude/confidence decisions.
SizingService owns final sizing.
ExecutionService and execution adapters own approved order execution.
TradeAuditService owns execution/rejection persistence.

Next app-level work should be composition cleanup only, not trading behavior migration.

7. Risk engine skeleton

Status: Later.

Future concepts:

risk_engine.py
RiskCheckResult
RiskDecision
layered risk checks
observe-only comparison against current app.py decisions
8. Soft risk modifier / live use of predictions

Status: Not ready.

The prediction layer is working, but confidence is still low because historical sample size is small and much of the data was reconstructed.

Correct path:

observe-only
→ validation report
→ warn-only
→ soft modifier
→ possible live gate much later

Potential future behavior, not enabled:

prediction_score < 35 → require extra confirmation or reduce size
expected_pnl negative + weak trend_score → avoid/chase block
recommended_entry_timing = prefer_wait_for_confirmation → require confirmation
trend_label = extended_uptrend + weak expectancy → reduce size or block chase
Known Issues / Watch Items
Prediction confidence is currently very_low until more sessions accumulate.
Some historical outcomes were reconstructed and should not be over-weighted.
Holiday targeting is now improved, but early closes are not modeled.
Prediction data is observe-only and should not be used as a live gate yet.
Event collection can surface low-quality financial news items; validation is needed.
Large share-price symbols may still hit affordability constraints.
Historical bracket stop/take-profit exits depend on synthetic exit capture.
Useful One-Liners

Check services:

for s in trading-bot fill-stream cloudflared nginx; do
  echo "---- $s ----"
  systemctl is-active "$s"
done

Check next trading date:

python3 next_trading_date.py

Check prediction readiness:

TARGET_DATE=$(python3 next_trading_date.py)
python3 ops_check.py prediction-validation "$TARGET_DATE"

Check /status intelligence summary:

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

Check row counts:

TARGET_DATE=$(python3 next_trading_date.py)

sqlite3 trades.db "
SELECT 'context', COUNT(*) FROM daily_symbol_context WHERE market_date='$TARGET_DATE'
UNION ALL
SELECT 'events', COUNT(*) FROM daily_symbol_events WHERE market_date='$TARGET_DATE'
UNION ALL
SELECT 'predictions', COUNT(*) FROM daily_symbol_predictions WHERE market_date='$TARGET_DATE';
"
Disclaimer

This project is for personal paper-trading experimentation and engineering research. It is not financial advice. Automated trading can lose money quickly. Use paper trading, strict risk controls, and extensive validation before considering any live deployment.
