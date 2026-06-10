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
  --exclude='*.db' \
  --exclude='*.db-*' \
  --exclude='trades.db' \
  --exclude='trades.db-*' \
  --exclude='trades.db-shm' \
  --exclude='trades.db-wal' \
  --exclude='backups' \
  --exclude='data' \
  --exclude='data_archive' \
  --exclude='ml/datasets' \
  --exclude='ml/experiments' \
  --exclude='research_exports' \
  --exclude='runtime_state' \
  --exclude='session_logs' \
  --exclude='scripts/data_archive' \
  --exclude='scripts/runtime_state' \
  --exclude='strategy_memory_history' \
  --exclude='db_recovery_*' \
  --exclude='db_corrupt_archive_*' \
  -czf "$OUT" \
  .github \
  .gitignore \
  .pre-commit-config.yaml \
  Dockerfile \
  README.md \
  CLAUDE.md \
  pyproject.toml \
  requirements.txt \
  requirements-base.txt \
  requirements-dev.txt \
  requirements-research.txt \
  *.py \
  *.sh \
  analytics_ext \
  api \
  config \
  dashboards \
  data_layer \
  execution \
  legacy_architecture \
  market_intelligence \
  ml_platform \
  ops \
  pipeline \
  reports \
  repositories \
  risk \
  scripts \
  services \
  src \
  strategy \
  tests \
  2>/tmp/source_snapshot_errors.log

echo "[OK] Source snapshot written:"
echo "$OUT"

echo
echo "Snapshot contents preview:"
tar -tzf "$OUT" | sed -n '1,80p'
