#!/usr/bin/env bash
#
# export_for_vault.sh — one-way, read-only export of a single trading day's
# bot_events ledger + run-log snapshots, streamed as a gzip tar to stdout.
#
# Intended to be PINNED as an SSH forced-command so the vault host can pull a
# day's record without ever getting an interactive shell on this VM. Add to
# /home/tradingbot/.ssh/authorized_keys (one line):
#
#   command="/home/tradingbot/trading-bot/ops/export_for_vault.sh",no-port-forwarding,no-agent-forwarding,no-x11-forwarding,no-pty ssh-ed25519 AAAA... vault-pull
#
# The client passes the target date as the ssh command string; with a forced
# command that arrives here as $SSH_ORIGINAL_COMMAND. Anything that is not a
# strict YYYY-MM-DD is ignored and we default to today (server local date).
#
# Read-only by construction: the ledger comes from `bot_events.py --json`,
# which is a SELECT through the service layer. SQLite WAL mode allows concurrent
# readers alongside the single writer, so this never raw-copies or locks
# trades.db. Contains no secrets; env is sourced from /etc/trading-bot.env per
# repo convention.

set -euo pipefail

BOT_DIR="/home/tradingbot/trading-bot"
LIMIT=200000   # must exceed any single day's event count; truncation is flagged in manifest

# --- resolve target date, strictly ---------------------------------------
REQ="${SSH_ORIGINAL_COMMAND:-}"
if [[ "$REQ" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  DATE="$REQ"
else
  DATE="$(date +%F)"
fi

cd "$BOT_DIR"

# --- environment (mirrors run_after_close_learning.sh) -------------------
set -a
# shellcheck disable=SC1091
source /etc/trading-bot.env
set +a
export PYTHONPATH="$BOT_DIR:$BOT_DIR/scripts:$BOT_DIR/src${PYTHONPATH:+:${PYTHONPATH}}"
# shellcheck disable=SC1091
source "$BOT_DIR/venv/bin/activate"

<<<<<<< Updated upstream
# --- staging --------------------------------------------------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/bot-export-$DATE"
mkdir -p "$STAGE"

# --- 1. raw ledger for the day (read-only SELECT; WAL-safe) --------------
# Query is a lower-bound (--since), so we post-filter to the exact date and
# record counts + a truncation flag in the manifest. Goes to stdout-of-python
# captured to a file; nothing here writes to the tar stream yet.
RAW="$WORK/raw.json"
python3 scripts/bot_events.py --since "$DATE" --json --limit "$LIMIT" > "$RAW"

python3 - "$RAW" "$DATE" "$LIMIT" "$STAGE/bot_events_${DATE}.json" "$STAGE/manifest.json" <<'PY'
import json, sys, socket, subprocess
=======
# 1. slimmed ledger for the day (read-only; WAL-safe; stdlib only)
python3 - "$DB" "$DATE" "$STAGE/bot_events_${DATE}.json" "$STAGE/manifest.json" "$BOT_DIR" <<'PY'
import json, sqlite3, sys, socket, subprocess
from collections import Counter
>>>>>>> Stashed changes
from datetime import datetime, timezone

raw_path, date, limit, out_path, manifest_path = sys.argv[1:6]
limit = int(limit)

rows = json.load(open(raw_path))
raw_count = len(rows)
# timestamps are "YYYY-MM-DD HH:MM:SS"; key off the same column we keep.
same_day = [r for r in rows if str(r.get("timestamp", ""))[:10] == date]

with open(out_path, "w") as f:
    json.dump(same_day, f, indent=2, sort_keys=True)

def git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return None

manifest = {
    "date": date,
    "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "hostname": socket.gethostname(),
    "git_commit": git_commit(),
<<<<<<< Updated upstream
    "event_query_limit": limit,
    "events_returned_by_query": raw_count,
    "events_for_date": len(same_day),
    "possibly_truncated": raw_count >= limit,
=======
    "events_for_date": len(events),
    "event_counts_by_type": dict(
        sorted(Counter(e["event_type"] for e in events).items(), key=lambda kv: -kv[1])
    ),
    "payload_handling": "slimmed: scalar candidate fields only; nested feature/trace dicts dropped (full payloads remain in trades.db)",
    "run_logs": ("attached for this date"
                 if datetime.now().strftime("%Y-%m-%d") == date
                 else "omitted — rolling logs reflect only the latest run; export on the target date to capture its digest"),
>>>>>>> Stashed changes
    "source": "ops/export_for_vault.sh",
}
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)

if manifest["possibly_truncated"]:
    print(f"WARNING: query hit limit {limit}; ledger may be truncated", file=sys.stderr)
PY

<<<<<<< Updated upstream
# --- 2. run-log snapshots (genuine stdout records; copied as-is) ---------
for logname in after_close_learning post_session_review; do
  src="$BOT_DIR/${logname}.log"
  if [[ -f "$src" ]]; then
    cp "$src" "$STAGE/${logname}_${DATE}.log"
  fi
done
=======
# 2. run-log snapshots — these are ROLLING files (latest run only), so they only
#    correspond to the date they were produced (today). Attach only when exporting
#    today; for a historical date they'd mislabel the wrong day's digest.
TODAY="$(date +%F)"
if [[ "$DATE" == "$TODAY" ]]; then
  for logname in daily_summary after_close_learning post_session_review; do
    src="$BOT_DIR/${logname}.log"
    if [[ -s "$src" ]]; then cp "$src" "$STAGE/${logname}_${DATE}.log"; fi
  done
fi
>>>>>>> Stashed changes

# --- 3. stream the bundle to stdout (pure tar; warnings went to stderr) --
tar -C "$WORK" -czf - "bot-export-$DATE"
