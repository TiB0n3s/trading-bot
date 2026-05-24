# Tuesday Debrief Template

Session date: 2026-05-26

Use this after the paper session to decide what worked, what failed, and what to
fix first.

## Commands

```bash
cd ~/trading-bot
python3 ops_check.py market-context-check
python3 ops_check.py intelligence-summary 2026-05-26
python3 ops_check.py dataset-health 2026-05-26
python3 ops_check.py feature-watch 2026-05-26
python3 ops_check.py rejection-summary 2026-05-26
python3 ops_check.py order-health 2026-05-26
python3 ops_check.py post 2026-05-26
```

Review the QA automation log:

```bash
ls -1t ops/qa_logs/tuesday_qa_2026-05-26_*.log | head
```

## Scorecard

```text
Market context fresh and valid: yes/no
Event collection ran: yes/no
Predictions generated for 41 symbols: yes/no
Feature snapshots collected: yes/no, count=
All symbols covered by features: yes/no, missing=
Labels generated after 35m delay: yes/no, count=
Unlabeled eligible backlog at close: count=
Webhook signals received: count=
Rejected signals: count=
Approved paper orders: count=
Approved rows missing order_id: count=
Fill stream/fill poller reconciliation clean: yes/no
Position manager behavior understood: yes/no
After-close learning ran: yes/no
Matched trades generated: yes/no, count=
```

## Top Findings

```text
1.
2.
3.
```

## Rejection Analysis

Top rejection categories:

```text
1.
2.
3.
```

Questions:

- Which rejections were expected risk controls?
- Which rejections look too conservative?
- Which rejections were ambiguous or poorly categorized?
- Did any blocked signal later look like a missed opportunity?

## Order / Broker Health

Questions:

- Did every approved row get an `order_id`?
- Were order statuses updated as expected?
- Did fill stream and fill poller agree?
- Were any broker failures caused by sizing, affordability, market state, or
  symbol constraints?

## Feature / Label Health

Questions:

- Did `feature_snapshots` cover all approved symbols?
- Did `labeled_setups` start after the 35-minute delay?
- Was there any persistent eligible unlabeled backlog?
- Which symbols failed or had sparse feature coverage?

## Intelligence / Prediction Review

Questions:

- Did deterministic market context match the live tape?
- Were event scores plausible?
- Were prediction confidences mostly low/very_low as expected?
- Did any high prediction score conflict with later labels or order outcomes?

## Decision Tree

- If feature collection failed: fix feature pipeline before model work.
- If labeling failed: fix `label_features.py`/Alpaca forward-bar access before
  model work.
- If approved rows missed order IDs: fix broker/order path before strategy work.
- If rejection categories are unclear: improve reporting before changing gates.
- If data collection and order health were stable: begin post-Tuesday
  signal-processing extraction behind tests.

## Immediate Fixes

```text
1.
2.
3.
```

## Post-Tuesday Refactor Candidates

```text
1.
2.
3.
```
