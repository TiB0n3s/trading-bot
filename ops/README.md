# Operations Notes

This directory stores operational reference files for the trading bot.

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


## Trade Decision Summaries

Use these read-only reports during or after a session:

```bash
cd ~/trading-bot
python3 ops_check.py rejection-summary 2026-05-26
python3 ops_check.py rejected-outcomes 2026-05-26
python3 auto_buy_manager.py --scope all
python3 ops_check.py auto-buy 2026-05-26
python3 auto_buy_outcome_report.py --date 2026-05-26
python3 strong_day_participation_report.py --date 2026-05-26 --write-db
python3 ops_check.py prediction-validation 2026-05-26
python3 ops_check.py decision-snapshots 2026-05-26
python3 ops_check.py policy-artifacts
python3 ops_check.py retention
python3 ops_check.py order-health 2026-05-26
python3 prediction_cache.py preload --date 2026-05-26
```

`rejection-summary` groups rejected trade rows by reason/category, symbol, and
recent context. `rejected-outcomes` checks counterfactual forward-return
coverage for rejected signals after `rejected_signal_outcome_builder.py` runs.
`auto_buy_manager.py` scores Alpaca-bar-derived buy candidates across the full
approved universe so scored-but-not-taken opportunities are persisted for later
counterfactual review. Live paper buys require both `--live` and
`AUTO_BUY_LIVE_BUYS=true`, and are constrained by
`AUTO_BUY_MAX_ORDERS_PER_RUN`, `AUTO_BUY_MAX_DAILY_ORDERS`, and
`AUTO_BUY_COOLDOWN_MINUTES`. The cron remains Central-time localized, but
`auto_buy_manager.py` skips closed-market runs and the first
`AUTO_BUY_SESSION_BUFFER_MINUTES` of the regular session before writing
candidate rows. Before any live paper buy it also cross-checks shared app
cooldowns, recent-sell churn state, the app per-symbol daily buy count, and
correlation-cluster exposure.
`auto_buy_outcome_report.py` compares captured candidates against forward
feature-snapshot returns, score buckets, and the TradingView signal baseline.
`strong_day_participation_report.py --write-db` persists full-universe
strong-session participation rows so `prediction_validation_report.py` and
`intelligence_prediction_report.py` can compare predictions against symbols
that were strong even if they had no TradingView alert.
`auto_buy_manager.py` writes `auto_buy_decision_snapshots` for candidate
decisions, live block reasons, risk cross-checks, and submitted order metadata
so the internal buy path has its own audit trail beside the main webhook
decision snapshots.
`decision-snapshots` verifies immutable point-in-time audit coverage for new
approved/rejected decisions. `policy-artifacts` checks the runtime learning
artifact files, and `retention` prints the non-destructive hot/warm/cold table
classification.
`order-health` checks approved rows for order IDs/statuses, fill-event
distribution, and imported Alpaca order status summaries.
`prediction_cache.py preload` verifies that `daily_symbol_predictions` can be
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

`run_after_close_learning.sh` registers the completed artifact set and marks it
known-good after all learning steps finish. If the after-close job fails before
completion, it logs a critical `AFTER_CLOSE_LEARNING` bot event. Rollback
restores the known-good snapshot with temp-file replacement. Dataset manifests
include current artifact hashes, the registry hash, and the known-good artifact
set id.


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
python3 run_tests.py
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
python3 rejected_signal_outcome_builder.py --date YYYY-MM-DD
python3 ops_check.py rejected-outcomes YYYY-MM-DD
```

The post-session cron calls `run_post_session_review.sh`, and that wrapper plus
`post_session_check.py` run the builder before validation. `ops_check.py
rejected-outcomes` verifies rejected row coverage, complete/pending/partial/error
label counts, 5m/15m/30m/60m/EOD horizon population, action-adjusted MFE/MAE
signs, and near-close partial attribution. Near-close rows should be `partial`
with `partial_reason = near_close_no_60m_window`, not silently treated as
complete labels.

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


## Tuesday QA Runbook

Use the Tuesday QA runbook to turn the 2026-05-26 paper session into a structured
validation pass:

```bash
less ops/tuesday_qa_runbook.md
```

It defines premarket, open, mid-session, close, and after-close checks plus a
QA scorecard for deciding what to fix next.


## Tuesday QA Automation

Start the read-only QA runner if you will be away during market hours:

```bash
cd ~/trading-bot
python3 ops/tuesday_qa_runner.py --date 2026-05-26
```

It follows `ops/tuesday_qa_runbook.md` and writes logs under `ops/qa_logs/`.
Use `--dry-run` to preview the schedule without running checks.

## Post-Tuesday Planning

Use these docs after the paper session to decide what to improve next:

- `ops/tuesday_debrief_template.md`: debrief scorecard and decision tree.
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
