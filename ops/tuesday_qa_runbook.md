# Tuesday Paper Session QA Runbook

Target session: Tuesday 2026-05-26

Purpose: make the paper-trading session a meaningful QA run for the current
runtime, intelligence, feature collection, order flow, and after-close learning
without introducing new trading behavior immediately before the session.

## Ground Rules

- Do not refactor `app.py`, `broker.py`, state persistence, DB schema, or risk
  controls during the session.
- Do not enable prediction outputs as live trade modifiers.
- Treat prediction, feature, and strategy outputs as evidence to evaluate, not
  authority to change decisions intraday.
- Prefer read-only checks and notes unless there is a confirmed production
  blocker.
- Record exact timestamps for anything surprising.

## Automation

If you will be away during market hours, start the read-only QA runner from a
terminal or tmux session:

```bash
cd ~/trading-bot
python3 ops/tuesday_qa_runner.py --date 2026-05-26
```

The runner sleeps until each QA window, runs the checks in this runbook, and
writes a timestamped log under `ops/qa_logs/`. It does not edit cron, restart
services, place orders, or change trading behavior.

Useful variants:

```bash
python3 ops/tuesday_qa_runner.py --date 2026-05-26 --dry-run
python3 ops/tuesday_qa_runner.py --date 2026-05-26 --run-due-only
python3 ops/tuesday_qa_runner.py --date 2026-05-26 --no-sleep
```

## Before 8:00 AM CT

Run from the repo root:

```bash
cd ~/trading-bot
git status --short
python3 run_tests.py
python3 ops_check.py market-context-check
python3 ops_check.py intelligence-summary 2026-05-26
python3 ops_check.py dataset-health 2026-05-26
python3 ops_check.py feature-health 2026-05-26
```

Expected:

- Tests pass.
- `market_context.json` targets `2026-05-26`.
- Market context source is `market_brief_builder` and format is
  `rich_market_brief_v1`.
- `daily_symbol_context` has 41 rows for `2026-05-26`.
- `daily_symbol_predictions` has 41 rows for `2026-05-26`.
- `feature_snapshots` and `labeled_setups` may still be zero after the DB
  rebuild.

Stop and investigate before open if:

- Tests fail.
- Alpaca credentials are missing.
- `market_context.json` is missing or has the wrong date.
- approved symbol coverage is not 41.
- service checks fail in `ops_check.py premarket` for trading-bot, fill-stream,
  cloudflared, or nginx.

## After 8:00 AM CT

The deterministic premarket cron should run at 8:00 AM CT.

```bash
python3 ops_check.py market-context-check
python3 ops_check.py intelligence-summary 2026-05-26
```

Expected:

- Fresh `market_context.json` still targets `2026-05-26`.
- Source/format remain deterministic/rich schema.
- Bias counts and avoid rows are plausible.

## After 8:05 AM CT

The event collection cron should run at 8:05 AM CT.

```bash
python3 ops_check.py intelligence-summary 2026-05-26
python3 ops_check.py dataset-health 2026-05-26
```

Expected:

- `daily_symbol_events` is populated for `2026-05-26`.
- `daily_symbol_predictions` remains present for 41 symbols.
- Prediction confidence can be low/very_low; that is not a failure while the
  layer is observe-only.

## Market Open: 9:30 AM ET / 8:30 AM CT

Watch the first 15-30 minutes without making behavioral changes.

```bash
python3 ops_check.py premarket
python3 ops_check.py feature-watch 2026-05-26
python3 ops_check.py rejection-summary 2026-05-26
python3 ops_check.py order-health 2026-05-26
```

Expected early-session behavior:

- `feature_snapshots` should become nonzero after the first live_features cron
  runs.
- Missing feature symbols should decrease toward zero as all-symbol collection
  succeeds.
- `labeled_setups` may still be zero because labels require snapshots to be at
  least 35 minutes old.
- Rejections may be dominated by market-hours early, then shift to real gates
  after open.
- Approved orders, if any, should have order IDs and sensible order statuses.

Investigate if:

- `feature_snapshots` stays zero after 10-15 minutes of open-market cron time.
- Many symbols are missing from feature collection.
- `feature-watch` shows an `eligible_35m_plus` backlog that keeps growing.
- Approved rows appear without `order_id`.
- Fill events diverge from order statuses.

## 10:15-10:30 AM CT

This is the first useful label-health window because early snapshots should be
old enough to label.

```bash
python3 ops_check.py feature-watch 2026-05-26
python3 ops_check.py dataset-health 2026-05-26
python3 ops_check.py rejection-summary 2026-05-26
python3 ops_check.py order-health 2026-05-26
```

Expected:

- `labeled_setups` should start increasing.
- `eligible_35m_plus` should not grow without labels being created.
- Rejection categories should be explainable.
- Order health should remain clean.

## Midday Check

```bash
python3 ops_check.py feature-watch 2026-05-26
python3 ops_check.py rejection-summary 2026-05-26
python3 ops_check.py order-health 2026-05-26
python3 ops_check.py positions
```

Questions to answer:

- Are feature rows accumulating steadily?
- Are labels keeping up?
- Which symbols are missing or noisy?
- Which gates are blocking the most trades?
- Did any approved signal fail to become a paper order?
- Are open positions and broker state coherent?

## Near Close

```bash
python3 ops_check.py positions
python3 ops_check.py order-health 2026-05-26
python3 ops_check.py rejection-summary 2026-05-26
python3 ops_check.py feature-watch 2026-05-26
```

Watch for:

- late-session order failures,
- position-manager exits,
- bracket/fill reconciliation issues,
- unlabeled feature backlog that should be resolved after close.

## After Close

Allow scheduled after-close jobs to run, then check:

```bash
python3 ops_check.py dataset-health 2026-05-26
python3 ops_check.py feature-watch 2026-05-26
python3 ops_check.py rejection-summary 2026-05-26
python3 ops_check.py order-health 2026-05-26
python3 ops_check.py post 2026-05-26
```

Expected:

- Feature snapshots and labels are nonzero.
- Matched trades may remain low if positions remain open; this is not
  necessarily a failure.
- Any approved rows without order IDs are understood.
- Rejection categories produce a clear improvement list.

## QA Scorecard

Fill this out after the session.

```text
Market context fresh and valid: yes/no
Event collection ran: yes/no
Predictions generated for 41 symbols: yes/no
Feature snapshots collected: yes/no, count=
All symbols covered by features: yes/no, missing=
Labels generated after 35m delay: yes/no, count=
Unlabeled eligible backlog at close: count=
Webhook signals received: count=
Approved paper orders: count=
Approved rows missing order_id: count=
Fill stream/fill poller reconciliation clean: yes/no
Position manager behavior understood: yes/no
Top rejection categories:
Unexpected failures:
Immediate fixes needed:
Post-Tuesday refactor candidates:
```

## Decision Rules After Tuesday

- If feature collection or labeling fails, fix data collection before model work.
- If order health fails, fix broker/order reconciliation before strategy work.
- If rejection categories are noisy or ambiguous, improve reporting before
  changing gates.
- If the session is stable, begin post-Tuesday structural refactor planning with
  the signal-processing extraction first.
- Keep predictions observe-only until enough feature, label, and matched-trade
  outcome data exists for validation.
