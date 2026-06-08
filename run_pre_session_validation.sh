#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot
set -a
# shellcheck disable=SC1091
. /etc/trading-bot.env
set +a

TARGET_DATE=$(/home/tradingbot/trading-bot/venv/bin/python scripts/expected_market_context_date.py)
echo "=== Pre-session validation $(date -Iseconds) TARGET=$TARGET_DATE ==="

/home/tradingbot/trading-bot/venv/bin/python ops_check.py intelligence "$TARGET_DATE"
/home/tradingbot/trading-bot/venv/bin/python ops_check.py events "$TARGET_DATE"
/home/tradingbot/trading-bot/venv/bin/python ops_check.py predictions "$TARGET_DATE"
/home/tradingbot/trading-bot/venv/bin/python ops_check.py trends "$TARGET_DATE"
/home/tradingbot/trading-bot/venv/bin/python ops_check.py prediction-validation "$TARGET_DATE"
