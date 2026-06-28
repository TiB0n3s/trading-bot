#!/usr/bin/env bash
#
# run_analysis.sh — run trading-bot diagnostics/analysis through the WSL/Linux
# interpreter so SQLite WAL reads succeed concurrently with the live bot.
#
# Why this exists:
#   trades.db runs in WAL journal mode and is held open by the live bot inside
#   WSL/Linux. WAL coordinates concurrent access through the -shm shared-memory
#   file, which only works among processes on the same machine/filesystem.
#   Opening the DB from Windows Python over the \\wsl.localhost 9P share cannot
#   join that coordination, so every connection fails with "database is locked".
#   Running on the Linux side (this wrapper) joins the same -shm coordination and
#   WAL readers run concurrently with the bot — exactly what WAL is for.
#
# Usage (from Windows, e.g. Claude Code's Bash tool):
#   wsl -e bash /home/tradingbot/trading-bot/scripts/run_analysis.sh replay_report.py --date 2026-06-23
#   wsl -e bash /home/tradingbot/trading-bot/scripts/run_analysis.sh ops_check.py post 2026-06-27
#
# Usage (already inside WSL):
#   scripts/run_analysis.sh ops_check.py morning
#
set -euo pipefail

REPO_DIR="/home/tradingbot/trading-bot"
cd "$REPO_DIR"

# Prefer the project venv; fall back to system python3 if it is missing.
if [[ -x "$REPO_DIR/venv/bin/python" ]]; then
    PY="$REPO_DIR/venv/bin/python"
else
    PY="$(command -v python3)"
fi

# src/ layout: packaged modules import as trading_bot.*
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$REPO_DIR/src"

if [[ $# -eq 0 ]]; then
    echo "usage: run_analysis.sh <script.py|-m module> [args...]" >&2
    exit 2
fi

exec "$PY" "$@"
