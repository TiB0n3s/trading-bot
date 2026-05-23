#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot

OUT_DIR="/home/tradingbot/trading-bot-local-backups/source_snapshots"
mkdir -p "$OUT_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
BRANCH="$(git branch --show-current | tr '/' '-')"
OUT="$OUT_DIR/source_snapshot_${BRANCH}_${STAMP}.tar.gz"

tar \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.log' \
  --exclude='*.log.*' \
  --exclude='trades.db' \
  --exclude='trades.db-*' \
  --exclude='trades.db-shm' \
  --exclude='trades.db-wal' \
  --exclude='session_logs' \
  --exclude='strategy_memory_history' \
  --exclude='db_recovery_*' \
  --exclude='db_corrupt_archive_*' \
  -czf "$OUT" \
  .gitignore \
  README.md \
  CLAUDE.md \
  *.py \
  *.sh \
  analytics_ext \
  data_layer \
  execution \
  market_intelligence \
  risk \
  strategy \
  tests \
  2>/tmp/source_snapshot_errors.log

echo "[OK] Source snapshot written:"
echo "$OUT"

echo
echo "Snapshot contents preview:"
tar -tzf "$OUT" | sed -n '1,80p'
