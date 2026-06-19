#!/usr/bin/env bash
# Observe-only model-evidence PAYLOAD EXPORT wrapper (the heavy half).
#
# Materializes the ~2-year model-promotion evidence diagnostics into the cached
# columnar export that run_model_evidence_review.sh reads. Split out from the
# review so it runs in its own generous dark-hours slot: the old in-review build
# was I/O-starved under --ionice-idle and SIGTERM'd before writing anything.
#
# Schedule it BEFORE the 03:50 review slot, on a large timeout, and do NOT pass
# --ionice-idle (idle I/O scheduling under contention is what starved it). It is
# read-only with respect to trades.db/broker/orders and writes only the cache.
#
# Example crontab line (NOT installed automatically). Runs 02:00 Tue-Sat,
# nice'd, 90-minute timeout:
#
# 0 2 * * 2-6 cd /home/tradingbot/trading-bot && PYTHONPATH=/home/tradingbot/trading-bot:/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot/src /home/tradingbot/trading-bot/venv/bin/python scripts/job_runner.py --job-name model_evidence_payload_export --lock-file /tmp/tradingbot_model_evidence_payload_export.lock --log-file /home/tradingbot/trading-bot/model_evidence_payload_export.log --timeout-seconds 5400 --nice 10 -- bash /home/tradingbot/trading-bot/run_model_evidence_payload_export.sh
set -euo pipefail

cd /home/tradingbot/trading-bot

set -a
source /etc/trading-bot.env
set +a
export PYTHONPATH="/home/tradingbot/trading-bot:/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot/src${PYTHONPATH:+:${PYTHONPATH}}"

source /home/tradingbot/trading-bot/venv/bin/activate

echo "============================================================"
echo "Model evidence payload export started: $(date)"
echo "============================================================"

python3 pipeline/model_evidence_payload_export.py --date "$(date +%F)"

echo
echo "Model evidence payload export finished: $(date)"
