#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot

set -a
source /etc/trading-bot.env
set +a

source /home/tradingbot/trading-bot/venv/bin/activate

on_failure() {
    local exit_code=$?
    python3 - <<PY2 || true
from bot_events import log_event
log_event(
    event_type="AFTER_CLOSE_LEARNING",
    action="failure",
    decision="failed",
    severity="critical",
    reason="after-close learning failed before completion; policy artifacts may be stale",
    source="run_after_close_learning.sh",
    context={"exit_code": ${exit_code}},
)
PY2
    echo "After-close learning failed with exit code ${exit_code}: $(date)" >&2
    exit "${exit_code}"
}

trap on_failure ERR

echo "============================================================"
echo "After-close learning run started: $(date)"
echo "============================================================"

python3 - <<'PY2'
from bot_events import log_event
log_event(
    event_type="AFTER_CLOSE_LEARNING",
    action="start",
    decision="running",
    severity="info",
    reason="after-close learning started",
    source="run_after_close_learning.sh",
)
PY2

echo
echo "---- trade_matcher.py ----"
python3 trade_matcher.py

echo
echo "---- strategy_learner.py ----"
python3 strategy_learner.py

echo
echo "---- excursion_report.py ----"
python3 excursion_report.py --date "$(date +%F)" --limit 100 --write-memory

echo
echo "---- missed_opportunity_report.py ----"
python3 missed_opportunity_report.py --date "$(date +%F)" --limit 100 --write-memory

echo
echo "---- symbol_momentum_timing_report.py ----"
python3 symbol_momentum_timing_report.py --date "$(date +%F)" --write-memory

echo
echo "---- policy_backtest.py ----"
python3 policy_backtest.py --date "$(date +%F)" --write-summary

echo
echo "---- portfolio_replacement_report.py ----"
python3 portfolio_replacement_report.py --minutes 390 --top 20 --write-memory

echo
echo "---- strategy_learner.py final memory refresh ----"
python3 strategy_learner.py

echo
echo "---- strategy_brain_report.py ----"
python3 strategy_brain_report.py

echo
echo "---- policy artifact hashes ----"
python3 policy_artifacts.py register \
    --label after_close_learning \
    --source run_after_close_learning.sh \
    --known-good

echo
echo "---- point-in-time context archive after policy artifact refresh ----"
python3 archive_context_state.py --reason after_close_learning_policy_artifacts


python3 - <<'PY2'
from bot_events import log_event
log_event(
    event_type="AFTER_CLOSE_LEARNING",
    action="finish",
    decision="completed",
    severity="info",
    reason="after-close learning finished",
    source="run_after_close_learning.sh",
)
PY2

echo
echo "After-close learning run finished: $(date)"
