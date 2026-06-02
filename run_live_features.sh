#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot
set -a
. /etc/trading-bot.env
set +a

/home/tradingbot/trading-bot/venv/bin/python live_features.py --all-symbols --write
