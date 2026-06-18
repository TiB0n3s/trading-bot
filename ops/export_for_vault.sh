#!/usr/bin/env bash
#
# export_for_vault.sh — write one trading day's bot_events ledger (slimmed) +
# run-log snapshots into the Obsidian vault's 01-raw/ as an immutable, dated
# source bundle. Runs locally inside WSL; the vault is reached over /mnt/d.
#
# Read-only w.r.t. trades.db (a SELECT through a read-only SQLite handle, WAL-
# safe). Uses only the Python stdlib — no venv, env file, or PYTHONPATH needed.
#
# The ledger keeps EVERY event and all structured decision columns
# (timestamp, symbol, event_type, action, decision, severity, reason, source).
# The bulky payload is slimmed to scalar candidate fields only — scores, flags,
# block reasons — which is what the vault's daily log (Blocker table, Top missed
# candidates) consumes. The heavy nested feature/trace dicts are dropped; full
# payloads remain in trades.db. This turns a ~550 MB/day dump into a few MB.
#
# Usage (inside WSL):
#   ops/export_for_vault.sh [YYYY-MM-DD]        # defaults to today (local date)
#   BOT_DIR=/path/to/bot ops/export_for_vault.sh 2026-06-17

set -euo pipefail

# --- paths (override via env if needed) ----------------------------------
BOT_DIR="${BOT_DIR:-/home/tradingbot/trading-bot}"            # operational prod checkout (migrated)
VAULT_RAW="${VAULT_RAW:-/mnt/d/AI Brain/Trading Project/01-raw}"
DB="${DB:-$BOT_DIR/trades.db}"

# --- target date, strictly -----------------------------------------------
REQ="${1:-}"
if [[ "$REQ" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then DATE="$REQ"; else DATE="$(date +%F)"; fi

# --- preflight ------------------------------------------------------------
[[ -d "$BOT_DIR" ]]   || { echo "ERROR: bot dir not found: $BOT_DIR (set BOT_DIR=...)" >&2; exit 1; }
[[ -f "$DB" ]]        || { echo "ERROR: trades.db not found: $DB" >&2; exit 1; }
[[ -d "$VAULT_RAW" ]] || { echo "ERROR: vault 01-raw not found: $VAULT_RAW (is the D: drive mounted?)" >&2; exit 1; }
DEST="$VAULT_RAW/bot-export-$DATE"
[[ -e "$DEST" ]] && { echo "ERROR: $DEST already exists — sources are immutable; refusing to overwrite." >&2; exit 1; }

# --- stage on fast ext4, publish to the vault only on success ------------
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/stage"; mkdir -p "$STAGE"

# 1. slimmed ledger for the day (read-only; WAL-safe; stdlib only)
python3 - "$DB" "$DATE" "$STAGE/bot_events_${DATE}.json" "$STAGE/manifest.json" "$BOT_DIR" <<'PY'
import json, sqlite3, sys, socket, subprocess
from datetime import datetime, timezone

db, date, out_path, manifest_path, bot_dir = sys.argv[1:6]

con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
cols = ["id", "timestamp", "event_type", "symbol", "action",
        "decision", "severity", "reason", "source"]
rows = con.execute(
    f"select {','.join(cols)}, payload_json from bot_events "
    "where date(timestamp)=? order by id",
    (date,),
).fetchall()

def slim_payload(raw):
    """Keep scalar candidate fields (scores, flags, block reasons);
    drop the heavy nested feature/trace dicts."""
    try:
        p = json.loads(raw) if raw else {}
    except Exception:
        return None
    if not isinstance(p, dict):
        return None
    out = {}
    cand = p.get("candidate")
    if isinstance(cand, dict):
        out["candidate"] = {k: v for k, v in cand.items()
                            if v is not None and not isinstance(v, dict)}
    if p.get("order") is not None:
        out["order"] = p["order"]
    return out or None

events = []
for r in rows:
    e = {c: r[c] for c in cols}
    sp = slim_payload(r["payload_json"])
    if sp is not None:
        e["payload"] = sp
    events.append(e)

with open(out_path, "w") as f:
    json.dump(events, f, indent=2, sort_keys=True)

def git_commit():
    try:
        return subprocess.check_output(
            ["git", "-C", bot_dir, "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return None

manifest = {
    "date": date,
    "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "hostname": socket.gethostname(),
    "git_commit": git_commit(),
    "events_for_date": len(events),
    "payload_handling": "slimmed: scalar candidate fields only; nested feature/trace dicts dropped (full payloads remain in trades.db)",
    "source": "ops/export_for_vault.sh",
}
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)

print(f"events_for_date={len(events)}")
PY

# 2. run-log snapshots (copied as-is; skip missing or empty)
for logname in daily_summary after_close_learning post_session_review; do
  src="$BOT_DIR/${logname}.log"
  if [[ -s "$src" ]]; then cp "$src" "$STAGE/${logname}_${DATE}.log"; fi
done

# 3. publish into the vault (deterministic; no nested directory)
mkdir -p "$DEST"
cp "$STAGE"/* "$DEST"/
echo "Wrote $DEST"
ls -lah "$DEST"
