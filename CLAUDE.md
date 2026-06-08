# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

The project is an automated AI-assisted trading bot. It currently runs in paper trading with layered safety controls, pre-market intelligence, event scoring, prediction reporting, and service-owned live signal orchestration. Do not change live trading behavior unless explicitly instructed.

---

## Current Project Status

The bot is operational in paper trading.

Recent completed roadmap items:

- `app.py` is now a Flask composition/runtime compatibility root: startup entry point, runtime compatibility context, container selection, and the public `process_signal()` compatibility wrapper. Flask app construction and route registration mechanics live in `src/trading_bot/web/app_factory.py`; startup-service wiring lives in `src/trading_bot/runtime/startup.py`; app-specific runtime settings parsing lives in `src/trading_bot/config/runtime.py`.
- Live signal orchestration is owned by `services/live_signal_processor.py`; approval gates, sizing, execution, context runtime, audit persistence, and repositories are service-owned.
- The legacy live processor, `execute_legacy`, `run_legacy_*` service names, and app-level `log_trade` / `log_rejection` shims have been removed.
- Architecture tests enforce approved DB, broker, market-data, Flask, repository, policy, report, and runtime boundaries. Temporary architecture allowlists are empty and expected to stay empty.
- Report, ops, runtime, ML, and backfill DB/market-data access has been migrated behind repositories/services.
- `/status` exposes read-only `symbol_intelligence`, prediction-cache state, policy-artifact state, runtime config, and service-owned route payloads.
- `prediction_validation_report.py` exists.
- `ops_check.py prediction-validation DATE` works.
- `ops_check.py conviction-persistence-health DATE [--samples N]` verifies that BUY rows persist setup, prediction, session, strategy, buy-opportunity, and sizing attribution fields.
- `ops_check.py conviction-stack-report DATE`, `peak-bucket-report DATE`, and `winner-became-loser DATE` are the current first-line trading-performance diagnostics.
- `next_trading_date.py` uses holiday-aware market calendar helpers from `market_time.py`.
- `market_context.json` validation uses the expected trading session, so weekend/holiday context can target the next market day.
- `export_ml_dataset.py` can write an audit manifest with `--manifest-output`.
- `ml_platform` has a staged observe-only integration lane through `staged-readiness`.
- `retraining-readiness` reports current blockers and never promotes automatically.
- `pipeline/validate_predictions.py` runs in the pre-market pipeline as a
  warning-only drift check for recent `prediction_score` correlation.
- `pipeline/retrain.py` can train candidate ML artifacts after prediction
  validation decay, but registry writes are metadata-only and promotion beyond
  `warn_only` requires explicit operator approval.
- Prediction drift checks use available joined prediction/outcome sessions, not
  calendar days; long weekends/holidays are not treated as failed sessions.
  Empty/partial coverage is explicit via `coverage_status`.
- Automated retraining uses `/tmp/tradingbot_ml_retrain.lock` and a default
  1800-second max-runtime guard. It also lowers process priority and applies a
  default 4 GB memory cap.
- Retraining writes a per-date completion marker and a `.diagnostic.json`
  companion file beside candidate model artifacts.
- Automated retraining now also writes an observe-only quant model suite
  comparison for baseline, RandomForest, and XGBoost when the optional packages
  are installed. This is diagnostic evidence only; it cannot promote, size,
  block, approve, or execute trades.
- Paper learning authority is enabled by default for paper/dry-run only. After
  hard blockers and deterministic pipeline gates have passed, it may convert a
  Claude low-confidence soft rejection into a capped paper approval when
  canonical setup quality and buy-opportunity scores are strong. It must never
  apply in `cash_safe`/`cash_full`, never override stale/broker/account/macro/
  explicit-symbol hard blockers, and never override Claude parse/engine errors.
- Retraining reads training rows through a point-in-time guard
  (`feature_available_at <= prediction_time_cutoff`) and prunes unprotected old
  binary artifacts while keeping diagnostic JSON.
- `pipeline/symbol_universe_retrain.py` runs inside the after-close learning
  loop before drift-based retraining. It fingerprints approved symbols from
  `symbols_config.py`, baselines the current universe on first run, runs
  `pipeline/historical_bar_backfill.py` for added symbols that lack
  bar-pattern coverage, then calls guarded retraining with `--force
  --rerun-completed` once coverage gates pass. It is observe-only and cannot
  promote or alter live authority.
- `pipeline/historical_bar_completion_hook.py` also runs in the after-close
  loop. It watches cache/manifest historical-bar readiness, records a runtime
  readiness fingerprint, and triggers guarded observe-only retraining once a
  new coverage floor is reached. It skips repeated training for the same
  fingerprint and cannot promote or alter live authority.
- `pipeline/after_close_learning.py` is the recurring after-close quant
  learning loop. It completes rejected/candidate/exit outcomes, refreshes
  report-memory artifacts, writes DuckDB/PyArrow research exports, runs
  pattern/feature/post-trade/readiness reports, audits paper-learning authority
  outcomes, runs guarded retraining/model comparison, registers policy
  artifacts, and archives point-in-time state. `run_after_close_learning.sh`
  invokes it under the existing cron `job_runner.py` lock/ledger path and
  should remain a scheduler wrapper only.
- `pipeline/post_session_review.py` owns post-session review sequencing. It
  keeps review/report warnings warn-only so `run_post_session_review.sh` does
  not look like a failed runtime job when diagnostics are simply reporting
  issues to inspect.
- `ops_check.py paper-learning-authority YYYY-MM-DD` reports paper-only
  learning overrides, lifecycle linkage, realized outcomes, MFE, and
  counterfactual outcome availability. It is diagnostic evidence only and must
  not be treated as live/cash promotion.
- `ops_check.py advanced-alpha-readiness YYYY-MM-DD` reports readiness for
  bar-level order-flow proxies, true trade-level VPIN, ETF lead-lag, options
  skew, fractional-memory/trend-scan features, asymmetric-loss comparison, and
  model monitoring. It is readiness-only and must not be treated as authority.
- `ops_check.py advanced-alpha-comparison YYYY-MM-DD` compares standard score
  thresholding against an asymmetric false-positive guard using linked forward
  outcomes. It is diagnostic-only and must not be treated as authority.
- `ops_check.py friction-heatmap YYYY-MM-DD` reports LSI/VPIN bucketed
  symmetric-vs-asymmetric stop-outs and toxic stop-outs avoided. The Streamlit
  dashboard at `dashboards/friction_heatmap_dashboard.py` reads the same
  payload and remains read-only.
- Slippage-adjusted fractional Kelly sizing is a final BUY size cap only. It
  may reduce or zero size when predicted slippage or LSI/VPIN stress erodes
  ATR-based reward/risk, but it must never approve trades, increase size, or
  bypass execution safety.
- The pre-market pipeline may write `shadow_predictions` for candidate models;
  this is observe-only and must not be read by live execution. Operators compare
  it with `python3 ops_check.py shadow-predictions YYYY-MM-DD`.
- Configured ML models are checked for registry/artifact staleness before ML
  authority can enforce. Stale/missing model metadata falls back to
  deterministic policy with no ML authority.
- `ml/models/similarity_v0/` is research-only metadata with no trained artifact.
- `run_staged_tests.py` runs ahead-of-live staged integration tests separately from current behavior tests.
- `replay-decisions` is a read-only decision-delta audit. It can join changed
  replay decisions to realized `matched_trades` and counterfactual
  `rejected_signal_outcomes`, but it must not affect runtime decisions.
- `broker.py` has validation/unit coverage for core order-flow boundaries.
- `broker.py` now polls for Alpaca bracket-order cancellation before market
  sells instead of assuming cancellation completes after a fixed sleep.
- `ops/db_connection_audit.py` reports manual SQLite connection assignments for gradual cleanup.
- `db_migrations.py` tracks idempotent schema migrations.
- `feature_snapshots` includes ML leakage/audit fields:
  `feature_available_at`, `feature_generated_at`, `feature_age_seconds`,
  `source`, `is_stale`, and `staleness_reason`.
- `decision_snapshots` stores immutable point-in-time context for new
  approved/rejected decisions.
- `auto_buy_outcome_report.py` compares internal auto-buy candidates against
  forward feature-snapshot returns, score buckets, and the TradingView signal
  baseline.
- Auto-buy live paper execution cross-checks shared app cooldowns, recent-sell
  churn state, per-symbol daily app buys, and correlation-cluster exposure
  before calling the broker.
- Auto-buy can operate from internal bar-derived candidates across the approved
  universe when `AUTO_BUY_SIGNAL_MODE=internal_all` and
  `AUTO_BUY_LIVE_BUYS=true`. It now records `early_constructive_build`,
  `mature_chase`, and `extreme_chase` so post-session review can distinguish
  early accumulation/reclaim opportunities from late momentum chasing.
- Auto-buy has a paper/dry-run-only strong-evidence promotion path. It may
  promote a candidate blocked only by setup conservatism when score, setup,
  session, 15m/30m momentum, and non-weak ML evidence all clear explicit
  thresholds. It records `paper_strong_evidence_*` fields and must not override
  weak ML, intraday losing-pattern feedback, extreme chase, broker/account,
  stale-data, macro/regime, or cash-mode blockers.
- Auto-buy paper defaults are broader than cash defaults: paper/dry-run allows
  more per-run/daily candidate executions, watch-setup promotion when score is
  strong, and lower learned-tiebreaker sample requirements. Cash modes keep the
  tighter defaults unless explicitly configured otherwise.
- `position_manager.py` partial exits are fail-safe around open-order state:
  cancel-first cycles wait for the next pass before submitting, and Alpaca
  available-quantity errors return non-submitted results instead of crashing the
  job.
- `archive_context_state.py` snapshots market context, override hashes, policy
  artifact hashes, and symbol-universe version for future replay.
- `policy_artifacts.py` registers after-close learning artifact sets, tracks a
  known-good pointer, and can roll back runtime policy artifacts without
  touching broker/order state.
- Decision policy authority is explicit and paper-only by default:
  `DECISION_POLICY_AUTHORITY_MODE=paper_only`,
  `DECISION_POLICY_LIVE_BLOCK=true`, and
  `DECISION_POLICY_LIVE_SIZE_DOWN=true`. Treat it as conservative, under
  review, and not promoted while `policy_backtest_summary.json` says
  `policy_too_loose`.
- Migrations are manual before deploy/restore, but pending migrations are
  surfaced by `morning_check.py`, `ops_check.py premarket`, and
  `ops_check.py migration-status`.
- Operational SQLite backups are handled by `pipeline/database_backup.py`.
  The backup service covers `trades.db`, `predictions.db`, and `jobs.db`, writes
  manifests under `backups/databases/`, and verifies copied DB files with
  `PRAGMA integrity_check`. Check freshness with `ops_check.py database-backups`.
- Local webhook burst diagnostics are available through
  `ops_check.py local-load-probe --requests N --concurrency N --symbol AAPL --action buy`.
  The probe exercises Flask route auth, payload parsing, event-record callback,
  and signal-submit callback only; it is diagnostic-only and cannot submit
  broker orders or mutate trading state.
- Temporary-DB paper replay/load diagnostics are available through
  `ops_check.py paper-replay-load-probe --requests N --concurrency N --symbol AAPL --action buy`.
  This extends the local route probe with SQLite signal/fill callback writes
  while still avoiding broker orders.
- Local incident records are available through
  `ops_check.py incident-workflow --title "brief title" --severity medium --create`.
  Records are written under `ops/incidents/` and should link job runs, logs,
  order/fill evidence, learning artifacts, model artifacts, and commits.
- Feature-flag inventory is available through `ops_check.py feature-flags`.
  It infers owner, authority level, and rollback action from static env-var
  references; cash-live promotion still requires explicit human ownership and
  default/change-approval metadata for high-authority flags.
- Consolidated model-governance diagnostics are available through
  `ops_check.py model-governance`. This report checks candidate diagnostics,
  observe-only runtime effect, basic quality thresholds, and registry
  live-status blockers; it cannot promote or load models.
- External observability and secrets-manager readiness are checked with
  `ops_check.py external-observability-readiness` and
  `ops_check.py secrets-manager-readiness`. These reports validate metadata
  only and make no network calls or secret reads.
- App startup no longer owns schema `ALTER TABLE` migration work.
- Webhook/status secrets should use `X-Webhook-Secret` or
  `Authorization: Bearer ...`; query-string secrets are rejected unless
  `ALLOW_QUERY_STRING_SECRET=true` is explicitly set for temporary compatibility.
- Prediction gate mode defaults to warn-only for hard blocking until labeled
  paper-session outcomes justify promotion.
- Cached ML predictions are still conservative: weak prediction evidence can
  apply logged downside size caps, but prediction scores cannot place orders,
  loosen gates, increase size, or override broker/order safeguards.
- `prediction_cache.py` is the only runtime-safe path for
  `daily_symbol_predictions` in the live signal path: preload/background
  refresh outside webhook handling, 60-second TTL, memory-only signal-path
  reads, fail-open to no ML prediction, and hard clipping of numeric prediction
  outputs before runtime context.
- `decision_snapshots` use feature semantic version
  `decision_snapshot_features_v4`. Canonical intelligence includes compact
  observe-only `analytics_state` from the predictive/descriptive/diagnostic/
  prescriptive AI analytics toolkit.
- Optional TimescaleDB tick storage is enabled only by `TIMESCALE_DB_URI`.
  `services/live_features_service.py` mirrors compact ticks through
  `services/timescale_tick_writer_service.py`; this path is storage-only and
  has no order, sizing, or risk-gate authority.
- `requirements.txt` delegates to `requirements-base.txt`, the slim runtime
  dependency subset. `requirements-research.txt` layers DuckDB/PyArrow research
  exports, sklearn/joblib supervised artifacts, XGBoost candidates, torch
  Transformer authority candidates, and hmmlearn HMM regime artifacts for
  reproducible local research/test runs. These dependencies remain observe-only
  unless separately promoted through tests, reports, and explicit operator review. The runtime
  container target intentionally excludes those heavy optional dependencies, so
  fallback behavior must be tested with the runtime target as well as the
  research target.
- The project uses normal `src/` package discovery. Runtime package imports
  should use `trading_bot.*`, not `src.trading_bot.*`. Fresh checkouts should run
  `pip install -e .` or set `PYTHONPATH=src` before invoking packaged modules.
- Development guardrails are active. `.github/workflows/ci.yml` runs compile
  checks plus `run_safety_checks.py` on push/PR. `.pre-commit-config.yaml` runs
  Ruff on staged Python files and the same fast safety harness before commits.
- `ops_check.py config-audit` validates typed config factories, inventories raw
  env-var access, and flags unsafe runtime defaults. It is diagnostic-only and
  should be run after changing `/etc/trading-bot.env` or adding config flags.
- `ops_check.py architecture-surface` tracks root/module sprawl, oversized
  decision files, raw env access, `src/trading_bot` package skeleton readiness,
  and compatibility-deletion planning. It is diagnostic-only and should guide
  architecture cleanup work before moving files.
- `src/trading_bot/` is the future bounded-context package skeleton. Phase 2
  has started there with `src/trading_bot/web/app_factory.py` for Flask app
  construction/route registration and `src/trading_bot/runtime/startup.py` for
  startup-service wiring, plus `src/trading_bot/config/runtime.py` for
  app-specific runtime settings parsing, while root `app.py` remains the
  deployed compatibility context. Do not move additional runtime code into `src/trading_bot/` without
  compatibility wrappers, characterization tests, updated cron/systemd/docs, and
  passing safety checks.
- `ops/compatibility_deletion_plan.md` tracks wrapper/module replacement,
  callers, deletion conditions, and phase targets.
- `ops/project_audit_followup_2026-06-08.md` is the current repo-owned follow-up
  to the external project-audit/missing-tools documents. Treat stale external
  claims about empty tests or missing CI as superseded by the checked-in CI,
  pre-commit, safety tests, dependency split, and config audit.
- `ops_check.py trading-education-health` reports the curated
  `trading_education_corpus_v1` source/concept contract. Education content can
  support explanation, taxonomy, backtesting, and overfitting-governance work,
  but it has no live authority.
- `ops_check.py trading-education-ingest --max-pages 6 --no-follow` performs a
  bounded approved-source crawl and stores compact concept metadata only:
  source URL, retrieved timestamp, content hash, summary, concept keys, related
  feature names, and corpus version. It must remain education context only.
- New AI analytics command surfaces exist for operator/research review:
  `ai_dependency_status.py`, `score_financial_sentiment.py`,
  `timescale_smoke_test.py`, `train_supervised_predictions.py`,
  `train_regime_model.py`, and `risk_lockout.py`.
- The legacy `prediction_gate` fields in trades/snapshots are deterministic
  signal-quality gate fields. Actual ML prediction values must use
  `ml_prediction_*` names; weak buckets may reduce size only through explicit
  cap logic.
- The current operational focus is performance validation on clean-feed live
  paper sessions before further policy tuning.

Current roadmap posture:

```text
Validate setup health and SIP->IEX fallback on a clean session.
Verify conviction-stack persistence and cap attribution.
Tune one policy at a time from measured paper-session evidence.
```

## Safety Principles

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

## Prediction Layer Rule

The prediction layer must remain conservative until enough paper-session validation exists.

Do not convert these into hard live gates or size increases without explicit instruction:

prediction_score
probability_of_profit
expected_pnl
timing_score
recommended_entry_timing
trend_score
trend_label
trend_regime

## ML Platform Rule

The ML platform is allowed to be one step ahead of live behavior only in staged
or observe-only paths. Do not import staged ML integration into `app.py`
webhook, `broker.py`, order execution, or hard risk-control paths without
explicit instruction.

Current staged/audit commands:

python3 run_staged_tests.py
python3 -m ml_platform.cli staged-readiness --start-date 2026-05-26 --end-date 2026-05-26 --candidate-model similarity_v0 --prediction-symbol AAPL
python3 -m ml_platform.cli retraining-readiness --start-date 2026-05-26 --end-date 2026-05-26 --trading-sessions-observed 0
python3 export_ml_dataset.py --date 2026-05-26 --output /tmp/ml_dataset_2026-05-26.csv --manifest-output /tmp/ml_dataset_2026-05-26.manifest.json
python3 ai_dependency_status.py
python3 score_financial_sentiment.py --text "Example headline text"
python3 timescale_smoke_test.py --symbol AAPL --price 123.45 --volume 100
python3 train_supervised_predictions.py --limit 5000 --artifact-output ml/models/supervised_entry_v1/model.joblib
python3 train_regime_model.py --limit 1000 --artifact-output ml/models/regime_hmm_v1/model.joblib
python3 risk_lockout.py status

These commands are read-only with respect to `trades.db`, broker state, orders,
position sizing, and risk controls, except that the training commands may write
local model artifacts under `ml/models/` and the Timescale smoke test may write
a test row to `stock_ticks` when `TIMESCALE_DB_URI` is configured.
`similarity_v0` is metadata-only until an operator explicitly promotes a real
artifact through review.

`risk_lockout.py` and `services/persistent_lockout_service.py` can create and
inspect lockout/rebuilding state for operational safety. The live buy/order
paths are not wired to enforce that state unless future work explicitly adds
tests, logging, env flags, and rollback.

Dataset exports default to complete fixed-horizon label rows only. Incomplete,
unlabeled, and near-close partial rows are excluded from the CSV and counted in
the manifest; `--include-incomplete-labels` is for audit exports only. Realized
P&L is not a training target in the default export. Any future realized-exit
label export must carry `exit_policy_version` and `position_manager_version`
and must not mix exit-policy versions without explicit controls.

Correct roadmap path:

observe-only
→ validation report
→ warn-only
→ soft modifier
→ possible live gate later

## Typed Config Layer

The `config/` package provides frozen dataclasses and factory functions for all
env-var-driven configuration. The rule is:

  **One pattern only: module-level singleton via factory.**

Each consuming module creates its own singleton at module level:

    from config.signal import load_signal_config
    from config.risk import load_risk_config

    _signal_cfg = load_signal_config()
    _risk_cfg = load_risk_config()

Tests call the factory directly with overrides — they never touch module singletons:

    cfg = load_signal_config(prediction_gate_mode="block")

Do not mix these three patterns in the same codebase:

  - `from config import signal_cfg`  ← removed; was a shared package singleton
  - `load_signal_config()` inline    ← factory call, fine in tests/scripts
  - `os.getenv("PREDICTION_GATE_MODE", "warn")`  ← raw read; eliminate on contact

When adding a new env var:
  1. Add a typed field to the appropriate dataclass in `config/`.
  2. Add validation in `__post_init__` using `_check()`.
  3. Add the `env_*` read to the factory's `kwargs` dict.
  4. Remove the raw `os.getenv` call from the consuming module.

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

## Core Architecture

TradingView alert
  → Cloudflare Tunnel
  → Nginx
  → Gunicorn
  → Flask app.py composition root
  → SignalPipeline
  → LiveSignalProcessor
  → service-owned context / approval / sizing / execution / audit
  → Claude Haiku decision_engine.py
  → BrokerService / broker.py
  → Alpaca paper account
  → fill_stream.py / fill_poller.py
  → trades.db
  → reports / intelligence / validation

## Important Runtime Files

### app.py

Flask/Gunicorn composition root.

Key routes:

POST /webhook
GET  /health
GET  /status
GET  /positions
GET  /debug/symbol/<SYMBOL>

Responsibilities:

Create Flask app instances.
Select and attach the `ApplicationContainer`.
Register API routes.
Run explicit startup orchestration.
Expose `process_signal()` as a compatibility wrapper around `SignalPipeline`.
Avoid owning trading behavior, broker access, direct DB access, or report logic.

### services/live_signal_processor.py

Service-owned live signal orchestration.

Responsibilities:

Consume `SignalContext`, `SignalRuntimeState`, and context runtime objects.
Run deterministic pre-Claude and post-Claude gates through approval services.
Call sizing and execution services.
Preserve audit behavior and webhook status updates.
Keep app-level code out of trading decisions.

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

live_bar_stream.py

Optional Alpaca `alpaca-py` 1-minute closed-bar listener.

Responsibilities:

Subscribes to live 1-minute bars.
Gap-fills missing rolling context after startup/reconnect.
Updates session_momentum through SessionMomentumService.
Feeds bar_pattern_features for EFI/PVT, candle physics, order-flow proxy, fractional-memory, triple-barrier, and trend-scanning learning.

Runtime effect:

observe_only_bar_learning_no_direct_order_authority

This stream is an intelligence/learning input only. It must not submit orders or bypass LiveSignalProcessor authority paths.

pipeline/historical_bar_archive.py

Offline Polygon archive/backfill job for 1-minute regular-session bars.

Responsibilities:

Archives Polygon 1-minute RTH bars.
Caches CSVs under `data/historical_bars/polygon_1min`.
Feeds bars into `bar_pattern_features` unless `--no-patterns` is supplied.
Provides historical candle-physics, order-flow proxy, fractional-memory, triple-barrier, and trend-scanning labels for ML/replay research.

Usage:

python3 pipeline/historical_bar_archive.py --date 2026-06-03 --symbol AAPL
python3 pipeline/historical_bar_archive.py --date 2026-06-03 --all

ML advanced per-bar contract:

`bar_pattern_features` is part of the ML/export surface. Candle body/wick ratios,
close location, ATR-normalized range, pressure vectors, EFI/PVT pattern labels,
CVD/order-flow proxies, VPIN-style toxicity, fractional-differentiated price
memory, opportunity scores, `triple_barrier_label`, and `trend_scan_label` are
observe-only training/research inputs. ETF lead-lag vectors and options-skew
signals require additional feeds before they can be populated. Live promotion
still requires model-readiness, calibration, stability, and rollout-governance
checks.

`services/historical_bar_model_intelligence_service.py` summarizes the latest
historical-bar candidate diagnostics and injects compact readiness evidence into
canonical `analytics_state.historical_bar_model_intelligence`. It is
observe-only: it reads diagnostics only, never loads model binaries, and cannot
block, size, approve, or submit trades without explicit future authority wiring.

`services/historical_bar_paper_strategy_service.py` builds a paper-only master
confidence score from historical-bar candidate readiness, current bar-pattern
features, a naive baseline comparison, and portfolio correlation friction. It
also computes a paper sizing recommendation using a 2% risk budget and
volatility adjustment. The output is archived in canonical pattern/analytics
state and available through `python3 ops_check.py historical-bar-paper-strategy
SYMBOL --action buy`, but it is not consumed by live approval, live sizing, or
order submission.

Use `python3 ops_check.py advanced-alpha-readiness YYYY-MM-DD` to see which
advanced families are integrated, partially integrated, or blocked by missing
feeds/schema/outcomes.

Use `python3 ops_check.py advanced-alpha-comparison YYYY-MM-DD` to compare the
standard score-threshold profile against the asymmetric false-positive guard.
This is an offline diagnostic; it cannot block, approve, or size trades.

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

Runtime, services, reports, ops checks, and ML scripts should not open SQLite directly. Put DB reads/writes in repositories. Repository modules may use `db.get_connection()`, which applies row factory, WAL mode, busy timeout, and foreign keys.

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
## Prediction Layer

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

Current live behavior is downside-only: weak ML buckets can cap size when the
setup/sample conditions are met. Predictions cannot place orders, increase
size, loosen gates, or override broker/order safeguards.

## /status Intelligence

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
python3 ops_check.py local-load-probe --requests 100 --concurrency 4 --symbol AAPL --action buy
python3 ops_check.py paper-replay-load-probe --requests 100 --concurrency 4 --symbol AAPL --action buy
python3 ops_check.py incident-workflow --title "brief title" --severity medium --create
python3 ops_check.py feature-flags --limit 40
python3 ops_check.py model-governance --min-rows 5000 --min-symbols 20 --min-accuracy 0.50
python3 ops_check.py external-observability-readiness
python3 ops_check.py secrets-manager-readiness
python3 ops_check.py config-audit
python3 ops_check.py architecture-surface
python3 ops_check.py resource-readiness
python3 ops_check.py historical-bar-coverage START_DATE --end-date END_DATE
python3 ops_check.py historical-bar-progress START_DATE --end-date END_DATE
python3 ops_check.py historical-bar-readiness START_DATE --end-date END_DATE --include-db-quality
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

After the session, persist strong-session participation before validating
prediction quality:

```bash
python3 strong_day_participation_report.py --date "$TARGET_DATE" --write-db
python3 ops_check.py prediction-validation "$TARGET_DATE"
```
python3 ops/db_connection_audit.py
python3 db_migrations.py status

Current tracked migrations cover feature leakage/audit fields,
`rejected_signal_outcomes`, webhook-event lifecycle/status columns, and trade
decision-context columns that used to be added during app startup, plus the
append-only `decision_snapshots` audit table, `strong_day_participation`, and
`auto_buy_decision_snapshots`.

`label_v1_builder.py` is the formal fixed-horizon label v1 entrypoint. It
checks feature availability/staleness audit fields before delegating to
`label_features.py`; use `--check-only` for read-only validation.

Rejected-signal counterfactual outcomes can be populated and checked with:

```bash
python3 rejected_signal_outcome_builder.py --date YYYY-MM-DD
python3 ops_check.py rejected-outcomes YYYY-MM-DD
python3 ops_check.py decision-snapshots YYYY-MM-DD
python3 auto_buy_outcome_report.py --date YYYY-MM-DD
```

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

prediction_validation_report.py is read-only. It compares
`daily_symbol_predictions` against signal/trade outcomes and persisted
`strong_day_participation` rows after the strong-day report runs with
`--write-db`. It also reports deterministic signal-quality gate versus cached
ML prediction agreement from `decision_snapshots` once `ml_prediction_*`
compare fields exist.

Usage:

python3 prediction_validation_report.py
python3 prediction_validation_report.py 2026-05-26
python3 prediction_validation_report.py --date 2026-05-26
python3 ops_check.py prediction-validation 2026-05-26
python3 strong_day_participation_report.py --date 2026-05-26 --write-db

Before the session, expected state:

Predictions          : 41
Symbols with signals : 0
Symbols with trades  : 0
Symbols with matches : 0

After the session, it should help answer:

Did high prediction_score symbols outperform low-score symbols?
Did timing recommendations match actual outcomes?
Did trend labels identify risk?
Did predicted symbols participate in strong sessions or miss them?
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

Install local guardrails:

```bash
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/pre-commit install
./venv/bin/python run_safety_checks.py
```

CI runs the same fast safety harness from `.github/workflows/ci.yml` on pushes
to `main` and pull requests.

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

1. Patch the file.
2. Run targeted tests for the changed behavior.
3. Run `python3 -m py_compile` for changed entry points when applicable.
4. Run a script/report smoke test for new operator commands.
5. Run `./venv/bin/python run_safety_checks.py` for risk, authority,
   dependency, config, and architecture-sensitive changes.
6. If app/runtime behavior changed, restart `trading-bot` only after market-safe
   review.
7. Validate endpoint/report.
8. Commit.

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
local incident/postmortem workflow through `ops_check.py incident-workflow`
feature-flag inventory through `ops_check.py feature-flags`
consolidated model-governance diagnostic through `ops_check.py model-governance`
external observability readiness through `ops_check.py external-observability-readiness`
external secrets manager readiness through `ops_check.py secrets-manager-readiness`

Open before any cash-live promotion:

configure external observability/alerting endpoints
choose/configure external secrets manager provider
full-day paper replay with realistic market-data cadence
external incident escalation/review process
promotion-grade model validation against baseline/cost/slippage/exit/regime evidence
external change-approval history for cash-live feature-flag changes

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

Next app-level work should be composition cleanup only, not trading behavior migration.

7. Risk engine skeleton

Status: Later.

Future concepts:

risk_engine.py
RiskCheckResult
RiskDecision
layered risk checks
observe-only compare against current service-owned decisions
8. Soft risk modifier / live use of predictions

Status: Conservative downside-only modifiers are active; hard blocking is not.

Current active behavior:

weak ML bucket plus degraded setup can cap size.
confident weak ML bucket on non-boost setups can cap size.
high ML bucket remains advisory.
prediction gate hard blocking requires explicit promotion through `PREDICTION_GATE_MODE=hard`.

Do not add broader prediction authority until there are several clean paper sessions and validation reports support the change.

Known Watch Items

Prediction confidence is still very_low due to limited clean historical samples.
Some outcome data was reconstructed and should not be over-weighted.
Early market closes are not currently modeled in the shared calendar.
Event collection can surface low-quality or loosely relevant financial news.
Large share-price symbols can hit affordability limits.

Prediction hard blocking remains disabled until validated.

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
