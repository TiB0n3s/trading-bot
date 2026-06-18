#!/usr/bin/env bash
#
# wsl_restore.sh — RUN THIS INSIDE WSL2 UBUNTU on your local PC.
#
# Pulls the whole project tree + SQLite DBs + secrets from the VM, rebuilds the
# Python environment, restores the schedule, and verifies. Run vm_capture.sh on
# the VM FIRST so the databases are quiesced and checkpointed.
#
# Re-runnable: rsync resumes partial transfers, so if the 60GB copy is
# interrupted just run this again.

set -euo pipefail

# ---- adjust these for your setup ------------------------------------------
VM_SSH="tradingbot@192.168.99.28"               # ssh target for the Ubuntu VM
VM_PROJECT_DIR="/home/tradingbot/trading-bot"   # path on the VM
LOCAL_PROJECT_DIR="/home/tradingbot/trading-bot" # MUST match VM path — the run_*.sh scripts hardcode it
ENV_DEST="/etc/trading-bot.env"
PYTHON="3.12"          # CPython version; provided by uv, not apt (matches the VM's python:3.12)
# ---------------------------------------------------------------------------

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# 0. sanity: we must be inside WSL
grep -qiE 'microsoft|wsl' /proc/version || { echo "This must run inside WSL2 Ubuntu."; exit 1; }

# ---------------------------------------------------------------------------
# PREFLIGHT — fail fast before the long transfer. Override with FORCE=1.
# ---------------------------------------------------------------------------
log "0/8  Preflight checks (SSH reachability + free space)"

# Need an ssh client to probe the VM; install it up front if missing.
if ! command -v ssh >/dev/null 2>&1; then
  echo "    ssh client missing — installing openssh-client"
  sudo apt-get update -qq && sudo apt-get install -y openssh-client
fi

# -- SSH reachability ------------------------------------------------------
echo "    checking SSH to $VM_SSH ..."
if ssh -o BatchMode=yes -o ConnectTimeout=10 "$VM_SSH" 'true' 2>/dev/null; then
  echo "      OK (key-based, non-interactive)"
elif ssh -o ConnectTimeout=10 "$VM_SSH" 'true'; then
  # falls through to here only if an interactive prompt succeeded
  echo "      OK (interactive auth) — consider 'ssh-copy-id $VM_SSH' so the"
  echo "      long rsync doesn't stall waiting for a password"
else
  echo "ERROR: cannot SSH to $VM_SSH. Fix VM_SSH / network / keys, then re-run." >&2
  [ "${FORCE:-0}" = "1" ] || exit 1
fi

# -- confirm the project dir exists on the VM ------------------------------
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$VM_SSH" "test -d '$VM_PROJECT_DIR'" 2>/dev/null; then
  echo "ERROR: $VM_PROJECT_DIR not found on the VM (check VM_PROJECT_DIR)." >&2
  [ "${FORCE:-0}" = "1" ] || exit 1
fi

# -- space: required (remote tree, minus venv/caches) vs available locally --
echo "    measuring source size on the VM (this counts the ~60GB DB) ..."
NEED_BYTES=$(ssh -o BatchMode=yes "$VM_SSH" \
  "du -sb --exclude=venv --exclude=venv-webull --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache '$VM_PROJECT_DIR' 2>/dev/null | cut -f1" \
  || echo 0)

# Available space on the ext4 filesystem backing the project (auto-grows
# against D: up to the distro's vhdx max size).
probe="$LOCAL_PROJECT_DIR"; while [ ! -d "$probe" ] && [ "$probe" != "/" ]; do probe="$(dirname "$probe")"; done
AVAIL_BYTES=$(df -B1 --output=avail "$probe" 2>/dev/null | tail -1 | tr -dc '0-9')

if [ -z "${NEED_BYTES:-}" ] || [ "${NEED_BYTES:-0}" -le 0 ]; then
  echo "    WARNING: couldn't measure remote size; skipping space comparison."
else
  # require destination free >= source * 1.25 (rebuilt venv + WAL/temp headroom)
  REQUIRED=$(( NEED_BYTES * 5 / 4 ))
  hr() { numfmt --to=iec "${1:-0}" 2>/dev/null || echo "${1:-0}B"; }
  echo "      source tree : $(hr "$NEED_BYTES")"
  echo "      need (x1.25): $(hr "$REQUIRED")"
  echo "      free here    : $(hr "${AVAIL_BYTES:-0}")  (on $probe)"
  if [ "${AVAIL_BYTES:-0}" -lt "$REQUIRED" ]; then
    echo "ERROR: not enough free space for the transfer." >&2
    echo "  If D: has room, the distro's vhdx max size may be the limit — grow it," >&2
    echo "  or set FORCE=1 to proceed anyway." >&2
    [ "${FORCE:-0}" = "1" ] || exit 1
  fi
  echo "      OK"
fi
# ---------------------------------------------------------------------------

log "1/8  Installing system prerequisites"
sudo apt-get update
# NOTE: Python itself is NOT installed via apt — this distro may not ship 3.12.
# uv provides a standalone CPython 3.12 below, matching the VM.
sudo apt-get install -y build-essential ca-certificates sqlite3 rsync openssh-client \
                        git curl

log "2/8  Installing uv + CPython $PYTHON (matches uv.lock and the VM)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"   # ensure uv is on PATH even if already installed
uv python install "$PYTHON"

log "3/8  Creating the project path (matching the VM so hardcoded paths work)"
sudo mkdir -p "$LOCAL_PROJECT_DIR"
sudo chown -R "$USER:$USER" "$(dirname "$LOCAL_PROJECT_DIR")/$(basename "$LOCAL_PROJECT_DIR")"

log "4/8  Rsyncing the project tree + databases from the VM"
echo "    (this is the long step — the 60GB+ trades.db dominates; resumable)"
rsync -a --info=progress2 --partial \
  --exclude 'venv/' --exclude 'venv-webull/' \
  --exclude '__pycache__/' --exclude '*.pyc' \
  --exclude '.pytest_cache/' --exclude '.ruff_cache/' \
  "$VM_SSH:$VM_PROJECT_DIR/" "$LOCAL_PROJECT_DIR/"

log "5/8  Placing the secrets file at $ENV_DEST"
if [ -f "$LOCAL_PROJECT_DIR/migration/_capture/trading-bot.env" ]; then
  sudo cp "$LOCAL_PROJECT_DIR/migration/_capture/trading-bot.env" "$ENV_DEST"
  sudo chown "$USER:$USER" "$ENV_DEST"
  sudo chmod 600 "$ENV_DEST"
  echo "    installed from captured copy"
else
  echo "    captured env not found; pulling directly from the VM"
  rsync -a "$VM_SSH:$ENV_DEST" /tmp/trading-bot.env
  sudo cp /tmp/trading-bot.env "$ENV_DEST"; sudo chown "$USER:$USER" "$ENV_DEST"; sudo chmod 600 "$ENV_DEST"
  rm -f /tmp/trading-bot.env
fi

log "6/8  Rebuilding the venv/ (name matters — run_*.sh and run_safety_checks.py expect venv/)"
cd "$LOCAL_PROJECT_DIR"
uv venv venv --python "$PYTHON"
# shellcheck disable=SC1091
source venv/bin/activate
uv pip install -r requirements-base.txt
uv pip install -r requirements-dev.txt         # pytest/ruff/mypy — needed by run_safety_checks.py
uv pip install -r requirements-research.txt    # torch/sklearn/xgboost — needed by the ML learning pipelines (heavy)
uv pip install --no-deps -e .                  # mirrors the Dockerfile's `pip install --no-deps .`

log "7/8  Verifying: DB migrations + databases + safety checks"
set -a; source "$ENV_DEST"; set +a
export PYTHONPATH="$LOCAL_PROJECT_DIR:$LOCAL_PROJECT_DIR/scripts:$LOCAL_PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

echo "--- quick_check on each DB (quick_check, not full integrity_check, so a 60GB DB finishes) ---"
for db in "$LOCAL_PROJECT_DIR"/*.db; do
  [ -e "$db" ] || continue
  echo -n "  $(basename "$db"): "; sqlite3 "$db" "PRAGMA quick_check;" | head -1
done

echo "--- migration status ---"
python db_migrations.py status || true

echo "--- safety checks (core risk/authority tests) ---"
python run_safety_checks.py || echo "  (review any failures before trusting the move)"

log "8/8  Restoring the schedule (cron)"
if [ -s "$LOCAL_PROJECT_DIR/migration/_capture/crontab.bak" ]; then
  echo "    A crontab backup exists. Review it, then install with:"
  echo "        crontab \"$LOCAL_PROJECT_DIR/migration/_capture/crontab.bak\""
  echo "    (Not auto-installed so you can confirm paths/timing first.)"
fi

cat <<'EOF'

============================================================
 RESTORE COMPLETE — remaining manual steps
============================================================
1. Enable systemd + cron persistence in WSL. In WSL run:
     printf '[boot]\nsystemd=true\n' | sudo tee /etc/wsl.conf
   then from a Windows terminal:  wsl --shutdown   (then reopen Ubuntu)

2. Install the reviewed crontab (see step 8 above).

3. (Optional) Give WSL more of the PC. Create  C:\Users\<you>\.wslconfig :
     [wsl2]
     memory=24GB        # or whatever headroom you want
     processors=8
   then  wsl --shutdown  to apply.

4. Run both VM and local in parallel for a session, compare outputs, THEN
   decommission the VM.

5. 24/7 later? WSL stops on reboot/sleep. You'll need a Task Scheduler entry
   to launch `wsl` at logon and disable PC sleep/hibernate.
============================================================
EOF
