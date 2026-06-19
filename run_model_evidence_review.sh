#!/usr/bin/env bash
# Observe-only model-evidence review wrapper (the fast LLM half). Warn-only: a
# no-graduation result is a valid outcome, not a failed job. It reads the cached
# payload materialized by run_model_evidence_payload_export.sh (the heavy half)
# rather than rebuilding diagnostics inline, so it finishes in its slot and
# always writes an artifact. Intended to run under the cron job_runner.py
# lock/ledger path in dark hours, AFTER the payload-export slot.
#
# Example crontab lines (NOT installed automatically — add them yourself after
# setting MODEL_EVIDENCE_REVIEW_ENABLED=true and ANTHROPIC_API_KEY in
# /etc/trading-bot.env). The payload export runs first at 02:00, then the
# review-only job at 03:50 Tue-Sat (just the LLM passes, so a 30-minute timeout
# is plenty; keep nice but NOT --ionice-idle for the heavy export):
#
# 0 2 * * 2-6 cd /home/tradingbot/trading-bot && PYTHONPATH=/home/tradingbot/trading-bot:/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot/src /home/tradingbot/trading-bot/venv/bin/python scripts/job_runner.py --job-name model_evidence_payload_export --lock-file /tmp/tradingbot_model_evidence_payload_export.lock --log-file /home/tradingbot/trading-bot/model_evidence_payload_export.log --timeout-seconds 5400 --nice 10 -- bash /home/tradingbot/trading-bot/run_model_evidence_payload_export.sh
# 50 3 * * 2-6 cd /home/tradingbot/trading-bot && PYTHONPATH=/home/tradingbot/trading-bot:/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot/src /home/tradingbot/trading-bot/venv/bin/python scripts/job_runner.py --job-name model_evidence_review --lock-file /tmp/tradingbot_model_evidence_review.lock --log-file /home/tradingbot/trading-bot/model_evidence_review.log --timeout-seconds 1800 --nice 10 -- bash /home/tradingbot/trading-bot/run_model_evidence_review.sh
set -euo pipefail

cd /home/tradingbot/trading-bot

set -a
source /etc/trading-bot.env
set +a
export PYTHONPATH="/home/tradingbot/trading-bot:/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot/src${PYTHONPATH:+:${PYTHONPATH}}"

source /home/tradingbot/trading-bot/venv/bin/activate

# Ensure the local Ollama red-team panelist is reachable (user-space, no systemd).
# Best-effort: if it can't start, that panelist is simply recorded as silent.
if [[ "${MODEL_EVIDENCE_PANEL:-}" == *ollama* ]] && [ -x "${HOME}/.local/bin/ollama" ]; then
    export PATH="${HOME}/.local/bin:${PATH}"
    if ! curl -s --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "starting ollama serve..."
        setsid ollama serve >> "${HOME}/ollama.log" 2>&1 &
        for _ in $(seq 1 20); do
            curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
            sleep 1
        done
    fi
fi

echo "============================================================"
echo "Model evidence review started: $(date)"
echo "============================================================"

# The python entrypoint is warn-only and exits 0 even when nothing graduates.
python3 pipeline/model_evidence_review.py --date "$(date +%F)"

echo
echo "Model evidence review finished: $(date)"
