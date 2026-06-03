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
"${PYTHON}" ops_check.py decision-lifecycle-dashboard "${TODAY}"
"${PYTHON}" ops_check.py lifecycle-analysis "${TODAY}"
"${PYTHON}" ops_check.py calibration-buckets "${TODAY}"
"${PYTHON}" ops_check.py post-trade-learning "${TODAY}"
"${PYTHON}" strong_day_participation_report.py --date "${TODAY}" --write-db
"${PYTHON}" tradingview_alert_coverage_report.py --date "${TODAY}"
"${PYTHON}" build_historical_trend_context.py --date "${TODAY}"
"${PYTHON}" predict_symbol_outcomes.py --date "${TODAY}"
"${PYTHON}" ops_check.py prediction-validation "${TODAY}"
nice -n 19 "${PYTHON}" pipeline/retrain.py --date "${TODAY}" --sessions 5 --bad-session-limit 3 || echo "WARN: automated retraining trigger did not complete; review pipeline/retrain.py output"
"${PYTHON}" ops_check.py auto-buy "${TODAY}"
"${PYTHON}" auto_buy_outcome_report.py --date "${TODAY}"
"${PYTHON}" entry_quality_report.py --date "${TODAY}"
"${PYTHON}" ops_check.py decision-snapshots "${TODAY}"
"${PYTHON}" ops_check.py policy-artifacts
"${PYTHON}" analytics_report.py --date "${TODAY}"
"${PYTHON}" filter_report.py --date "${TODAY}"
