#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot

SOURCE_DIRS=(
  analytics_ext
  data_layer
  execution
  market_intelligence
  risk
  strategy
  tests
)

echo "========================================================================"
echo "  Safe Repo Check"
echo "========================================================================"

echo
echo "---- branch ----"
git branch --show-current

echo
echo "---- latest commits ----"
git log --oneline -5

echo
echo "---- tracked/untracked status ----"
git status --short

echo
echo "---- untracked non-ignored source-like files ----"
git ls-files --others --exclude-standard \
  | grep -E '\.(py|sh|md|json|yml|yaml|toml|ini)$' \
  || true

echo
echo "---- source files present but not tracked ----"
missing_tracked=0
for d in "${SOURCE_DIRS[@]}"; do
  [ -d "$d" ] || continue
  while IFS= read -r f; do
    if ! git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
      echo "$f"
      missing_tracked=1
    fi
  done < <(find "$d" -type f -name '*.py' ! -path '*/__pycache__/*' | sort)
done

echo
echo "---- source files accidentally ignored ----"
ignored_source=0
for d in "${SOURCE_DIRS[@]}"; do
  [ -d "$d" ] || continue
  while IFS= read -r f; do
    if git check-ignore -q "$f"; then
      echo "$f"
      ignored_source=1
    fi
  done < <(find "$d" -type f -name '*.py' ! -path '*/__pycache__/*' | sort)
done

echo
echo "---- tracked source files in protected dirs ----"
for d in "${SOURCE_DIRS[@]}"; do
  git ls-files "$d" 2>/dev/null || true
done | sort

echo
echo "---- ignored runtime/cache summary ----"
git status --ignored --short \
  | grep '^!!' \
  | grep -E '(__pycache__|\.pyc|\.log|\.db|\.db-shm|\.db-wal|venv/|session_logs|strategy_memory|market_context\.json)' \
  | sed -n '1,80p' \
  || true

echo
echo "========================================================================"
if [ "$missing_tracked" -eq 0 ] && [ "$ignored_source" -eq 0 ]; then
  echo "[OK] No untracked/ignored Python source files found in protected source dirs."
  exit 0
fi

echo "[WARN] Source files need review before cleanup/commit."
exit 1
