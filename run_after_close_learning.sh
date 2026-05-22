#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot

set -a
source /etc/trading-bot.env
set +a

source /home/tradingbot/trading-bot/venv/bin/activate

echo "============================================================"
echo "After-close learning run started: $(date)"
echo "============================================================"

echo
echo "---- trade_matcher.py ----"
python3 trade_matcher.py

echo
echo "---- strategy_learner.py ----"
python3 strategy_learner.py

echo
echo "---- excursion_report.py ----"
python3 excursion_report.py --date "$(date +%F)" --limit 100 --write-memory

echo
echo "---- missed_opportunity_report.py ----"
python3 missed_opportunity_report.py --date "$(date +%F)" --limit 100 --write-memory

echo
echo "---- policy_backtest.py ----"
python3 policy_backtest.py --date "$(date +%F)" --write-summary

echo
echo "---- portfolio_replacement_report.py ----"
python3 portfolio_replacement_report.py --minutes 390 --top 20 --write-memory

echo
echo "---- strategy_brain_report.py ----"
python3 strategy_brain_report.py

echo
echo "After-close learning run finished: $(date)"
