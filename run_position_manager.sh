#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot

set -a
source /etc/trading-bot.env
set +a

source /home/tradingbot/trading-bot/venv/bin/activate

python3 position_manager.py --live
