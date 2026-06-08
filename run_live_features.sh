#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot
set -a
. /etc/trading-bot.env
set +a
export PYTHONPATH="/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot${PYTHONPATH:+:${PYTHONPATH}}"

/home/tradingbot/trading-bot/venv/bin/python scripts/live_features.py --all-symbols --write
