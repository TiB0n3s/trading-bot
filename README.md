# Trading Bot

Automated AI-assisted paper trading bot using TradingView webhooks, a Flask/Gunicorn webhook server, service-owned signal orchestration, Alpaca paper trading, pre-market intelligence, event scoring, prediction reports, and layered risk controls.

This project is currently operated as a paper-trading system. Several live-safe controls are present in the codebase. ML prediction authority remains conservative in cash modes. In paper/dry-run modes, explicitly bounded learning authority can now influence paper entries after hard blockers pass, so the intelligence layer can learn from real execution behavior without granting cash-live authority.

---

## Current Status

As of the latest roadmap work:

- Bot is operational in paper trading.
- `app.py` is a Flask composition root: startup entry point, runtime compatibility context, container selection, and the public `process_signal()` compatibility wrapper. Flask app construction and route registration mechanics now live in `src/trading_bot/web/app_factory.py`, startup wiring lives in `src/trading_bot/runtime/startup.py`, and app-specific runtime settings are loaded by `src/trading_bot/config/runtime.py`.
- Root Python file count is capped at five compatibility entrypoints. Legacy root scripts/modules have moved to `scripts/` while package migration continues into `src/trading_bot/`.
- Live signal orchestration is owned by `services/live_signal_processor.py`; approval gates, sizing, execution adapters, audit persistence, runtime context, and repositories are service-owned.
- The legacy live signal processor, `execute_legacy`, `run_legacy_*` service functions, and app-level audit shims have been removed.
- Architecture boundary tests enforce DB access through `db.py`, repositories, and migrations; broker/market-data access through approved adapter boundaries; and no temporary architecture allowlists remain.
- Runtime and report DB/market-data cleanup has moved most scripts through repositories/services, including fill stream/poller, session momentum, pre-market research, live features, prediction cache, bot events, reports, ops checks, and ML/backfill paths.
- `/status` exposes `symbol_intelligence`, prediction-cache status, policy-artifact status, runtime config, and service-owned status payloads.
- Daily intelligence pipeline creates `daily_symbol_context`, `daily_symbol_events`, `daily_symbol_predictions`, `strong_day_participation`, trend context, and prediction-validation reports.
- `ops_check.py external-symbol-discovery START_DATE --end-date YYYY-MM-DD` reviews event references to non-approved symbols, separates configured context-only symbols from unknown external symbols, shows linked approved symbols, source reliability, examples, and whether a symbol should remain context-only/watch-only or be reviewed for context/approval. This report is advisory-only and cannot expand the trade universe automatically.
- `pipeline/external_symbol_candidate_refresh.py --date YYYY-MM-DD` turns repeated unknown external-symbol findings into a research-only candidate queue, can run bounded Polygon historical backfill for eligible symbols, and then marks each symbol as context-only, backfill-pending, training-pending, review-ready, pooled, or rejected. `ops_check.py external-symbol-candidates` inspects this queue. Candidate status never grants trading authority or updates `SYMBOL_CONFIG`.
- The SpaceX catalyst cohort is now explicit in `symbols_config`: `NOC`, `LHX`, `HON`, and `TDY` are approved internal-bar/paper-learning symbols, while `SPCX`, `IRDM`, `ASTS`, `GSAT`, `RDW`, `PL`, `BKSY`, `SPIR`, and `BA` are context-only until liquidity, spread, slippage, and learning evidence justify promotion review.
- `ops_check.py` includes performance, runtime, resource, and persistence diagnostics such as `observability-health`, `external-observability-readiness`, `runtime-health`, `database-backups`, `database-restore-drill`, `live-quote-quality`, `paper-session-evidence`, `local-load-probe`, `paper-replay-load-probe`, `full-session-paper-replay`, `incident-workflow`, `incident-escalation-readiness`, `feature-flags`, `feature-flag-change-history`, `model-governance`, `packaged-entrypoints`, `secrets-manager-readiness`, `resource-readiness`, `lifecycle-analysis`, `setup-breakdown`, `conviction-stack-report`, `conviction-persistence-health`, `peak-bucket-report`, `winner-became-loser`, and prediction validation.
- `ops_check.py config-audit` inventories remaining raw env-var access, validates typed config factories, and flags unsafe runtime defaults such as default webhook secrets, query-string secrets, cash mode without live-trading enablement, or unbacked live ML authority. This report is diagnostic-only and does not change runtime configuration.
- `ops_check.py secrets-hygiene` checks local secret-storage hygiene without printing secret values, including `/etc/trading-bot.env` permissions, repo-local env files, `.gitignore` coverage, and Dockerfile leakage risk.
- `ops_check.py architecture-surface` measures root/module sprawl, oversized decision files, raw env access, and `src/trading_bot` migration skeleton readiness. It is diagnostic-only and supports the cleanup plan in `ops/compatibility_deletion_plan.md`.
- Development guardrails are active: `.github/workflows/ci.yml` runs compile checks plus `run_safety_checks.py` on push/PR, and `.pre-commit-config.yaml` runs Ruff plus the same fast safety harness before commits.
- `ops/project_audit_followup_2026-06-08.md` reconciles the external project-audit/missing-tools notes with the current repo state. CI, local pre-commit guardrails, core safety tests, dependency split, config audit, database backup verification, local observability, local secrets hygiene, replay/load probes, incident workflow/escalation readiness, model-governance evidence checks, feature-flag inventory/metadata/change-history validation, and packaged-entrypoint validation are implemented. Remaining items are external service configuration and real-session evidence collection.
- Approved BUY audit persistence records final sizing attribution, dominant limiter, active cap-derived effective cap, ML prediction bucket/score, buy-opportunity recommendation, strategy score, session label, and setup policy action.
- `db_migrations.py` provides the idempotent migration runner; app startup no longer owns schema `ALTER TABLE` work.
- `feature_snapshots`, `decision_snapshots`, `rejected_signal_outcomes`, `exit_snapshots`, `matched_trades`, and related report tables support ML governance, counterfactual coverage, lifecycle analysis, and replay validation.
- `decision_snapshots` now use feature semantic version `decision_snapshot_features_v4`; canonical intelligence includes observe-only `analytics_state` from the predictive/descriptive/diagnostic/prescriptive toolkit.
- `ml_platform` remains a staged, ahead-of-live research lane with read-only readiness, replay, governance, manifest, and retraining reports.
- `ml/models/similarity_v0/` remains a research-only metadata placeholder, while optional supervised and HMM artifacts can be trained under `ml/models/` for offline review only.
- Research export support now includes DuckDB and Parquet/PyArrow so daily review datasets can be exported without changing live trading behavior.
- `pipeline/after_close_learning.py` runs the recurring after-close quant learning loop: trade matching, rejected-signal outcome completion, automated learning-evidence repair, report-memory refresh, DuckDB/PyArrow research export, pattern/feature/post-trade/readiness reports, paper-learning authority outcome audit, guarded retraining, policy artifact registration, and point-in-time archival. `run_after_close_learning.sh` is now a scheduler wrapper only.
- `pipeline/learning_backfill_repair.py` is the automated post-session repair step for learning evidence. It loops candidate-universe forward-outcome backfill in bounded chunks until coverage reaches the configured target, then repairs approved matched exits that are missing canonical exit snapshots. It is analysis-only and cannot approve, size, or route orders.
- `pipeline/post_session_review.py` owns post-session diagnostics and learning-evidence review with explicit warn-only report semantics, so ordinary review warnings no longer make the scheduled wrapper look like a hard runtime failure.
- Optional TimescaleDB storage can mirror compact live feature ticks into `stock_ticks` when `TIMESCALE_DB_URI` is configured. This storage path has no trade authority.
- Auto-buy paper execution can run from internal Alpaca-bar candidates across the approved universe when `AUTO_BUY_SIGNAL_MODE=internal_all` and `AUTO_BUY_LIVE_BUYS=true`. Candidate capture stores scored/taken/not-taken rows for learning and counterfactual review.
- Auto-buy scoring now distinguishes early constructive build opportunities from mature chase/extension states. Early build is a ranking/learning boost; mature/extreme chase is penalized or blocked so the bot is not simply buying peak momentum.
- Paper auto-buy can apply a bounded strong-evidence promotion when a candidate is blocked only by setup conservatism, has score above threshold plus buffer, positive 15m/30m momentum, strong session/setup context, and non-weak ML evidence. This path is disabled by default outside paper/dry-run, records `paper_strong_evidence_*` audit fields, and cannot override weak ML, intraday losing-pattern feedback, extreme chase, stale data, broker/account, macro/regime, or cash-mode blockers.
- Paper learning authority is enabled by default for paper/dry-run only. It can override Claude low-confidence soft rejections when canonical setup quality and buy-opportunity evidence are strong, and it caps the resulting paper size. Bounded paper exploration authority can also approve or increase size when setup quality, buy-opportunity score, prediction score, session context, and execution context all clear configured thresholds. The primary ML/intelligence authority path is now `layered_model_authority`: it runs the Level 0 regime/alternative-data gates, Level 1 historical-bar/Transformer/supervised ensemble, Level 2 meta-label and counterfactual un-veto logic, and Level 3 slippage-adjusted Kelly sizing before it can veto, approve, or increase paper size. These paper decisions run through the canonical `AuthorityMatrix`, `IntelligenceAdjudicator`, and ordered `GateEngine`; each evaluated signal stores `layered_model_decision`, `intelligence_adjudication`, `decision_trace`, and `canonical_decision_trace` in `account_state`. It cannot override stale signals, broker/account constraints, cash-safe/cash-full mode, explicit symbol overrides, macro/regime hard blocks, execution-quality blocks, or Claude infrastructure failures.
- Claude buy approval is now constrained by the canonical `AuthorityMatrix`: Claude can approve paper/dry-run buys, but cash/live buys require deterministic/promoted authority evidence rather than Claude alone. Denied approvals are recorded as `source=authority_matrix` with canonical trace metadata.
- `DecisionEngine` now records a trace-native cascade for preflight, cash-safe, macro, setup, trend, prediction, session momentum, ML authority, decision policy, intelligence adjudication, paper authority, final sizing, execution quality, and Claude approval gates. Auto-buy candidates also attach canonical `SignalCandidate`, `DecisionTrace`, `intelligence_adjudication`, and capital-allocation metadata before logging/execution.
- Trace-native operator reports are available through `decision_trace_report.py`, `gate_impact_report.py`, `counterfactual_replay_report.py`, and `model_authority_report.py`; the report registry exposes them as `decision-trace`, `gate-impact`, `counterfactual-replay`, and `model-authority`.
- Runtime startup validates a fail-fast `runtime_safety_profile_v1` with `safety_profile_hash` before background runtime tasks run. Config authority terms are normalized through the canonical vocabulary: `off`, `observe`, `warn`, `size_down`, `paper_block`, and `live_block`.
- `ops_check.py operational-readiness YYYY-MM-DD` is the aggregated pre-market/post-deploy hardening gate. It validates critical entrypoints, packaged app imports, config safety, local env-file permissions, latest verified DB backup freshness, runtime job ledger health, SQLite WAL size, and cron/systemd deployment references. It is diagnostic-only and does not mutate runtime state.
- `ops_check.py paper-learning-authority YYYY-MM-DD` audits those paper-only overrides against linked lifecycle evidence. This report is diagnostic and does not grant live/cash authority.
- `ops_check.py advanced-alpha-readiness YYYY-MM-DD` scores advanced alpha families such as bar-level order-flow proxies, true trade-level VPIN, ETF lead-lag, options skew, fractional-memory/trend-scan features, asymmetric-loss comparison, and model dashboards. `ops_check.py advanced-alpha-comparison YYYY-MM-DD` compares standard score thresholding against an asymmetric false-positive guard using linked forward outcomes. `ops_check.py friction-heatmap YYYY-MM-DD` buckets symmetric-vs-asymmetric outcomes by LSI and VPIN toxicity. `ops_check.py volume-clock-vpin YYYY-MM-DD --symbol AAPL --start-time 09:30 --end-time 10:00` converts existing 1-minute rows into equal-volume VPIN buckets using Bulk Volume Classification, and `ops_check.py cross-asset-lead-map` prints the broad/sector lead ticker map for ensemble research. `ops_check.py volatile-session-intelligence YYYY-MM-DD --symbols QQQ,AAPL,NVDA` combines the 10x asymmetric-loss probe, opening-window VPIN coverage, and governed Transformer size-down/block diagnostics for stressed sessions. These reports are diagnostic-only and cannot affect live trading.
- `ops_check.py transformer-authority --symbol AAPL` audits the governed torch Transformer authority adapter. It only affects `decision_policy` when `TRANSFORMER_AUTHORITY_ENABLED=true`, a promoted `TRANSFORMER_MODEL_ID` exists in `ml/models/registry.json`, the registry status is one of `warn_only`, `paper_soft`, `paper_gate`, or `live_candidate`, and the staleness guard passes. Even then it can only block or reduce size; it cannot increase size or submit orders.
- Final BUY sizing now applies an optional slippage-adjusted fractional Kelly cap. It uses predicted slippage, ATR context, model probability, and LSI/VPIN stress to reduce or zero paper/live size when execution friction erodes edge; it cannot approve trades, increase sizing, or bypass broker/order safeguards.
- Position-manager partial exits now fail safe when open-order cancellation or Alpaca available-quantity state has not settled; the job records a failed/queued action instead of crashing on stale quantity.
- The trading education corpus is versioned and non-authoritative. `ops_check.py trading-education-health` reports curated source and concept coverage for SEC/FINRA/CFTC/CME/NerdWallet/Investopedia/Schwab plus normalized strategy, risk, backtesting, and overfitting-control concepts; `ops_check.py trading-education-ingest --max-pages 6 --no-follow` stores compact approved-source concept metadata with URL, timestamp, content hash, and corpus version.
- Webhook/status secrets should be supplied by `X-Webhook-Secret` or `Authorization: Bearer ...`; query-string secrets are rejected unless `ALLOW_QUERY_STRING_SECRET=true` is explicitly set for temporary compatibility.
- Prediction gate mode defaults to warn-only for hard blocking. Weak ML predictions can only reduce risk through explicit size caps; they do not place orders, loosen gates, or override broker/order safeguards.

Development safety workflow:

```bash
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/pre-commit install
./venv/bin/python run_safety_checks.py
```

The pre-commit hook runs Ruff on staged Python files and then runs the fast
trading safety harness. It intentionally does not run full-repo Ruff yet because
the legacy tree still has existing lint debt; CI and local hooks focus on
changed files plus core risk, authority, dependency-packaging, and architecture
regressions. Full targeted tests remain available through `python3 scripts/run_tests.py`.

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
WEBULL_API_KEY
WEBULL_API_SECRET
WEBULL_ACCOUNT_ID
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
pip install -r requirements-dev.txt
pip install -e '.[dev]'
python scripts/run_tests.py
```

`requirements.txt` delegates to `requirements-base.txt`, the slim runtime
dependency subset. Use `requirements-research.txt` when explicitly setting up
the full local research/test environment after installing runtime requirements.
It is an overlay-only file for:
DuckDB/PyArrow research exports, scikit-learn/joblib supervised prediction
artifacts, XGBoost supervised candidates, torch Transformer authority
candidates, and hmmlearn HMM regime experiments.
These packages do not grant live trading authority by themselves.
`pyproject.toml` uses the normal `src/` package layout, so package imports should
use `trading_bot.*`, not `src.trading_bot.*`. Fresh checkouts should run
`pip install -e .` or set `PYTHONPATH=src` before invoking packaged modules.
`pyproject.toml` also declares optional extras for metadata and future packaging:
`runtime`, `research`, `dashboard` (`streamlit`), `timescale` (`asyncpg`),
`sentiment` (`transformers`), `webull` (`webull-openapi-python-sdk`), and `dev`.
Docker and CI still use the
requirements files as the operational install source.

Webull is configured as a read-only diagnostic integration until parity and
ledger evidence justify expanding authority. The Alpaca runtime now uses
`alpaca-py` for broker REST compatibility and trade-update streaming; the
legacy `alpaca-trade-api` package is no longer part of runtime requirements.
Webull remains optional and should be validated through an isolated adapter venv
until provider parity and account-device behavior are stable. The `runtime` and
`webull` extras are marked conflicting for `uv` because Webull requires
`protobuf<6` while the runtime stack currently pins `protobuf==7.35.0`:

```bash
python3 -m venv venv-webull
./venv-webull/bin/pip install -U pip
./venv-webull/bin/pip install -e .
./venv-webull/bin/pip install alpaca-py==0.43.4 webull-openapi-python-sdk==2.0.10
```

Store credentials outside git, normally in `/etc/trading-bot.env`:

```bash
WEBULL_API_KEY=...
WEBULL_API_SECRET=...
WEBULL_ACCOUNT_ID=...
WEBULL_REGION=US
WEBULL_OVERNIGHT_REQUIRED=false
WEBULL_EXTENDED_HOURS_REQUIRED=false
```

Validate readiness and quote parity:

```bash
python ops_check.py webull-readiness
TRADING_BOT_SKIP_VENV_REEXEC=1 \
  PYTHONPATH=/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot/src:/home/tradingbot/trading-bot \
  ./venv-webull/bin/python ops_check.py webull-market-data-parity AAPL
```

The Webull SDK may require app-side device registration or 2FA before quote
calls succeed. If the parity command returns `NO_AVAILABLE_DEVICE`, complete
the latest Webull app 2FA/device verification and rerun the command. The SDK
token cache is ignored via `conf/` and must not be committed.

The Webull adapter is diagnostic-only in this phase. It does not route orders,
increase size, approve trades, or replace Alpaca/Polygon as the ML training
source. Its first role is provider redundancy: quote freshness, bid/ask spread,
and cross-provider parity evidence for execution-quality scoring.

Container build targets are split the same way:

```bash
docker build --target runtime -t tradingbot-runtime .
docker build --target research -t tradingbot-research .
docker run --rm tradingbot-research python tests/test_dependency_packaging_contract.py
```

Before moving any live service into a slim container, run fallback-focused tests
inside the `runtime` target with heavy ML dependencies absent. That validates the
optional-dependency fallback branch separately from the research image where ML
dependencies are present.

For SQLite, reason about write ownership per database file. Keep `trades.db`,
`predictions.db`, and `jobs.db` on same-host bind mounts, never NFS/network
volumes, and run at most one writer for any given DB file. The live runtime
should own live order/trade writes; research jobs may run concurrently only when
their writes are isolated to separate DB files or read-only access.

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

scripts/live_bar_stream.py

Optional Alpaca `alpaca-py` closed-bar listener.

Responsibilities:

Subscribes to live 1-minute bars.
Gap-fills missing rolling context through the shared market-data service after startup/reconnect.
Updates session_momentum through SessionMomentumService.
Feeds the same bars into bar_pattern_features for EFI/PVT, candle physics, order-flow proxy, fractional-memory, triple-barrier, and trend-scanning learning.

Runtime effect:

observe_only_bar_learning_no_direct_order_authority

It does not submit orders and does not bypass auto-buy, approval, sizing, or execution gates.

Usage:

python3 scripts/live_bar_stream.py --symbol AAPL
python3 scripts/live_bar_stream.py --symbol AAPL,MSFT,NVDA --feed iex
python3 scripts/live_bar_stream.py --all --feed iex

Use `--feed sip` only when the Alpaca account has paid consolidated data. IEX can be useful for paper learning, but its volume/VWAP can differ materially from Polygon/SIP history.

Live bar-pattern capture verification:

```bash
python3 ops_check.py live-bar-pattern-capture 2026-06-08 --max-age-minutes 10 --min-symbols 1
```

During regular trading hours this report verifies that the session-momentum
capture path is producing fresh target-date `bar_pattern_features` rows for the
paper ensemble. Outside the active session it remains a report-only sanity check
and does not grant model authority.

pipeline/historical_bar_archive.py

Offline Polygon archive/backfill job for 1-minute regular-session bars.

Responsibilities:

Archives Polygon 1-minute RTH bars for one or more symbols.
Caches CSVs under `data/historical_bars/polygon_1min` by default.
Feeds the same bars into `bar_pattern_features` unless `--no-patterns` is supplied.
Provides historical candle-physics, order-flow proxy, fractional-memory, triple-barrier, and trend-scanning labels for ML/replay research.

Usage:

python3 pipeline/historical_bar_archive.py --date 2026-06-03 --symbol AAPL
python3 pipeline/historical_bar_archive.py --start-date 2026-06-01 --end-date 2026-06-03 --symbol AAPL,MSFT
python3 pipeline/historical_bar_archive.py --date 2026-06-03 --all

This is an offline learning job only. It does not place orders or grant live authority.

pipeline/historical_bar_backfill.py

Chunked multi-month or multi-year Polygon backfill for ML training history.
Use this instead of a single giant archive invocation when building the local
historical bar corpus.

Recommended sequence:

```bash
# 1. Confirm Polygon access and chunk shape without writing.
python3 pipeline/historical_bar_backfill.py \
  --start-date 2024-06-01 \
  --end-date 2026-06-04 \
  --symbol AAPL \
  --chunk-days 30 \
  --max-chunks 1 \
  --dry-run

# 2. Backfill the approved universe in resumable chunks.
python3 pipeline/historical_bar_backfill.py \
  --start-date 2024-06-01 \
  --end-date 2026-06-04 \
  --all \
  --chunk-days 120 \
  --request-sleep-seconds 13 \
  --retry-attempts 3 \
  --retry-sleep-seconds 20

# 3. Verify DB feature coverage before using the data for model claims.
python3 ops_check.py historical-bar-coverage \
  2024-06-01 \
  --end-date 2026-06-04 \
  --min-days 252 \
  --min-symbols 20

python3 ops_check.py historical-bar-progress \
  2024-06-01 \
  --end-date 2026-06-04 \
  --min-days 252 \
  --min-symbols 20 \
  --limit 20

python3 ops_check.py historical-bar-readiness \
  2024-06-01 \
  --end-date 2026-06-04 \
  --min-days 252 \
  --min-symbols 20

# 4. After the broad pass, build a focused retry plan for only the tail.
python3 ops_check.py historical-bar-retry-plan \
  2024-06-01 \
  --end-date 2026-06-04 \
  --max-symbols 10
```

The backfill writes chunked CSVs under `data/historical_bars/polygon_1min` and
persists the derived `bar_pattern_features` rows used by supervised training,
advanced-alpha readiness, pattern-learning reports, and research exports.

The coverage report prints both aggregate readiness and per-symbol balance:
minimum/median/maximum symbol rows, symbols meeting the configured market-day
floor, and a symbol-imbalance ratio. Treat `training_ready=True` as a configured
dataset floor, not proof that every approved symbol has equivalent history.
The progress report adds approved-universe awareness, latest manifest status,
recent manifest errors, and a prioritized list of symbols still below the
market-day floor. It is cache/manifest based so it stays fast while backfills
run. `historical-bar-readiness` combines cache progress, latest manifest state,
feature-family readiness, and completion-hook status; by default it skips
expensive DB scans so it is safe during active backfills. Add
`--include-db-quality` after the backfill finishes to scan persisted rows for
OHLCV nulls, invalid price ranges, feature missing rates, and optional
`--include-duplicate-scan` duplicate checks. When the scan is skipped, DB-only
metrics print as `not_scanned` rather than zero. Use
`historical-bar-coverage` for DB-derived aggregate training readiness. Use
`historical-bar-retry-plan` after a broad run to prioritize only symbols below
the day floor and symbols tied to recent manifest errors; add `--execute` only
when you want it to launch the focused retry backfill. Header-only/empty cache
CSVs do not count toward coverage, and `--skip-existing-cache` retries them
rather than treating them as complete.

The after-close learning loop also runs
`pipeline/historical_bar_completion_hook.py`. This hook watches the cache/
manifest readiness fingerprint and triggers guarded observe-only retraining only
once a new historical-bar coverage floor is crossed. It stores state under
`runtime_state/historical_bar_training_hook_state.json`, skips repeated training
for the same readiness fingerprint, and still cannot promote or alter live
authority.

Build or inspect the canonical ML training export after coverage is acceptable:

```bash
python3 ops_check.py ml-dataset-export \
  2024-06-01 \
  2026-06-04 \
  --min-rows 500 \
  --min-symbols 20 \
  --max-rows 5000

python3 ops_check.py ml-dataset-export \
  2024-06-01 \
  2026-06-04 \
  --output research_exports/ml_training_dataset_20240601_20260604.jsonl \
  --format jsonl \
  --max-rows 0
```

`ml-dataset-export` uses `ml_platform.dataset_builder`, writes an adjacent
manifest when `--output` is supplied, and remains export-only with no live
authority. The default `--max-rows 5000` keeps operator checks responsive while
the archive is large; use `--max-rows 0` only for an intentional full export.
Operator exports write a lightweight manifest by default. Add
`--full-manifest` when you intentionally want full DB/policy hashing for an
audited dataset snapshot.

Historical bar contract:

- cached CSVs include OHLCV, VWAP, source, adjusted flag, and inclusive interval-start metadata
- `bar_pattern_features` persists raw OHLCV/VWAP plus engineered RSI/EMA/MACD, candle physics, EFI/PVT, CVD/VPIN proxies, fractional-memory, triple-barrier, and trend-scan fields
- supervised training consumes normalized/derived features, not raw absolute price levels, so cross-symbol models are less likely to learn ticker price scale instead of behavior
- intra-bar open/high/low/close event timestamps require tick-level data; Polygon 1-minute aggregate bars do not provide those timestamps
- tick, volume, and dollar bars remain a future data-sampling layer once transaction-level data is archived

Tick-level Polygon probe:

```bash
python3 pipeline/polygon_tick_archive.py \
  --date 2026-06-04 \
  --symbol AAPL \
  --limit 50000 \
  --dry-run
```

If the command returns trades, remove `--dry-run` to cache raw transactions
under `data/historical_ticks/polygon_trades`. If it returns an entitlement
or plan error, the current Polygon subscription does not expose tick-level
historical trades.

ML advanced per-bar integration

`bar_pattern_features` is now part of the ML/export surface:

Included feature families:

candle body/wick ratios
close location within candle range
ATR-normalized range
volume-normalized pressure vectors
EFI/PVT pattern labels and opportunity scores
CVD/order-flow proxy metrics
VPIN-style toxicity proxy
fractional-differentiated close memory
trend-scanning t-stat and trend horizon labels

Included target:

triple_barrier_label
trend_scan_label

These features and targets are available for observe-only training/research. ETF lead-lag vectors and options-skew signals still require additional reference/options feeds before they can be populated. Promotion into live authority still requires model-readiness, calibration, stability, and rollout-governance checks.

Train observe-only models directly from the completed historical bar archive:

```bash
python3 pipeline/train_historical_bar_model.py \
  --start-date 2024-06-01 \
  --end-date 2026-06-04 \
  --label-target triple_barrier_label \
  --rows-per-symbol 1000 \
  --limit 60000 \
  --skip-suite \
  --baseline-only

python3 pipeline/train_historical_bar_model.py \
  --start-date 2024-06-01 \
  --end-date 2026-06-04 \
  --label-target trend_scan_label \
  --rows-per-symbol 1000 \
  --limit 60000 \
  --skip-suite \
  --baseline-only
```

This path reads current-version `bar_pattern_features` directly, writes
candidate diagnostics/artifacts under `ml/models/historical_bar_patterns_v1`,
and remains `observe_only_no_live_authority`. It is the fastest way to verify
that the multi-year Polygon bar backfill is being consumed by ML without
requiring a matching multi-year `feature_snapshots` table.
Use `--rows-per-symbol` for balanced universe sampling; a plain chronological
global limit can overrepresent the earliest symbols in the archive. Use
`--skip-suite --baseline-only` for routine validation; omit `--baseline-only`
for sklearn training, and omit both flags for heavier after-hours comparative
model training.

Readiness command:

```bash
python3 ops_check.py advanced-alpha-readiness 2026-06-04
python3 ops_check.py advanced-alpha-comparison 2026-06-04
python3 ops_check.py volume-clock-vpin 2026-06-08 --symbol QQQ --start-time 09:30 --end-time 10:00
python3 ops_check.py volatile-session-intelligence 2026-06-08 --symbols QQQ,AAPL,NVDA,MSFT,AMD,TSLA
python3 ops_check.py historical-bar-models
python3 ops_check.py historical-bar-paper-strategy AAPL --action buy
python3 ops_check.py historical-bar-paper-validation 2024-06-01 --end-date 2026-06-04
python3 ops_check.py historical-bar-paper-validation 2024-06-01 --end-date 2026-06-04 --thresholds 55,60,65,70
python3 ops_check.py historical-bar-walk-forward 2024-06-01 --end-date 2026-06-04
python3 ops_check.py historical-bar-validation 2024-06-01 --end-date 2026-06-04 --label-target triple_barrier_label
python3 ops_check.py monday-readiness
python3 ops_check.py exit-intelligence 2026-06-04
python3 ops_check.py sqlite-ownership
python3 ops_check.py operator-intelligence 2026-06-04
```

These reports distinguish the currently integrated bar-level proxies from true trade-level order flow, ETF/component lead-lag, and options-skew features that still require external feeds or mappings. The comparison report also shows whether an asymmetric false-positive guard would have reduced bad pattern candidates without granting authority.
`historical-bar-models` reports latest observe-only historical-bar model
candidates, threshold failures, and artifact hygiene. Add `--prune` for a
dry-run cleanup plan, and add `--execute-prune` only when you intentionally
want older non-protected binaries removed. Diagnostics are preserved.
The latest diagnostics are also summarized by
`services/historical_bar_model_intelligence_service.py` and included in
canonical `analytics_state.historical_bar_model_intelligence` as
observe-only evidence. That payload is report/replay context only: it does not
load model binaries, block trades, size orders, submit orders, or affect the
live decision policy without a separate approved authority path.
`historical-bar-paper-strategy` combines ready historical-bar diagnostics,
current bar-pattern features when available, a naive baseline comparison, and
portfolio correlation friction into a paper-only master confidence score and
paper sizing recommendation. By itself this report remains non-authoritative,
but the broader `layered_model_authority` can consume it as the Level 1/Level 2
model evidence for paper/dry-run approval, veto, and size-increase decisions
after hard gates pass. It still has no cash-live authority and cannot submit
orders directly.
`historical-bar-paper-validation` compares the paper ensemble score against a
naive RSI/SMA/close-location baseline on labeled historical bars, reporting hit
rate delta, false-positive avoidance, and false-negative cost. `historical-bar-
walk-forward` repeats that comparison over chronological folds so one strong
period does not masquerade as stable intelligence.
Use `--thresholds 55,60,65,70` to sweep paper candidate thresholds and surface
the best observe-only threshold plus blockers before any paper soft-modifier
promotion is considered.
`historical-bar-validation` reports label distributions by symbol, session
phase, volatility, CVD, VPIN, and fractional-memory buckets. `monday-readiness`
summarizes market context presence, Polygon key configuration, current
historical-bar symbol coverage, observe-only model candidate readiness, and
advisory full-window cache gaps.
`exit-intelligence` summarizes canonical exit snapshots by trigger and symbol,
including capture ratio, missed upside, post-exit recovery, and avoided
drawdown. `sqlite-ownership` documents the per-DB one-writer rule for container
planning. `operator-intelligence` is the compact dashboard view that points the
operator to the next validation reports; it is dashboard-only and has no live
authority.

Off-hours historical-bar learning pipeline:

```bash
python3 pipeline/off_hours_historical_bar_learning.py \
  --start-date 2024-06-01 \
  --end-date 2026-06-04 \
  --dry-run
```

Long-running retry command for direct SSH/session use:

```bash
cd /home/tradingbot/trading-bot
set -a; source /etc/trading-bot.env; set +a
./venv/bin/python job_runner.py \
  --job-name historical_bar_weekend_retry \
  --lock-file /tmp/tradingbot_historical_bar_weekend_retry.lock \
  --log-file /home/tradingbot/trading-bot/historical_bar_weekend_retry.log \
  -- ./venv/bin/python pipeline/off_hours_historical_bar_learning.py \
       --start-date 2024-06-01 \
       --end-date 2026-06-04 \
       --max-symbols 10 \
       --execute-retry
```

Repeat the retry command until `python3 ops_check.py historical-bar-progress
2024-06-01 --end-date 2026-06-04` shows `symbols_ready=59` and no remaining
empty-cache advisory items. Then rerun the same off-hours pipeline with
`--train` to refresh observe-only candidates from the larger repaired archive.

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
setup-quality conditions are met. The layered model stack can also approve or
increase paper/dry-run size when the Level 0-3 evidence clears configured
thresholds. Predictions and model layers still do not place orders directly,
do not loosen hard gates, and do not grant cash-live approval. Hard prediction
blocking remains disabled unless `PREDICTION_GATE_MODE=hard` is explicitly
promoted after paper-session validation.

The correct roadmap path is:

observe-only
→ validation report
→ warn-only
→ soft modifier
→ possible hard gate much later

Current learning-readiness posture:

- Runtime job health, candidate forward-outcome coverage, and approved exit
  linkage are expected to be repaired by the after-close pipeline.
- Candidate forward-outcome coverage target is at least 95% in
  `pipeline.learning_backfill_repair`; learning readiness only requires 80%.
- Missing calibration buckets during early paper collection are not a plumbing
  failure. They remain a promotion blocker until enough realized lifecycle
  outcomes exist.
- Authority promotion still requires sufficient integrated outcomes, calibration
  evidence, and explicit operator review.

## ML Platform and Staged Integration

The ML platform is now split between a research/audit lane and a bounded
paper-authority lane. Research artifacts, diagnostics, retraining jobs, and
candidate reports remain separate from live webhook, broker, order, and hard
risk-control paths. In paper/dry-run mode only, `layered_model_authority` can
use promoted in-process evidence to approve, veto, or increase size after hard
deterministic gates pass.

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

Approved-symbol universe changes have a separate after-close trigger:

```bash
python3 pipeline/symbol_universe_retrain.py --date 2026-06-05
```

The trigger records the current `symbols_config.py` approved-symbol fingerprint
on first run. Later additions/removals are detected by hash. Added symbols must
first meet bar-pattern coverage gates (`--min-bar-rows`, `--min-bar-days`). If
an added symbol is not coverage-ready, the trigger automatically calls the
chunked Polygon archive:

```bash
python3 pipeline/historical_bar_backfill.py \
  --start-date 2024-06-01 \
  --end-date 2026-06-05 \
  --symbol NEW1,NEW2 \
  --skip-existing-cache
```

That backfill writes cached CSV chunks and persists derived v4
`bar_pattern_features`. After backfill, the trigger reassesses coverage; when
coverage passes, it calls `pipeline/retrain.py --force --rerun-completed`. The
result is still observe-only candidate training and cannot change live
authority. Pending coverage and last-trained universe state are stored in
`runtime_state/symbol_universe_training_state.json`.

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

Operational SQLite backups are handled by `pipeline/database_backup.py`.
It uses SQLite's online backup API, writes a JSON manifest under
`backups/databases/`, and verifies each copied DB with `PRAGMA integrity_check`.
The default target set is `trades.db`, `predictions.db`, and `jobs.db`; missing
optional DB files are reported in the manifest without failing the backup if at
least one DB verifies.

```bash
python3 pipeline/database_backup.py
python3 ops_check.py database-backups
```

The tracked cron snapshot runs the verified backup weekly after Friday close.
Because `trades.db` can be tens of GB, increase backup frequency only after
checking available disk and retention impact.

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
python3 ops_check.py local-load-probe --requests 100 --concurrency 4 --symbol AAPL --action buy
python3 ops_check.py paper-replay-load-probe --requests 100 --concurrency 4 --symbol AAPL --action buy
python3 ops_check.py full-session-paper-replay --symbols AAPL,MSFT --execute --max-requests 1000
python3 ops_check.py incident-workflow --title "brief title" --severity medium --create
python3 ops_check.py incident-escalation-readiness
python3 ops_check.py config-audit
python3 ops_check.py feature-flags --limit 40
python3 ops_check.py feature-flag-change-history
python3 ops_check.py feature-flag-change-history --append --flag LIVE_TRADING_ENABLED --old false --new false --operator USER --approval REF --rollback "set false"
python3 ops_check.py model-governance --min-rows 5000 --min-symbols 20 --min-accuracy 0.50
python3 ops_check.py model-promotion-evidence --write --execute-replay --max-requests 1000 --symbols AAPL,MSFT --operator USER --approval REF
python3 ops_check.py packaged-entrypoints
python3 ops_check.py external-observability-readiness
python3 ops_check.py secrets-manager-readiness
python3 ops_check.py architecture-surface
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

`ops_check.py config-audit` validates typed config factories against the current
environment, inventories raw env-var access, and flags unsafe runtime defaults.
Use it after changing `/etc/trading-bot.env`, adding a new env flag, or changing
config factory behavior. It is diagnostic-only and does not mutate config.

`ops_check.py architecture-surface` tracks the structural cleanup roadmap:
root Python file count, direct service/repository module counts, oversized
runtime decision files, raw env access, `src/trading_bot` skeleton readiness,
and the compatibility deletion plan. It intentionally returns a warning until
the repo is within the cleanup targets.

Phase 2 web-runtime cleanup has begun: `src/trading_bot/web/app_factory.py`
owns Flask app creation and route registration, and
`src/trading_bot/runtime/startup.py` owns startup-service wiring.
`src/trading_bot/config/runtime.py` owns app-specific runtime settings parsing.
Root `app.py` delegates to these package modules while remaining the deployed
runtime compatibility context.
Remaining Phase 2 work is reducing root `app.py` to a small compatibility shim,
packaging more runtime context, and updating Gunicorn/systemd only after smoke
tests prove the packaged entrypoint.

Ops-check cleanup has also begun: root `ops_check.py` is now a small
compatibility shim delegating to `src/trading_bot/ops_checks/cli.py`, and
command specs are grouped under `src/trading_bot/ops_checks/commands/`.
The remaining ops-check cleanup target is splitting the packaged CLI handler
functions into those command modules.

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

Install and run the local development guardrails:

```bash
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/pre-commit install
./venv/bin/python run_safety_checks.py
```

CI runs the same fast safety harness from `.github/workflows/ci.yml` on push to
`main` and pull requests.

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
1. Operational audit follow-up

Status: Active.

Completed from the June 8 audit follow-up:

CI fast safety workflow
local pre-commit guardrails
core safety/authority/dependency/architecture tests
runtime/research dependency split
configuration audit diagnostics
verified SQLite database backup/restore-readability manifests
lightweight observability summary through `ops_check.py observability-health`
local secrets-hygiene diagnostic
local webhook burst diagnostic through `ops_check.py local-load-probe`
temporary-DB paper replay/load diagnostic through `ops_check.py paper-replay-load-probe`
full-session paper replay diagnostic through `ops_check.py full-session-paper-replay`
local incident/postmortem workflow through `ops_check.py incident-workflow`
incident escalation readiness through `ops_check.py incident-escalation-readiness`
feature-flag inventory through `ops_check.py feature-flags`
feature-flag change-history validation through `ops_check.py feature-flag-change-history`
consolidated model-governance diagnostic through `ops_check.py model-governance`
model-promotion evidence generation through `ops_check.py model-promotion-evidence`
packaged entrypoint validation through `ops_check.py packaged-entrypoints`
external observability readiness through `ops_check.py external-observability-readiness`
external secrets manager readiness through `ops_check.py secrets-manager-readiness`

External items still open before any cash-live promotion:

configure external observability/alerting endpoints
choose/configure external secrets manager provider
full-day paper replay with realistic market-data cadence
external incident escalation/review process
external change-approval history for cash-live feature-flag changes
real market-session evidence beyond the accepted historical/replay surrogate

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

Status: Complete for the live signal path; Phase 2 web-runtime extraction is
partially complete.

Current ownership:

app.py remains the deployed Flask compatibility root and runtime context holder.
src/trading_bot/web/app_factory.py owns Flask app creation and route
registration mechanics.
src/trading_bot/runtime/startup.py owns startup-service wiring.
src/trading_bot/config/runtime.py owns app-specific runtime settings parsing.
SignalPipeline owns runtime flow entry.
LiveSignalProcessor owns live signal orchestration.
ApprovalService owns deterministic and Claude/confidence decisions.
SizingService owns final sizing.
ExecutionService and execution adapters own approved order execution.
TradeAuditService owns execution/rejection persistence.

Next app-level work should be compatibility-shim reduction only, not trading
behavior migration.

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
Live-session prediction promotion remains blocked until enough clean observed
sessions prove stability across regimes. Historical-bar candidates can provide
observe-only/paper validation evidence, but reconstructed outcomes and
backfilled labels should not be treated as cash-live proof by themselves.
Holiday targeting is now improved, but early closes are not modeled.
Prediction data can reduce size only where explicitly wired through governed
downside-only policy; it should not be used as a broad hard live gate yet.
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
