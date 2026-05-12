#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot
set -a
. /etc/trading-bot.env
set +a

source venv/bin/activate

python3 live_features.py --all-symbols --write >> live_features.log 2>&1