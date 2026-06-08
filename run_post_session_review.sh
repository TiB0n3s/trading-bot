#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot

set -a
. /etc/trading-bot.env
set +a
export PYTHONPATH="/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot${PYTHONPATH:+:${PYTHONPATH}}"

TODAY="${1:-$(date +%F)}"
PYTHON="/home/tradingbot/trading-bot/venv/bin/python"

echo "=== Post-session review $(date -Iseconds) DATE=${TODAY} ==="
"${PYTHON}" pipeline/post_session_review.py --date "${TODAY}"
