# Incident Report

## Summary

- Incident ID: incident_20260702T111008Z_stale-daily-db-backup-hung-in-io-wait
- Title: stale daily db backup hung in io wait
- Severity: high
- Status: open; trading halted for auto-buy, backup coverage zero
- Started At: 2026-07-02T11:10:08.642594+00:00
- Resolved At: -
- Owner: operator

## Impact

- Trading mode affected: scheduled auto-buy disabled as emergency risk reduction before the regular session.
- Symbols affected: none observed.
- Orders affected: none observed.
- Data/learning affected: live `trades.db` reads and research replay reads entered kernel I/O wait while a stale daily backup process was active. A later heartbeat exercise exposed an adhoc retention bug that deleted the recent manifest-referenced tiered backup artifacts; standalone `trades.db` backup coverage is currently zero verified restorable DBs until a fresh backup completes verification.
- User/operator impact: hold-duration validation had to use the last completed verified backup instead of the live DB while the live DB file was under backup I/O pressure.

## Detection

- Detected by: operator/Codex investigation during hold-duration replay validation.
- First alert/report: replay and raw SQLite reads against `trades.db` entered `D` I/O wait; process list showed stale `daily_db_backup_son`.
- Related commands:
  - `ps -eo pid,stat,etime,pcpu,pmem,args | grep -E 'database_backup|daily_db_backup|ops_check.py hold-duration|python3 -'`
  - `tail -120 backups/backup.log`
  - `python3 ops_check.py database-backups --max-age-hours 48`
  - `crontab -l | grep -n "daily_db_backup_son\|database_backup.py"`

## Timeline

- `2026-07-02T11:10:08.642594+00:00` - Incident record opened.
- `2026-07-02T01:30:01Z` - Stale installed cron launched `daily_db_backup_son`.
- `2026-07-02T02:29Z` - Process list later showed `pipeline/database_backup.py --backup-tier son` still active in `D` state after roughly 59 minutes.
- `2026-07-02T02:30Z` - Operator sent SIGTERM to the stale backup job runner and child process; processes exited.
- `2026-07-02T11:08Z` - Installed crontab was backed up and the stale `daily_db_backup_son` entry was removed.
- `2026-07-02T11:12Z` - Remaining weekly/monthly database backup cron jobs were bounded with `--timeout-seconds 3600`, `--ionice-idle`, and `--nice 10`; checked-in cron contract updated and installed.
- `2026-07-02T11:20Z` - Added `ops_check.py cron-drift`, installed a premarket scheduler drift check, added backup heartbeat/stale-process/unmanifested-artifact detection, and quarantined the unmanifested 2026-07-02 backup directory.
- `2026-07-02T11:09Z` - `ops_check.py database-backups --max-age-hours 48` reported latest completed manifest fresh/restorable via grandfather manifest reusing the verified 2026-07-01 son backup.
- `2026-07-02T11:32Z` - Ran a real `pipeline/database_backup.py --backup-tier adhoc --retention-days 1 --db trades.db --skip-recent-full-hours 168` heartbeat exercise. The run wrote heartbeat status `finished` and a fresh manifest, but exposed a pruning bug: default adhoc pruning recursively traversed tier subdirectories and deleted the recently reused `son/20260701T013001Z` backup artifacts.
- `2026-07-02T11:33Z` - Added health detection for manifest-referenced backup paths missing from disk; `ops_check.py database-backups` correctly failed the reused manifest.
- `2026-07-02T11:35Z` - Attempted read-only verification of the quarantined 2026-07-02 stale-job artifact; verifier entered `D` state (`folio_wait_bit_common`) and was terminated without producing trust evidence.
- `2026-07-02T11:42Z` - Started a fresh low-priority online SQLite backup. Copy reached full `trades.db` size, then verification entered the same `D` state wait channel without writing a manifest.
- `2026-07-02T12:01Z` - Terminated the fresh backup verification, quarantined `backups/databases/20260702T114254Z` as `backups/databases/quarantine/20260702T114254Z_unverified_online_backup`, wrote failed manifest `backups/databases/database_backup_20260702T120152Z.manifest.json`, and set heartbeat status to `failed`.
- `2026-07-02T12:09Z` - Read-only `sqlite3 trades.db` diagnostic queries also entered `D` state at `folio_wait_bit_common`, confirming the fault is below application-level SQLite locking or backup code.
- `2026-07-02T12:15Z` - Removed both scheduled `auto_buy_manager --live` cron entries from the checked-in and installed crontab through `scripts/install_operator_crontab.py --apply`; `cron-drift` passed afterward.
- `2026-07-02T12:16Z` - Set `/etc/trading-bot.env` `AUTO_BUY_LIVE_BUYS=false`; resolved `config.auto_buy.load_auto_buy_config().live_buys` is `False`.

## Root Cause

- Technical cause: repeated `D`-state waits on `trades.db` access confirm a degraded lower storage layer for `/dev/sdd` ext4, not an application-level SQLite lock or backup-script bug. The repo is running under WSL2 on a virtual disk, so the failing layer is the WSL virtual block device/ext4/VHD path until Windows-host diagnostics prove the physical disk boundary.
- Original trigger: stale installed crontab still contained `daily_db_backup_son`, even though `ops/crontab.tradingbot.current.txt` no longer includes that job and documents daily recovery as VM snapshot-owned.
- Contributing factors: the stale job invoked a full SQLite online backup plus `PRAGMA integrity_check` for a 41 GB `trades.db` copy with no explicit job-runner timeout or I/O throttling. The destination DB reached full size, but no 2026-07-02 manifest or `job-finish` line was written, so the likely hang point was backup verification or filesystem I/O after the copy phase. The backup service also let the default adhoc tier prune recursively from the backup root, crossing into `son`, `father`, and `grandfather` tier directories.
- What made detection harder: the July 2 backup directory contained a full-sized `trades.db` artifact, but no manifest. File size alone looked plausible while the authoritative completion marker was absent.

## Resolution

- Immediate mitigation: terminated the stale backup process and stopped replay/database probes that were waiting on DB I/O.
- Scheduler fix: removed the stale `daily_db_backup_son` line from the installed crontab; only weekly father and monthly grandfather database backup jobs remain installed, both with explicit 3600-second timeouts and idle I/O priority.
- Deployment fix: added `scripts/install_operator_crontab.py`; normal scheduler changes now install from the repo-owned crontab reference with a timestamped pre-install backup. Installed crontab was reapplied through this path at `2026-07-02T11:32Z`.
- Detection fix: `ops_check.py cron-drift` now compares the installed user crontab against `ops/crontab.tradingbot.current.txt`, and the checked-in/installed crontab runs `scheduler_drift_check` before the regular session. `ops_check.py database-backups` now reports active backup processes, stale running heartbeats, heartbeat phase, recent DB artifacts without completed manifest references, and manifest-referenced artifacts missing from disk.
- Code fix: adhoc retention pruning now excludes tier directories and protects the backup path reused by the current manifest. Interrupted backup runs now attempt to write a failed heartbeat on SIGTERM/SIGINT.
- Emergency trading halt: scheduled internal auto-buy is disabled by removing `auto_buy_manager --live` from the installed crontab, and `/etc/trading-bot.env` now has `AUTO_BUY_LIVE_BUYS=false`. Do not restore either path until storage is repaired and a fresh manifest-backed database backup passes restore verification.
- Current state: not resolved. `ops_check.py database-backups --max-age-hours 48 --stale-process-minutes 45` fails because the latest manifest is a failed interrupted verification; this is intentional and must remain red until a fresh `trades.db` backup completes integrity verification. Verified restorable `trades.db` backup coverage is zero.
- Rollback used: installed crontab was backed up to `migration/crontab.backup.20260702T1110-before-remove-daily-db-backup.bak` before the change.

## Evidence Links

- Job run: `trades.db.job_runs` has successful `daily_db_backup_son` rows through 2026-07-01; the killed 2026-07-02 run did not record a finish row.
- Logs: `backups/backup.log` has `2026-07-02T01:30:01.438593+00:00 job-start: daily_db_backup_son` with no corresponding manifest or finish line.
- Superseded backup manifest: `backups/databases/son/database_backup_20260701T020114Z.manifest.json` recorded `trades.db` status `verified`, `integrity_check=ok`, `table_count=44`, and matching source/backup size `43577221120`, but the referenced artifact was later deleted by the adhoc prune bug and must not be treated as currently restorable.
- Untrusted artifact: `backups/databases/quarantine/20260702T013001Z/trades.db` exists but has no manifest; do not treat it as restorable evidence.
- Untrusted recovery artifact: `backups/databases/quarantine/20260702T114254Z_unverified_online_backup/trades.db` reached full source size but verification was interrupted after a D-state wait; do not treat it as restorable evidence.
- Failed manifest: `backups/databases/database_backup_20260702T120152Z.manifest.json` records the interrupted verification as `status=failed`.
- Current backup health: `ops_check.py database-backups --max-age-hours 48 --stale-process-minutes 45` fails with `failed_count=1`, `heartbeat_status=failed`, and `heartbeat_phase=interrupted_verify`.
- Auto-buy halt: installed crontab has no `--job-name auto_buy_manager` command lines; `ops_check.py cron-drift` passes after deployment. `/etc/trading-bot.env` has `AUTO_BUY_LIVE_BUYS=false`, and `load_auto_buy_config().live_buys` resolves to `False`.
- Live exposure snapshot: `scripts/dt_positions_snapshot.py --json` at `2026-07-02T12:16:42Z` reported account active, equity/cash `$100270.52`, buying power `$401082.08`, `positions=[]`, and unrealized P&L `$0.00`.
- Host/storage evidence: repository path is on `/dev/sdd` ext4 inside WSL2. Non-interactive `sudo` is unavailable, `smartctl` is not installed in the WSL guest, and no-administrator SMART/host-disk diagnostics have not been run.
- Installed crontab backup: `migration/crontab.backup.20260702T1110-before-remove-daily-db-backup.bak`.
- Repo-backed crontab install backup: `migration/crontab.backup.20260702T113208Z.before-install-reference.bak`.
- Order/fill records: none linked.
- Learning artifacts: hold-duration validation used the verified 2026-07-01 backup for the 2026-06-10..2026-06-20 locked window.
- Model artifacts: none.
- Commit(s): not committed.

## Follow-Up Actions

- [x] Action: remove stale installed daily DB backup cron entry.
- [x] Test/monitoring added: cron contract now requires database backup jobs to use an explicit timeout, idle I/O priority, and no daily son backup entry.
- [x] Action: quarantine the unmanifested 2026-07-02 backup artifact.
- [x] Test/monitoring added: add/confirm an ops check that flags backup artifacts without manifests.
- [x] Test/monitoring added: add scheduler drift detection for installed-vs-reference crontab divergence.
- [x] Action: add repo-backed crontab installer and deploy installed crontab from the checked-in reference.
- [x] Bug fix: restrict adhoc backup pruning so it cannot cross into tier directories.
- [x] Test/monitoring added: fail backup health when a restorable manifest row references a missing DB artifact.
- [x] Test/monitoring added: backup progress callbacks can refresh heartbeat progress during copy/verify phases.
- [x] Emergency risk reduction: remove scheduled `auto_buy_manager --live` cron entries and deploy the repo-owned crontab.
- [x] Emergency risk reduction: set `AUTO_BUY_LIVE_BUYS=false` in `/etc/trading-bot.env`.
- [ ] Recovery: complete a fresh `trades.db` backup with `integrity_check=ok` and a manifest that passes `ops_check.py database-backups`.
- [ ] Investigation: diagnose the WSL `/dev/sdd` ext4/VHD/host-storage fault from the Windows/administrator side; run host disk health diagnostics or migrate the repo/DB to known-good storage before retrying backup verification.
- [x] Documentation updated: document that `database_backup_health_v1` must use manifests, not file size, as backup truth.

## Lessons

- What worked: manifest-based backup verification clearly distinguished the completed 2026-07-01 backup from the untrusted 2026-07-02 artifact.
- What failed: installed crontab drifted from the checked-in cron reference, leaving a stale heavy job active. The first heartbeat exercise also exposed that backup retention was able to delete backup artifacts outside the active tier, and backup verification can still enter uninterruptible I/O wait.
- What to change before cash-live authority: scheduler drift should be part of premarket/runtime checks for high-I/O jobs, not only service liveness.
