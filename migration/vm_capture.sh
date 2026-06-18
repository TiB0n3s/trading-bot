#!/usr/bin/env bash
#
# vm_capture.sh — RUN THIS ON THE UBUNTU VM (as the tradingbot user, with sudo available).
#
# It does NOT transfer anything. It quiesces the bot, makes the SQLite
# databases safe to copy, and snapshots the bits of state that live outside
# the project tree (crontab, /etc secrets, apt package list). The big data
# transfer itself happens from the WSL side via wsl_restore.sh (rsync pull).
#
# Nothing here is destructive: the crontab is backed up before it is cleared,
# and re-enabling instructions are printed at the end.

set -euo pipefail

# ---- adjust if your VM layout differs -------------------------------------
PROJECT_DIR="/home/tradingbot/trading-bot"
ENV_FILE="/etc/trading-bot.env"
OUT="${PROJECT_DIR}/migration/_capture"        # metadata lands here; rsync'd with the tree
# ---------------------------------------------------------------------------

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

mkdir -p "$OUT"

log "1/6  Stopping writers (systemd services + cron) so the DB snapshot is consistent"
# Stop any systemd units that look like the bot. Record what we stopped.
mapfile -t UNITS < <(systemctl list-units --type=service --all --no-legend 2>/dev/null \
                     | awk '{print $1}' | grep -iE 'trading|tradingbot|gunicorn|webull' || true)
: > "$OUT/stopped_services.txt"
for u in "${UNITS[@]:-}"; do
  [ -n "$u" ] || continue
  echo "$u" >> "$OUT/stopped_services.txt"
  sudo systemctl stop "$u" || true
done
systemctl list-units --type=service --all --no-legend > "$OUT/all_services.txt" 2>/dev/null || true

# Back up the crontab, then clear it so nothing fires mid-snapshot.
if crontab -l > "$OUT/crontab.bak" 2>/dev/null; then
  crontab -r 2>/dev/null || true
  echo "  crontab backed up to $OUT/crontab.bak and cleared"
else
  echo "  (no crontab for this user)"
  : > "$OUT/crontab.bak"
fi

log "2/6  Checkpointing WAL on every SQLite DB at the project root"
# After this, with writers stopped, each *.db is a single consistent file and
# the -wal/-shm sidecars are emptied — safe to rsync as plain files.
checkpoint_db() {
  local db="$1"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$db" "PRAGMA wal_checkpoint(TRUNCATE); PRAGMA optimize;"
  else
    python3 - "$db" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1], timeout=30)
con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
con.execute("PRAGMA optimize")
con.close()
PY
  fi
}
shopt -s nullglob
for db in "$PROJECT_DIR"/*.db; do
  echo "  checkpoint: $db ($(du -h "$db" | cut -f1))"
  checkpoint_db "$db"
done
shopt -u nullglob

# OPTIONAL compaction: produces a defragmented copy and can shrink a churned
# 60GB DB substantially. Needs free disk ~= DB size. Disabled by default
# because a resource-constrained VM may not have the headroom. To use it,
# set COMPACT=1 when running, and rsync trades.compact.db instead of trades.db.
if [ "${COMPACT:-0}" = "1" ]; then
  log "    COMPACT=1 → VACUUM INTO trades.compact.db (needs ~DB-size free disk)"
  sqlite3 "$PROJECT_DIR/trades.db" "VACUUM INTO '$PROJECT_DIR/trades.compact.db'"
fi

log "3/6  Capturing the secrets file"
if sudo test -f "$ENV_FILE"; then
  sudo cp "$ENV_FILE" "$OUT/trading-bot.env"
  sudo chown "$USER:$USER" "$OUT/trading-bot.env"
  chmod 600 "$OUT/trading-bot.env"
  echo "  copied $ENV_FILE -> $OUT/trading-bot.env (mode 600)"
else
  echo "  WARNING: $ENV_FILE not found — locate your secrets file and copy it manually"
fi

log "4/6  Recording the environment (for rebuild parity, not for copying)"
python3 --version > "$OUT/python_version.txt" 2>&1 || true
dpkg --get-selections > "$OUT/apt-packages.txt" 2>/dev/null || true
( cd "$PROJECT_DIR" && [ -d venv ] && ./venv/bin/pip freeze > "$OUT/pip-freeze.txt" 2>/dev/null ) || true
uname -a > "$OUT/uname.txt" 2>&1 || true
lsb_release -a > "$OUT/ubuntu_release.txt" 2>&1 || true

log "5/6  Writing manifest"
{
  echo "captured_from   : $(hostname)"
  echo "project_dir     : $PROJECT_DIR"
  echo "env_file        : $ENV_FILE"
  echo
  echo "database sizes:"
  shopt -s nullglob
  for db in "$PROJECT_DIR"/*.db; do printf '  %-24s %s\n' "$(basename "$db")" "$(du -h "$db" | cut -f1)"; done
  shopt -u nullglob
  echo
  echo "total project tree size (excl. venv):"
  du -sh --exclude=venv --exclude=__pycache__ "$PROJECT_DIR" 2>/dev/null | cut -f1
} | tee "$OUT/MANIFEST.txt"

log "6/6  DONE — capture complete"
cat <<EOF

Next:
  • Run migration/wsl_restore.sh INSIDE your WSL Ubuntu. It will rsync this
    whole tree (including migration/_capture) plus the DBs from this VM.
  • Keep this VM powered on and reachable over SSH until the transfer verifies.

To RE-ENABLE this VM later (if you need to roll back):
    crontab "$OUT/crontab.bak"
    while read -r u; do sudo systemctl start "\$u"; done < "$OUT/stopped_services.txt"

