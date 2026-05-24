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

To restore intentionally after review:

crontab ops/crontab.tradingbot.current.txt

Do not restore blindly. Review paths, environment loading, market schedule,
and any newly added jobs first.
```


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
python3 ops_check.py order-health 2026-05-26
```

`rejection-summary` groups rejected trade rows by reason/category, symbol, and
recent context. `order-health` checks approved rows for order IDs/statuses,
fill-event distribution, and imported Alpaca order status summaries.


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
