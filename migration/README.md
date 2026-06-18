# VM → local (WSL2) migration

Moves the trading bot off the resource-constrained Ubuntu VM onto WSL2 Ubuntu
on the local Windows PC, so it uses the PC's CPU/RAM directly.

## What's being moved
- **Code** — the whole project tree (rsync'd, not re-cloned, for guaranteed parity).
- **Databases** — `trades.db` (~60GB, SQLite/WAL) and `jobs.db`, at the repo root.
- **Secrets** — `/etc/trading-bot.env`.
- **Runtime state** — `ml/`, `data/`, `reports/`, `logs/`, `runtime_state/`,
  `strategy_memory_history/`, and the root `*_memory.json` / `*_state.json` files.
- **Schedule** — the user's crontab (backed up, reinstalled after review).

`venv/` is **not** copied — it's rebuilt locally from `requirements-base.txt` + `uv.lock`.

## Where it physically lives (D:, the 8TB drive)
Everything runs inside WSL2's Linux (ext4) filesystem — including the ~60GB
`trades.db`. To put that on D: while keeping native ext4 speed and SQLite
safety, we **relocate the whole WSL distro's virtual disk (`ext4.vhdx`) onto
D:** (`setup_wsl_on_d.ps1`). The Linux files are then browsable from Windows at
`\\wsl.localhost\Ubuntu\home\tradingbot\trading-bot`, and they consume D:
capacity — but they are *not* loose files on D:.

> **Do NOT** put the project or DB on a Windows path like `/mnt/d/...`. WSL
> reaches Windows drives through a slow translation layer that is unreliable
> for SQLite file locking + WAL — a real corruption risk for `trades.db`.
> ext4-on-D: (via the relocated vhdx) is the correct way to use the 8TB drive.

## Order of operations
0. **On the local PC (Windows Terminal), once:** relocate WSL onto D: and size it:
   ```powershell
   powershell -ExecutionPolicy Bypass -File migration\setup_wsl_on_d.ps1
   ```
   (Host is 32 CPU / 64GB — the script caps WSL at 48GB / 24 CPU with 16GB swap,
   all on D:. Edit those values at the top if you want.)

1. **On the VM:** copy this `migration/` folder into the project, then run:
   ```bash
   bash migration/vm_capture.sh
   ```
   Stops writers, checkpoints the WAL DBs, snapshots crontab/secrets/package list.
   The VM is now quiesced — leave it powered on and SSH-reachable.

2. **In WSL2 Ubuntu (local PC):** edit the top of `wsl_restore.sh`
   (`VM_SSH`, paths), then run:
   ```bash
   bash migration/wsl_restore.sh
   ```
   Pulls everything, rebuilds `venv/`, verifies DB integrity + migrations +
   safety checks. The 60GB DB transfer is the long part and is resumable —
   just re-run if interrupted.

3. **Finish (manual, prompted by the script):** enable systemd in WSL,
   install the reviewed crontab, optionally raise WSL's resource caps via
   `.wslconfig`, run in parallel against the VM to confirm, then decommission.

## Rollback
`vm_capture.sh` only quiesces — it deletes nothing. To bring the VM back:
```bash
crontab migration/_capture/crontab.bak
while read -r u; do sudo systemctl start "$u"; done < migration/_capture/stopped_services.txt
```

## Notes / gotchas
- **Path parity:** the `run_*.sh` scripts hardcode `/home/tradingbot/trading-bot`.
  `wsl_restore.sh` recreates that exact path so they work unchanged. If you
  put the project elsewhere, find/replace that path in the run scripts.
- **WAL safety:** never plain-copy `trades.db` while the bot is writing.
  `vm_capture.sh` stops writers and checkpoints first — that's why step 1
  must precede the rsync.
- **Optional compaction:** `COMPACT=1 bash migration/vm_capture.sh` runs
  `VACUUM INTO` to shrink the churned 60GB DB before transfer — but it needs
  ~60GB free disk on the VM. Off by default for constrained VMs.
- **24/7 later:** WSL keeps running in the background but stops on reboot and
  when the PC sleeps. Always-on needs a Task Scheduler auto-start + disabled
  sleep/hibernate (+ ideally a UPS).
