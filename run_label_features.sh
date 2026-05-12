#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot
set -a
. /etc/trading-bot.env
set +a

source venv/bin/activate

python3 label_features.py >> label_features.log 2>&1
