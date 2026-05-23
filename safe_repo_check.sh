#!/usr/bin/env bash
set -euo pipefail

cd /home/tradingbot/trading-bot

echo "---- branch ----"
git branch --show-current

echo
echo "---- tracked/untracked status ----"
git status --short

echo
echo "---- untracked source files that are not ignored ----"
git ls-files --others --exclude-standard | grep -E '\.py$|\.sh$|\.md$|\.json$' || true

echo
echo "---- source files present but not tracked ----"
find analytics_ext data_layer execution market_intelligence risk strategy tests \
  -type f \
  -name '*.py' \
  2>/dev/null \
  | sort \
  | while read f; do
      git ls-files --error-unmatch "$f" >/dev/null 2>&1 || echo "$f"
    done

echo
echo "---- source files accidentally ignored ----"
for f in $(find analytics_ext data_layer execution market_intelligence risk strategy tests -type f -name '*.py' 2>/dev/null | sort); do
  if git check-ignore -q "$f"; then
    echo "$f"
  fi
done

echo
echo "[OK] safe repo check complete"
