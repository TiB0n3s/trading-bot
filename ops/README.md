# Operations Notes

This directory stores operational reference files for the trading bot.

## Strategy Authority Status

`auto_buy_strategy_status.md` records the current auto-buy research conclusion:
the OHLCV-derived auto-buy stack has no demonstrated deployable edge and must
remain in observe/research mode unless a future thesis clears the documented
discrimination, blocked-null, multiple-testing, leakage, net-cost, and
independent-day checks. The current research detector uses both blocked
permutation nulls for within-test dependence and a max-statistic permutation
null for feature-family selection. Additional observe-mode data should be
treated as passive research substrate, not as evidence that the existing
OHLCV-derived intelligence can bootstrap an edge.

## Historical Candle Research View

Use the historical market-view report to make sure candle-based research is not
operating from an artificially narrow sample:

```bash
cd ~/trading-bot
./venv/bin/python scripts/historical_market_view.py \
  --start-date 2026-06-01 \
  --end-date 2026-06-16 \
  --target trend_scan_return_pct \
  --json-output reports/historical_market_view_2026-06-01_2026-06-16.json \
  --flat-output reports/historical_bar_research_2026-06-01_2026-06-16.csv
```

The report audits coverage, regime/label breadth, baseline outcomes, and
corrected feature-lift results over existing `bar_pattern_features` rows. It is
read-only research infrastructure and cannot grant auto-buy authority.

For large historical replays, keep generated feature rows out of the hot
runtime database. The CSV repair job can target an isolated SQLite DB:

```bash
cd ~/trading-bot
./venv/bin/python pipeline/historical_bar_feature_repair.py \
  --start-date 2024-06-01 \
  --end-date 2026-06-15 \
  --all \
  --db-path research_exports/historical_bar_features_2024-06-01_2026-06-15.db
```

Then point `historical_market_view.py --db-path` at that research DB.

## Point-In-Time External Signal Features

Use the external signal feature table for non-candle research inputs that are
known at a specific decision time: event structure, macro/calendar state,
options-derived positioning, flow/positioning, filings, or other orthogonal
signals. These rows are research features only. They cannot approve trades or
override auto-buy risk gates.

Each JSONL row must include symbol, feature timestamp, availability timestamp,
source, feature family, feature name, and a numeric or text value. Use `*` or
omit `symbol` for market-wide context. `available_at` is the point-in-time
contract used by scans; do not backfill with revised values unless the revision
policy and true availability time are preserved. For scheduled future events
that were legitimately known before the event time, set
`revision_policy=scheduled_known_before_event` or
`calendar_known_before_event` so the leakage audit treats that timing as
intentional.

```bash
cd ~/trading-bot
./venv/bin/python scripts/external_signal_features.py \
  --db-path trades.db \
  ingest-jsonl \
  --input data/external_signal_features/YYYY-MM-DD.jsonl
```

After ingest, run the research scan over candidate/rejected outcomes:

```bash
cd ~/trading-bot
./venv/bin/python scripts/external_signal_features.py \
  --db-path trades.db \
  scan-candidates \
  --start-date 2026-06-01 \
  --end-date 2026-06-16 \
  --min-rows 100 \
  --permutations 200 \
  --json-output reports/external_signal_scan_2026-06-01_2026-06-16.json
```

The scan enriches rows using features available at the original decision
timestamp when the source loader provides it, then applies the existing
feature-lift detector with blocked market-date permutations and family-wise
max-statistic correction.

## Post-Earnings Drift Research

Use the post-earnings drift runner as the first slower-horizon external thesis.
It ingests point-in-time earnings events into `external_signal_features`, labels
forward returns over multi-session horizons from `bar_pattern_features`, runs
the corrected detector, and adds an expected-value review after friction. It is
research-only and cannot grant auto-buy authority.

Input JSONL rows should contain at least `symbol`, `earnings_ts`,
`available_at`, and `source`. Scalar fields such as `report_timing`,
`eps_surprise_pct`, `revenue_surprise_pct`, or `guidance_surprise` are expanded
into earnings features.

```bash
cd ~/trading-bot
./venv/bin/python scripts/post_earnings_drift_research.py \
  --db-path trades.db \
  ingest-jsonl \
  --input data/earnings_events/YYYY-MM-DD.jsonl
```

Then scan a multi-session horizon:

```bash
cd ~/trading-bot
./venv/bin/python scripts/post_earnings_drift_research.py \
  --db-path trades.db \
  scan \
  --start-date 2026-01-01 \
  --end-date 2026-06-16 \
  --horizon-sessions 5 \
  --min-rows 30 \
  --permutations 200 \
  --spread-pct 0.05 \
  --slippage-pct 0.03 \
  --account-equity 500 \
  --json-output reports/post_earnings_drift_5d_2026-01-01_2026-06-16.json
```

Treat a positive detector result as a research lead only. A candidate still
needs leakage review, independent validation, and a positive expected-value
result at the intended account size before any promotion discussion.

## Cron

`crontab.tradingbot.current.txt` is a version-controlled snapshot of the
production `tradingbot` user's current crontab.

It is not automatically installed by the repo.

To compare the live server schedule against the tracked copy:

```bash
cd ~/trading-bot
crontab -l > /tmp/live-crontab.txt
diff -u ops/crontab.tradingbot.current.txt /tmp/live-crontab.txt
```

To restore intentionally after review:

```bash
crontab ops/crontab.tradingbot.current.txt
```

Do not restore blindly. Review paths, environment loading, market schedule,
and any newly added jobs first.


## Read-Only Dataset Checks

Use the dataset-health command to inspect ML/research data readiness without
changing trading behavior:

```bash
cd ~/trading-bot
python3 ops_check.py dataset-health 2026-05-26
```

This summarizes intelligence rows, feature/label coverage, matched-trade
coverage, and prediction confidence for the target market date.


## Feature Pipeline Checks

Use the feature-health command after DB recovery or before a session to inspect
feature collection and labeling without writing to the database:

```bash
cd ~/trading-bot
python3 ops_check.py feature-health 2026-05-26
```

This checks script presence, feature/labeled table schema, current row counts,
unlabeled backlog, and recent live_features/label_features log evidence.


## Feature Session Watch

Use the feature-watch command during the trading session to confirm the rebuilt
DB is accumulating new intraday ML rows:

```bash
cd ~/trading-bot
python3 ops_check.py feature-watch 2026-05-26
```

Early in the session, `feature_snapshots` should become nonzero first. After
snapshots are at least 35 minutes old, `labeled_setups` should begin increasing.
An `eligible_35m_plus` backlog means label_features has snapshots old enough to
label but has not labeled them yet.

## CFTC COT Positioning Context

Weekly CFTC Commitments of Traders context is normalized into
`runtime_state/cot_positioning.json` and consumed by pre-market/intraday market
context refreshes as macro positioning evidence.

```bash
cd ~/trading-bot
./venv/bin/python scripts/cot_positioning_fetch.py
```

`pipeline/pre_market.py` runs this fetch/normalize step automatically before
building `market_context.json`. Manual normalization from a prepared JSON file
is still available for replay or vendor-failover cases:

```bash
cd ~/trading-bot
./venv/bin/python scripts/cot_positioning_update.py \
  --input data/cot/latest_financial_futures.json \
  --output runtime_state/cot_positioning.json
```

This context is delayed weekly macro evidence only. It can inform ML features,
meta-labeling, and size-down logic, but it cannot independently approve trades.
See `ops/cot_positioning_context.md` for the timing and no-lookahead contract.

## Prime Brokerage Flow Context

Prime-brokerage / hedge-fund flow context is normalized into
`runtime_state/prime_brokerage_flows.json` and consumed by pre-market/intraday
market context refreshes as external sector/symbol positioning evidence.

```bash
cd ~/trading-bot
./venv/bin/python scripts/prime_brokerage_flows_update.py \
  --input data/prime_brokerage/latest_flows.json \
  --output runtime_state/prime_brokerage_flows.json
```

This context can inform ML features, meta-labeling, crowded-short review, and
size-down logic. It cannot independently approve trades or override risk gates.
See `ops/prime_brokerage_flow_context.md` for the input and no-lookahead
contract.

## Dealer Gamma Context

Dealer gamma / options GEX context is normalized into
`runtime_state/dealer_gamma.json` and consumed by pre-market/intraday market
context refreshes as per-symbol volatility-regime and structural level evidence.

```bash
cd ~/trading-bot
./venv/bin/python scripts/dealer_gamma_update.py \
  --input data/dealer_gamma/latest_gamma.json \
  --output runtime_state/dealer_gamma.json
```

This context can inform ML features, strategy-family weighting, gamma-flip chop
warnings, dynamic stop-level evidence, and size-down logic. It cannot
independently approve trades or override risk gates. See
`ops/dealer_gamma_context.md` for the input and no-lookahead contract.

## Webull Morning Brief Context

Webull morning brief context is normalized into
`runtime_state/webull_morning_brief.json` and consumed by pre-market/intraday
market context refreshes as event, attention, futures, and technical-signal
evidence.

```bash
cd ~/trading-bot
./venv/bin/python scripts/webull_context_collect.py --date "$(date +%F)"
```

`pipeline/pre_market.py` runs this collector automatically before the context
build. The collector uses Webull OpenAPI screener rankings as a
morning-brief-compatible proxy because the SDK exposes ranked market data, not
the exact in-app Morning Brief panel. Manual normalization from captured app
payloads remains available:

```bash
cd ~/trading-bot
./venv/bin/python scripts/webull_morning_brief_update.py \
  --input data/webull/morning_brief_YYYY-MM-DD.json \
  --output runtime_state/webull_morning_brief.json
```

This context can inform ML features, event-risk review, symbol attention, and
size-down/caution logic. It cannot independently approve trades or override
risk gates.

## Webull Screener / News / Attention Context

Webull screener, news-summary, and attention evidence is normalized into
`runtime_state/webull_market_evidence.json` and consumed by pre-market/intraday
market context refreshes as non-authoritative symbol evidence.

```bash
cd ~/trading-bot
./venv/bin/python scripts/webull_context_collect.py --date "$(date +%F)"
```

The same automated collector writes `data/webull/market_evidence_YYYY-MM-DD.json`
and `runtime_state/webull_market_evidence.json`. Manual normalization remains
available for externally captured payloads:

```bash
cd ~/trading-bot
./venv/bin/python scripts/webull_market_evidence_update.py \
  --input data/webull/market_evidence_YYYY-MM-DD.json \
  --output runtime_state/webull_market_evidence.json
```

The normalized context is attached under `webull_market_context` and emits
`webull_market:*` performance-evidence tags. Auto-buy records those tags in
candidate snapshots so after-close learning can test whether Webull screener,
news, and attention features improve forward outcomes before any gate
relaxation or tightening is considered. It cannot independently approve trades,
override risk gates, or size positions.

## Configuration Audit

Use the config audit after changing `/etc/trading-bot.env`, adding new env
flags, or refactoring config factories:

```bash
cd ~/trading-bot
python3 ops_check.py config-audit
```

The report validates typed config factories, inventories raw env-var access,
and flags unsafe runtime defaults such as default webhook secrets,
query-string-secret compatibility, cash mode without live-trading enablement,
unbacked live ML authority, or Transformer authority without a model id.

This command is diagnostic-only. It does not mutate config and does not grant
trading authority.

## Development Safety And Audit Follow-Up

Local and CI guardrails are now part of the repo:

```bash
cd ~/trading-bot
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/pre-commit install
./venv/bin/python run_safety_checks.py
```

`.github/workflows/ci.yml` runs compile checks plus `run_safety_checks.py` on
pushes to `main` and pull requests. `.pre-commit-config.yaml` runs Ruff on
staged Python files and the same fast safety harness before commits.

`ops/project_audit_followup_2026-06-08.md` tracks the current status of the
external project-audit and missing-tools findings. As of that follow-up, CI,
pre-commit guardrails, core safety tests, config audit, and dependency split are
implemented. Verified SQLite backup manifests are also implemented through
`pipeline/database_backup.py` and `ops_check.py database-backups`. Lightweight
local observability is available through `ops_check.py observability-health`.
Local secrets hygiene is available through `ops_check.py secrets-hygiene`.
`ops_check.py operational-readiness YYYY-MM-DD` now aggregates the deployment
entrypoint, package import, config, secret-file permission, backup freshness,
runtime job-ledger, SQLite WAL, and cron/systemd reference checks into one
pre-market/post-deploy readiness gate. External observability/alerting and
external secrets-manager adoption remain optional scaling items rather than
current runtime dependencies.

## Observability

Use the local health rollup before adding heavier monitoring:

```bash
python3 ops_check.py observability-health
python3 ops_check.py runtime-health "$(date +%F)"
python3 ops_check.py database-backups
```

`observability-health` consolidates the job-run ledger, verified database backup
freshness, service watchdog warnings, and ML staleness-guard state. It is
diagnostic-only and does not post external alerts.

## Operational Readiness

Use the aggregate readiness gate before market open, after deployment, or after
large refactors:

```bash
python3 ops_check.py operational-readiness "$(date +%F)"
```

The report fails only on critical blockers: missing entrypoints, broken packaged
imports, config factory failures, unsafe local env-file permissions, missing or
stale verified DB backups, dirty runtime job ledger, missing `trades.db`, or
stale cron/systemd references. Large SQLite WAL files and missing local env
files are warnings unless they indicate an unsafe production configuration.

Useful remediation commands:

```bash
# Fix stale fill-stream systemd references after root-script cleanup.
sudo sed -i \
  's#/home/tradingbot/trading-bot/fill_stream.py#/home/tradingbot/trading-bot/scripts/fill_stream.py#' \
  /etc/systemd/system/fill-stream.service
sudo systemctl daemon-reload
sudo systemctl restart fill-stream

# Create a fresh verified DB backup manifest off-hours.
cd ~/trading-bot
./venv/bin/python pipeline/database_backup.py
./venv/bin/python ops_check.py database-backups
```

For non-strict diagnostics while a job ledger is still empty:

```bash
python3 ops_check.py operational-readiness "$(date +%F)" --no-require-job-ledger
```

## Secrets Hygiene

Use the local diagnostic before changing credentials or container/runtime
configuration:

```bash
python3 ops_check.py secrets-hygiene
```

The report checks `/etc/trading-bot.env` permissions, repo-local env-file
candidates, `.gitignore` coverage, and Dockerfile leakage risk. It never prints
secret values. A dedicated external secrets manager remains a future hardening
option rather than a current dependency.

## Database Backups

Use the Python backup path instead of shell-only `sqlite3 .backup` commands or
raw file copies:

```bash
python3 pipeline/database_backup.py --backup-tier father --retention-days 28
python3 ops_check.py database-backups
python3 ops_check.py database-restore-drill
```

The backup service uses SQLite's online backup API, stores verified copies under
`backups/databases/`, writes a manifest, and runs `PRAGMA integrity_check` on
each copied database. The default set is `trades.db` and `jobs.db`; prediction
history currently lives inside `trades.db`. Optional split database files can be
passed explicitly with `--db` if introduced later. The tracked cron file uses a
GFS policy: weekly Father backups after Friday close and a monthly Grandfather
backup on the first Saturday. Nightly VM snapshots currently provide the daily
Son recovery layer.

Do not raw-copy `trades.db`, `trades.db-wal`, or `trades.db-shm` while the
runtime is active. SQLite WAL files are tied to the main database and checkpoint
state; copying them alone is not a safe transaction-log archive for this
deployment.

`database-restore-drill` re-opens the latest verified backup manifest, restores
each verified database into `backups/databases/restore_drills/`, runs SQLite
integrity/table-count checks against the restored copy, and writes a drill
manifest. Run it off-hours for production-sized databases.

## Paper Session Evidence

Use the paper-session evidence report after or during a paper trading session to
check whether ML/intelligence authority has enough canonical evidence for review:

```bash
python3 ops_check.py paper-session-evidence "$(date +%F)"
```

The report summarizes decision snapshots, auto-buy bridge rows, candidate
forward-outcome coverage, rejected/realized outcomes, and whether canonical
decision-policy learning effects are present. It is diagnostic-only; blockers
mean the session should not be used for authority promotion yet.

## Live Quote Quality

Use live quote quality when market-data providers disagree or quote quality is
suspect:

```bash
python3 ops_check.py live-quote-quality AAPL
```

The check compares currently configured Alpaca, Polygon, and Webull quote
snapshots, counts usable providers, measures provider mid-price disagreement,
and reports spread/provider errors without granting trading authority.

For Webull RSI indicator parity, use:

```bash
WEBULL_RSI_EXPECTED=62.4 python3 ops_check.py webull-rsi-calibration AAPL
```

The command reads the latest persisted Webull-compatible Wilder RSI feature and
compares it to the optional app value within `WEBULL_RSI_TOLERANCE` points
(default `0.75`). It is diagnostic-only and grants no trading authority.

## Architecture Surface Cleanup

Use the architecture-surface report before and after structural refactors:

```bash
cd ~/trading-bot
python3 ops_check.py architecture-surface
```

The report measures root Python file count, direct `services/` module count,
`src/trading_bot/ops_checks/` module count, repository module count, oversized runtime
decision files, raw env access, `src/trading_bot` package skeleton readiness,
and whether `ops/compatibility_deletion_plan.md` exists.

It is diagnostic-only and is expected to warn until cleanup targets are met.
Use `ops/compatibility_deletion_plan.md` as the staged migration tracker. Do not
move runtime decision code without compatibility wrappers, characterization
tests, command smoke tests, and a market-safe deployment window.

## Polygon Historical Bar Backfill

Use Polygon history to build the multi-year 1-minute regular-session bar corpus
needed for serious ML training. The backfill is offline/observe-only: it writes
cached CSV chunks and persists derived `bar_pattern_features`; it does not alter
live trading authority.

First run a smoke chunk:

```bash
cd ~/trading-bot
set -a && . /etc/trading-bot.env && set +a
python3 pipeline/historical_bar_backfill.py \
  --start-date 2024-06-01 \
  --end-date 2026-06-04 \
  --symbol AAPL \
  --chunk-days 30 \
  --max-chunks 1 \
  --dry-run
```

Then run the full approved-universe backfill:

```bash
python3 pipeline/historical_bar_backfill.py \
  --start-date 2024-06-01 \
  --end-date 2026-06-04 \
  --all \
  --chunk-days 120 \
  --request-sleep-seconds 13 \
  --retry-attempts 3 \
  --retry-sleep-seconds 20
```

Verify coverage before making model-readiness claims:

```bash
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
```

If the coverage report is not ready, train only as a smoke test or
observe-only comparison. Do not promote model authority from short history.
The report also shows per-symbol balance metrics. A dataset with enough total
days can still be weak if only a few symbols have deep history.
Use `historical-bar-progress` while the backfill is running to see the latest
manifest, recent errors, and the next symbols that need more historical days.
It is cache/manifest based for speed; use `historical-bar-coverage` for
DB-derived training readiness.

Inspect or write the canonical ML training export:

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
  --output research_exports/ml_training_dataset_20240601_20260604.csv \
  --format csv \
  --max-rows 0
```

This export is point-in-time audited, manifest-backed, and has
`dataset_export_only_no_live_authority` runtime effect. The default
`--max-rows 5000` keeps checks responsive; `--max-rows 0` requests a full
export.

Data contract:

- Polygon backfill requests `adjusted=True` and filters to regular market hours.
- Cached CSV chunks include OHLCV, VWAP, source, adjusted flag, and inclusive interval-start metadata.
- Persisted `bar_pattern_features` rows include raw OHLCV/VWAP plus RSI/EMA/MACD, EMA200/MACD reversal setup fields, Webull-compatible Wilder RSI, candle-physics ratios, EFI/PVT, CVD/VPIN proxies, fractional-memory, triple-barrier, and trend-scan features.
- Intra-bar timestamps for the exact open/high/low/close event sequence are not available from Polygon aggregate bars. Those require tick-level data and should be treated as a future archive layer.

Tick-level entitlement probe:

```bash
python3 pipeline/polygon_tick_archive.py \
  --date 2026-06-04 \
  --symbol AAPL \
  --limit 50000 \
  --dry-run
```

Successful output means tick-level trades can be cached for future tick,
volume, and dollar-bar sampling. Entitlement or plan errors mean the current
Polygon subscription only supports aggregate-bar training.

## AI Analytics And Storage Checks

Use these checks after dependency installs, DB restore, or Timescale changes:

```bash
cd ~/trading-bot
set -a && . /etc/trading-bot.env && set +a
. venv/bin/activate

python3 ai_dependency_status.py
python3 risk_lockout.py status
python3 timescale_smoke_test.py --symbol AAPL --price 123.45 --volume 100
python3 score_financial_sentiment.py --text "Example headline text"
python3 score_financial_sentiment.py --text "Example headline text" --finbert
```

`TIMESCALE_DB_URI` controls optional TimescaleDB storage. When configured,
`services/live_features_service.py` mirrors compact feature ticks into the
`stock_ticks` hypertable through `services/timescale_tick_writer_service.py`.
Unset the env var to disable storage mirroring. Timescale writes are for
research and feature engineering only; they do not affect broker calls,
position sizing, approvals, or risk gates.

`ai_dependency_status.py` reports which heavy ML/NLP/storage packages are
available. `score_financial_sentiment.py --finbert` uses the transformer path
when available; without `--finbert`, the lexicon fallback keeps the command
usable in lighter environments. `risk_lockout.py status` inspects persistent
lockout/rebuilding state. Creating lockout state does not currently enforce a
live buy block unless a future runtime integration explicitly wires it in.


## Trade Decision Summaries

Use these read-only reports during or after a session:

```bash
cd ~/trading-bot
python3 ops_check.py rejection-summary 2026-05-26
python3 ops_check.py rejected-outcomes 2026-05-26
python3 scripts/auto_buy_manager.py --scope all
python3 ops_check.py auto-buy 2026-05-26
python3 auto_buy_outcome_report.py --date 2026-05-26
python3 strong_day_participation_report.py --date 2026-05-26 --write-db
python3 ops_check.py prediction-validation 2026-05-26
python3 ops_check.py decision-snapshots 2026-05-26
python3 ops_check.py policy-artifacts
python3 ops_check.py retention
python3 ops_check.py order-health 2026-05-26
python3 ops_check.py config-audit
python3 ops_check.py trading-education-health
python3 ops_check.py trading-education-ingest --max-pages 6 --no-follow
python3 scripts/prediction_cache.py preload --date 2026-05-26
```

`rejection-summary` groups rejected trade rows by reason/category, symbol, and
recent context. `rejected-outcomes` checks counterfactual forward-return
coverage for rejected signals after `scripts/rejected_signal_outcome_builder.py` runs.
`scripts/auto_buy_manager.py` scores Alpaca-bar-derived buy candidates across the full
approved universe so scored-but-not-taken opportunities are persisted for later
counterfactual review. Live paper buys require both `--live` and
`AUTO_BUY_LIVE_BUYS=true`, and are constrained by
`AUTO_BUY_MAX_ORDERS_PER_RUN`, `AUTO_BUY_MAX_ACTIVE_POSITIONS`,
`AUTO_BUY_MAX_DAILY_ORDERS`, and `AUTO_BUY_COOLDOWN_MINUTES`.
`AUTO_BUY_MAX_ACTIVE_POSITIONS` limits concurrent auto-buy exposure, while
`AUTO_BUY_MAX_DAILY_ORDERS` is a gross daily circuit cap so early exits can be
replaced while still limiting churn. The cron remains Central-time localized, but
`scripts/auto_buy_manager.py` skips closed-market runs and the first
`AUTO_BUY_SESSION_BUFFER_MINUTES` of the regular session before writing
candidate rows. Before any live paper buy it also cross-checks shared app
cooldowns, recent-sell churn state, the app per-symbol daily buy count, and
correlation-cluster exposure.
Current scoring favors earlier constructive build over mature momentum chase:
`early_constructive_build` is recorded when a symbol is near VWAP with improving
5m/15m/30m momentum and acceptable setup quality, while `mature_chase` and
`extreme_chase` are recorded when price is already extended from VWAP after a
large session move. Extreme chase states are blocked unless the setup is a
specific recovery/retest pattern rather than simple momentum chasing.
When TradingView alerts are unavailable or intentionally retired, set
`AUTO_BUY_SIGNAL_MODE=internal_all` or `TRADINGVIEW_ALERTS_DEPRECATED=true`.
That allows legacy TradingView-cohort symbols to execute through the internal
bar-derived candidate path while preserving `signal_source=tradingview_alert`
as historical/source metadata. Use
`python3 ops_check.py signal-source-readiness YYYY-MM-DD` to verify that strong
legacy-cohort candidates are not being blocked solely by webhook-source gating.
For paper-mode breadth across the approved universe, use:

```bash
AUTO_BUY_SIGNAL_MODE=internal_all
AUTO_BUY_LIVE_BUYS=true
AUTO_BUY_MAX_ORDERS_PER_RUN=3
AUTO_BUY_MAX_ACTIVE_POSITIONS=10
AUTO_BUY_MAX_DAILY_ORDERS=24
AUTO_BUY_COOLDOWN_MINUTES=20
AUTO_BUY_MAX_SIGNALS_PER_SYMBOL=2
DECISION_POLICY_AUTHORITY_MODE=paper_only
DECISION_POLICY_LIVE_BLOCK=true
DECISION_POLICY_LIVE_SIZE_DOWN=true
ML_AUTHORITY_MODE=paper_block
BUY_OPPORTUNITY_STRONG_CONVICTION_MAX_PCT=1.50
POSITION_MANAGER_STRONG_CONVICTION_MIN_PROFIT_PARTIAL_PCT=1.0
POSITION_MANAGER_STRONG_CONVICTION_GIVEBACK_TRIGGER_PCT=70
```

The installed cron entry now preserves the normal `/etc/trading-bot.env`
exposure caps. Use `AUTO_BUY_MAX_ACTIVE_POSITIONS_OVERRIDE` or
`AUTO_BUY_MAX_DAILY_ORDERS_OVERRIDE` only when intentionally applying a
temporary cap for a specific session.
Keep `TRANSFORMER_AUTHORITY_ENABLED=false` until a promoted transformer artifact
is registered with `TRANSFORMER_MODEL_ID`; once registered for paper authority,
use `TRANSFORMER_AUTHORITY_MODE=paper_gate` so it can block paper candidates
without bypassing hard risk gates.
`auto_buy_outcome_report.py` compares captured candidates against forward
feature-snapshot returns, score buckets, and the TradingView signal baseline.
`strong_day_participation_report.py --write-db` persists full-universe
strong-session participation rows so `prediction_validation_report.py` and
`intelligence_prediction_report.py` can compare predictions against symbols
that were strong even if they had no TradingView alert.
`scripts/auto_buy_manager.py` writes `auto_buy_decision_snapshots` for candidate
decisions, live block reasons, risk cross-checks, and submitted order metadata
so the internal buy path has its own audit trail beside the main webhook
decision snapshots.
`position_manager.py` treats partial exits as fail-safe around open-order state:
when a partial exit must cancel open orders first, it waits for the next cycle
before submitting; if Alpaca still reports insufficient available quantity, the
job records a non-submitted action instead of crashing.
`decision-snapshots` verifies immutable point-in-time audit coverage for new
approved/rejected decisions. `policy-artifacts` checks the runtime learning
artifact files, and `retention` prints the non-destructive hot/warm/cold table
classification.
`order-health` checks approved rows for order IDs/statuses, fill-event
distribution, and imported Alpaca order status summaries.
`trading-education-health` reports the versioned, non-authoritative education
source and concept corpus. It is for AI/ML explanation, taxonomy, and operator
review only; it cannot approve, block, size, or execute trades.
`trading-education-ingest` performs a bounded approved-domain crawl and stores
compact concept metadata in `trading_education_pages`; use small `--max-pages`
values and `--no-follow` for seed refreshes. Fetch failures are recorded rather
than treated as trading failures.
For sites that block VM fetches, operator-provided HTML/text snapshots can be
loaded through the same schema:

```bash
python3 ops_check.py trading-education-ingest \
  --manual-file /path/to/article.html \
  --url https://www.schwab.com/learn/story/what-are-derivatives \
  --title "What Are Derivatives? A Guide to Financial Contracts"
python3 ops_check.py trading-education-review
```

Manual snapshots are marked `manual_snapshot`; low-confidence or short
extractions are stored as `needs_review`.
`scripts/prediction_cache.py preload` verifies that `daily_symbol_predictions` can be
loaded into the TTL cache before the session. The Flask app also starts its own
background cache refresher so webhook handling reads predictions from memory,
not SQLite. `prediction_validation_report.py` reports deterministic-gate versus
cached-ML agreement once decision snapshots include `ml_prediction_*` compare
fields.

Decision policy authority is visible in `/status` under `decision_policy`.
Default authority is `paper_only`: `DECISION_POLICY_LIVE_BLOCK=true` and
`DECISION_POLICY_LIVE_SIZE_DOWN=true` can affect paper/dry-run BUY review, but
not cash modes unless `DECISION_POLICY_AUTHORITY_MODE=all_modes` is explicitly
set. The policy cannot increase size or submit orders. If
`ops_check.py policy-artifacts` shows `policy_backtest_recommendation=policy_too_loose`,
keep the layer under review and do not promote it.

## Policy Artifact Registry And Rollback

After-close learning artifacts influence live decision context, so they are
registered as `policy_artifact` sets:

```bash
cd ~/trading-bot
python3 policy_artifacts.py status
python3 policy_artifacts.py register --label manual_review --source operator --known-good
python3 policy_artifacts.py rollback --dry-run
python3 policy_artifacts.py rollback
```

`pipeline/after_close_learning.py` registers the completed artifact set and
marks it known-good after all learning steps finish. The pipeline also runs
`pipeline.learning_backfill_repair` before downstream learning reports. That
repair step repeatedly backfills candidate-universe forward outcomes in bounded
chunks until the configured coverage target is reached, then repairs approved
matched exits that are missing canonical exit snapshots. It is analysis-only and
cannot approve, size, or route orders.

`run_after_close_learning.sh` only loads environment, logs
start/failure/finish bot events, and delegates to the pipeline under the
cron/job-runner lock. Rollback restores the known-good snapshot with temp-file
replacement. Dataset manifests include current artifact hashes, the registry
hash, and the known-good artifact set id.


## Point-In-Time Context Archive

Archive the current market context, override hashes, policy artifact hashes,
and symbol-universe version whenever context changes before a session:

```bash
cd ~/trading-bot
python3 archive_context_state.py --reason premarket_context_refresh
```

The current cron snapshot runs this shortly after the premarket context refresh
and writes timestamped JSON under `data_archive/point_in_time/`.


## Maintainability Audits

Use the DB connection audit while refactoring database access. It is read-only
and flags manual connection assignments that should be reviewed for `close()` or
conversion to `with get_connection(...)` blocks:

```bash
cd ~/trading-bot
python3 ops/db_connection_audit.py
```

Broker boundary unit tests live in `tests/test_broker.py` and are included in
the normal targeted test runner:

```bash
python3 scripts/run_tests.py
```

The sell path cancels open bracket orders and polls Alpaca for cancellation
propagation before submitting a market sell. If repeated cancellation polling
fails, the sell fails closed instead of assuming a fixed sleep was enough.


## Schema Migrations

Use `db_migrations.py` for idempotent schema changes instead of manual
one-off `ALTER TABLE` statements:

```bash
cd ~/trading-bot
python3 db_migrations.py status
python3 db_migrations.py apply
```

Migration execution is intentionally manual before deployment, DB restore, or
schema-dependent ops work. `morning_check.py`, `ops_check.py premarket`, and
`ops_check.py all` surface pending migrations so a restored or fresh DB does not
silently run with an old schema.

The first tracked migration adds feature leakage/audit columns to
`feature_snapshots`: `feature_available_at`, `feature_generated_at`,
`feature_age_seconds`, `source`, `is_stale`, and `staleness_reason`.

The second tracked migration creates `rejected_signal_outcomes`, the canonical
target table for counterfactual labels on rejected signals. Populate it with:

```bash
python3 scripts/rejected_signal_outcome_builder.py --date YYYY-MM-DD
python3 ops_check.py rejected-outcomes YYYY-MM-DD
```

The post-session cron calls `run_post_session_review.sh`, which delegates to
`pipeline/post_session_review.py`. The pipeline runs the rejected-outcome builder
before validation and treats review/report warnings as warn-only instead of hard
cron failures. `ops_check.py rejected-outcomes` verifies rejected row coverage,
complete/pending/partial/error label counts, 5m/15m/30m/60m/EOD horizon
population, action-adjusted MFE/MAE signs, and near-close partial attribution.
Near-close rows should be `partial` with
`partial_reason = near_close_no_60m_window`, not silently treated as complete
labels.

If learning readiness reports candidate coverage or approved-exit linkage gaps,
the first recovery path is now:

```bash
cd ~/trading-bot
PYTHONPATH=.:scripts ./venv/bin/python -m pipeline.learning_backfill_repair --date YYYY-MM-DD
PYTHONPATH=.:scripts ./venv/bin/python ops_check.py learning-readiness YYYY-MM-DD
```

## Local Artifact Cleanup

`ops/clean_local_artifacts.sh` defaults to safe local cleanup only: Python
caches and local source backup/temp files. It intentionally excludes operational
logs, session logs, QA logs, and `*.db.bak*` database backups unless explicitly
requested.

```bash
ops/clean_local_artifacts.sh --dry-run
ops/clean_local_artifacts.sh --apply
ops/clean_local_artifacts.sh --dry-run --include-logs --include-db-backups
ops/clean_local_artifacts.sh --apply --include-logs --include-session-logs
```

The third tracked migration adds webhook-event lifecycle/status columns used by
the app to record queue, start, finish, order, and failure metadata.

The fourth tracked migration adds trade decision-context columns that used to
be added by app startup. Runtime startup should not own schema `ALTER TABLE`
work; run `python3 db_migrations.py apply` before deployment or restore.

The fifth tracked migration creates `decision_snapshots`, an append-only audit
table that records what the bot knew at each approved/rejected decision time.

Later tracked migrations add `rejected_signal_outcomes.partial_reason`,
`strong_day_participation`, and `auto_buy_decision_snapshots`.

`run_label_features.sh` runs `label_v1_builder.py`, which validates the
feature-snapshot leakage/audit fields before generating fixed-horizon v1
labels. For a read-only check:

```bash
python3 label_v1_builder.py --check-only
```


## Webhook Secrets

Operator endpoints and TradingView webhooks should pass the secret in a header:

```bash
curl -s -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  "https://trading.tib0n3s.xyz/status" | jq
```

`Authorization: Bearer $WEBHOOK_SECRET` is also accepted. Query-string
`?secret=...` is still accepted for backward compatibility, but should be
treated as legacy because reverse proxies and access logs often record URLs.


## Staged Validation

Use these docs and checks to decide what to improve next:

- `ops/module_inventory.md`: active vs scheduled vs research-only module map.
- `ops/ml_platform_roadmap.md`: staged ML/research-platform direction.

Ahead-of-live integration work should use the staged test lane. These tests
exercise observe-only contracts without changing live webhook, broker, order, or
risk-control behavior:

```bash
cd ~/trading-bot
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
```

`ml/models/similarity_v0/` is metadata-only. It is a versioned research
placeholder, not a trained artifact and not a runtime dependency.

The read-only ML dataset exporter can generate CSV evidence once
`feature_snapshots` and `labeled_setups` exist:

```bash
cd ~/trading-bot
python3 export_ml_dataset.py \
  --date 2026-05-26 \
  --output /tmp/ml_dataset_2026-05-26.csv \
  --manifest-output /tmp/ml_dataset_2026-05-26.manifest.json
```

The default export is the training-safe path: only complete fixed-horizon rows
are written to the CSV. Unlabeled rows and near-close partial horizons remain
visible in the manifest as exclusion counts. Use `--include-incomplete-labels`
for audit/reconciliation exports, not first-pass training. Realized-PnL labels
are intentionally excluded from this export surface until they can be versioned
by `exit_policy_version` and `position_manager_version`.
