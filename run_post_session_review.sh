#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot

set -a
. /etc/trading-bot.env
set +a

TODAY="${1:-$(date +%F)}"
PYTHON="/home/tradingbot/trading-bot/venv/bin/python"

echo "=== Post-session review $(date -Iseconds) DATE=${TODAY} ==="
"${PYTHON}" ops_check.py post "${TODAY}"
"${PYTHON}" rejected_signal_outcome_builder.py --date "${TODAY}"
"${PYTHON}" ops_check.py rejected-outcomes "${TODAY}"
"${PYTHON}" strong_day_participation_report.py --date "${TODAY}" --write-db
"${PYTHON}" build_historical_trend_context.py --date "${TODAY}"
"${PYTHON}" predict_symbol_outcomes.py --date "${TODAY}"
"${PYTHON}" ops_check.py prediction-validation "${TODAY}"
"${PYTHON}" ops_check.py auto-buy "${TODAY}"
"${PYTHON}" auto_buy_outcome_report.py --date "${TODAY}"
"${PYTHON}" ops_check.py decision-snapshots "${TODAY}"
"${PYTHON}" ops_check.py policy-artifacts
"${PYTHON}" analytics_report.py --date "${TODAY}"
"${PYTHON}" filter_report.py --date "${TODAY}"
