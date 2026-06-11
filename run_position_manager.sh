#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot

set -a
source /etc/trading-bot.env
set +a
export PYTHONPATH="/home/tradingbot/trading-bot:/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot/src${PYTHONPATH:+:${PYTHONPATH}}"

source /home/tradingbot/trading-bot/venv/bin/activate

python3 scripts/position_manager.py --live
