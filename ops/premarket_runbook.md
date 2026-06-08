# Premarket Runbook

Use this before the next market session.

## 1. Confirm repo state

```bash
cd ~/trading-bot
git branch --show-current
git status --short
git log --oneline -8
Expected:

Correct branch.
Clean working tree.
Latest safety/refactor commits present.
2. Run compile checks
python3 -m py_compile \
  app.py \
  broker.py \
  db.py \
  decision_engine.py \
  ops_check.py \
  bot_events.py \
  rejection_categories.py \
  run_tests.py

Expected:

No output.
Exit code 0.
3. Run targeted tests
python3 run_tests.py

Expected:

env_file_loaded=True
all targeted tests pass

Note:

run_tests.py automatically re-execs under ./venv/bin/python when the project
venv is present, so this command can be run from a plain shell or an activated
venv.

3a. Check dataset health
python3 ops_check.py dataset-health 2026-05-26

Expected before Tuesday:

daily_symbol_context and daily_symbol_predictions have 41 rows for 2026-05-26.
daily_symbol_events is populated.
feature_snapshots, labeled_setups, and matched_trades may still be zero until
market-session collection and closed-trade matching have real data.

3b. Check feature pipeline health
python3 ops_check.py feature-health 2026-05-26

Expected after a DB rebuild:

feature_snapshots and labeled_setups may be zero, but schema should pass.
Rotated logs may show prior collection/labeling from before the rebuild. Logs
prove prior behavior, but they do not contain enough data to restore full rows.

Tuesday session watch:

python3 ops_check.py feature-watch 2026-05-26

After the first live_features cron run, feature_snapshots should be nonzero.
After snapshots are 35+ minutes old, labeled_setups should start increasing.
4. Run premarket ops check
python3 ops_check.py premarket

Expected during a real premarket window:

env_file_loaded=True
Alpaca reachable
services active
market context current for the intended market date
approved symbols present
position review completes
bot events query works

Acceptable outside market hours:

session momentum may show insufficient_data
position momentum may skip live actions because market is closed

Not acceptable before open:

missing Alpaca credentials
WEBHOOK_SECRET missing
stale or wrong market_context.json date
services inactive
approved symbols missing
/debug endpoint unavailable
5. Check bot events
python3 ops_check.py events

Expected:

command runs cleanly
recent event table displays
6. Check system services
systemctl status trading-bot --no-pager
systemctl status fill-stream --no-pager
systemctl status cloudflared --no-pager
systemctl status nginx --no-pager

Expected:

all required services active
7. Check live status endpoint
source /etc/trading-bot.env
curl -s "https://trading.tib0n3s.xyz/status?secret=$WEBHOOK_SECRET" | jq .

Expected:

valid JSON
paper trading still active
macro risk visible
positions visible
recent telemetry visible
8. Market context rule

Do not begin the session with stale or wrong-date market context.

If market_context.json is stale, regenerate or validate the intended market brief before market open.

9. Do not change before open

Avoid these changes late Monday or Tuesday morning unless fixing a confirmed production-blocking bug:

extracting process_signal
changing order execution
changing broker logic
changing DB schema
changing state persistence
changing live risk controls
enabling prediction as a live modifier
replacing pre_market_research.py
10. Safe Tuesday observation targets

During the session, watch:

rejected signal categories
market_hours blocks disappearing after open
second-look / price sanity rejections
affordability rejections
buy opportunity sizing behavior
portfolio rotation events
position manager events
fill stream activity
unexpected bot_events growth
