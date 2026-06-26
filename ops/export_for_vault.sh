#!/usr/bin/env bash
#
# export_for_vault.sh - export one trading day's bot_events ledger plus run-log
# snapshots. By default it writes an immutable dated bundle into the Obsidian
# vault. When invoked as an SSH forced command, or with
# EXPORT_FOR_VAULT_MODE=tar, it streams the bundle as a gzip tar to stdout.
#
# The ledger is read-only with respect to trades.db and uses a WAL-safe SQLite
# read-only handle. Payloads are slimmed to scalar candidate/order fields; full
# payloads remain in trades.db.
#
# Usage:
#   ops/export_for_vault.sh [YYYY-MM-DD]
#   EXPORT_FOR_VAULT_MODE=tar ops/export_for_vault.sh 2026-06-17 > export.tgz
#
# Forced-command authorized_keys example:
#   command="/home/tradingbot/trading-bot/ops/export_for_vault.sh",no-port-forwarding,no-agent-forwarding,no-x11-forwarding,no-pty ssh-ed25519 AAAA... vault-pull

set -euo pipefail

BOT_DIR="${BOT_DIR:-/home/tradingbot/trading-bot}"
VAULT_RAW="${VAULT_RAW:-/mnt/c/AI Brain/Trading Project/01-raw}"
DB="${DB:-$BOT_DIR/trades.db}"
MODE="${EXPORT_FOR_VAULT_MODE:-vault}"

if [[ -n "${SSH_ORIGINAL_COMMAND:-}" ]]; then
  MODE="tar"
  REQ="$SSH_ORIGINAL_COMMAND"
else
  REQ="${1:-}"
fi

if [[ "$REQ" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  DATE="$REQ"
else
  DATE="$(date +%F)"
fi

[[ -d "$BOT_DIR" ]] || { echo "ERROR: bot dir not found: $BOT_DIR (set BOT_DIR=...)" >&2; exit 1; }
[[ -f "$DB" ]] || { echo "ERROR: trades.db not found: $DB" >&2; exit 1; }
if [[ "$MODE" != "tar" ]]; then
  [[ -d "$VAULT_RAW" ]] || { echo "ERROR: vault 01-raw not found: $VAULT_RAW (is the C: drive mounted?)" >&2; exit 1; }
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/bot-export-$DATE"
mkdir -p "$STAGE"

python3 - "$DB" "$DATE" "$STAGE/bot_events_${DATE}.json" "$STAGE/manifest.json" "$BOT_DIR" <<'PY'
import json
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

db, date, out_path, manifest_path, bot_dir = sys.argv[1:6]

con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
cols = [
    "id",
    "timestamp",
    "event_type",
    "symbol",
    "action",
    "decision",
    "severity",
    "reason",
    "source",
]
rows = con.execute(
    f"select {','.join(cols)}, payload_json from bot_events "
    "where date(timestamp)=? order by id",
    (date,),
).fetchall()


def slim_payload(raw):
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    slimmed = {}
    candidate = payload.get("candidate")
    if isinstance(candidate, dict):
        slimmed["candidate"] = {
            key: value
            for key, value in candidate.items()
            if value is not None and not isinstance(value, dict)
        }
    if payload.get("order") is not None:
        slimmed["order"] = payload["order"]
    return slimmed or None


events = []
for row in rows:
    event = {column: row[column] for column in cols}
    payload = slim_payload(row["payload_json"])
    if payload is not None:
        event["payload"] = payload
    events.append(event)

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
    "payload_handling": "slimmed: scalar candidate/order fields only; full payloads remain in trades.db",
    "source": "ops/export_for_vault.sh",
}
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)

print(f"events_for_date={len(events)}", file=sys.stderr)
PY

for logname in daily_summary after_close_learning post_session_review; do
  src="$BOT_DIR/${logname}.log"
  if [[ -s "$src" ]]; then
    cp "$src" "$STAGE/${logname}_${DATE}.log"
  fi
done

daily_src="$BOT_DIR/daily_summary.log"
daily_md="$STAGE/${DATE}-log.md"
if [[ -s "$daily_src" ]]; then
  python3 - "$daily_src" "$DATE" "$daily_md" <<'PY'
import re
import sys
from pathlib import Path

src, date, out = sys.argv[1:4]
text = Path(src).read_text(errors="replace")
marker = f"DAILY SUMMARY — {date}"
idx = text.rfind(marker)
if idx >= 0:
    start = text.rfind("\n", 0, idx)
    while start > 0 and set(text[start - 1:start + 1].strip()) <= {"="}:
        prev = text.rfind("\n", 0, start - 1)
        if prev < 0:
            break
        start = prev
    start = max(start, 0)
    finish_match = re.search(
        rf"^.*job-finish: daily_summary exit_code=\d+.*$",
        text[idx:],
        flags=re.MULTILINE,
    )
    end = idx + finish_match.end() if finish_match else len(text)
    summary = text[start:end].strip()
    Path(out).write_text(
        f"**Daily Summary: {date}**\n\n```text\n{summary}\n```\n",
    )
PY
fi

case "$MODE" in
  tar)
    tar -C "$WORK" -czf - "bot-export-$DATE"
    ;;
  vault)
    DEST="$VAULT_RAW/bot-export-$DATE"
    if [[ -e "$DEST" && ! -d "$DEST" ]]; then
      echo "ERROR: $DEST exists but is not a directory." >&2
      exit 1
    fi
    if [[ -d "$DEST" ]]; then
      echo "Updating existing $DEST"
    else
      mkdir -p "$DEST"
      echo "Wrote $DEST"
    fi
    cp -f "$STAGE"/* "$DEST"/
    if [[ -s "$daily_md" ]]; then
      TOP_LEVEL_SUMMARY="$VAULT_RAW/${DATE}-log.md"
      if [[ -e "$TOP_LEVEL_SUMMARY" && ! -f "$TOP_LEVEL_SUMMARY" ]]; then
        echo "ERROR: $TOP_LEVEL_SUMMARY exists but is not a file." >&2
        exit 1
      fi
      cp -f "$daily_md" "$TOP_LEVEL_SUMMARY"
    fi
    ls -lah "$DEST"
    ;;
  *)
    echo "ERROR: unsupported EXPORT_FOR_VAULT_MODE: $MODE" >&2
    exit 1
    ;;
esac
