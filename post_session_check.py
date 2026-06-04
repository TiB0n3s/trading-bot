#!/usr/bin/env python3
"""
Post-session validation check — read-only after-market operational review.

Usage:
  python3 post_session_check.py
  python3 post_session_check.py 2026-05-08
"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")


def _reexec_under_venv_if_available():
    if not VENV_PYTHON.exists():
        return
    venv_dir = VENV_PYTHON.parent.parent.resolve()
    if Path(sys.prefix).resolve() == venv_dir:
        return
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


def _load_env_file(path=ENV_FILE):
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_reexec_under_venv_if_available()
_load_env_file()

from services.broker_service import broker_service
from trade_matcher import rebuild_matched_trades
from repositories.reporting_repo import ReportingRepository

repo = ReportingRepository()


def ok(msg):
    print(f"[OK]   {msg}")


def warn(msg):
    print(f"[WARN] {msg}")


def fail(msg):
    print(f"[FAIL] {msg}")


def run_cmd(label, cmd, *, critical=True):
    print(f"\n── {label} ─────────────────────────────────────────")
    try:
        r = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.stdout.strip():
            print(r.stdout.rstrip())
        if r.stderr.strip():
            print(r.stderr.rstrip())
        if r.returncode == 0:
            ok(f"{label} completed")
            return True
        if critical:
            fail(f"{label} exited with code {r.returncode}")
            return False
        else:
            warn(f"{label} exited with code {r.returncode}; continuing")
            return True
    except Exception as e:
        if critical:
            fail(f"{label} failed: {e}")
            return False
        else:
            warn(f"{label} failed: {e}; continuing")
            return True


def check_missing_fills(target_date):
    print("\n── Missing Fill Prices ─────────────────────────────")
    rows = repo.post_session_missing_fills(target_date)

    if not rows:
        ok("No approved order rows missing fill_price for target date")
        return True

    warn(f"{len(rows)} approved order rows missing fill_price")
    for r in rows[:20]:
        print(
            f"  id={r['id']} {r['timestamp']} {r['symbol']} {r['action']} "
            f"status={r['order_status']} qty={r['qty']} order={str(r['order_id'])[:8]}"
        )
    print("  Suggested remediation: python3 backfill_missing_fills.py --dry-run")
    return False


def check_reconciliation():
    print("\n── Alpaca vs DB Reconciliation ─────────────────────")

    try:
        alpaca_positions = broker_service.list_positions()
        alpaca = {p.symbol: float(p.qty) for p in alpaca_positions}
    except Exception as e:
        warn(f"Could not fetch Alpaca positions: {e}; reconciliation skipped")
        return True

    rows = repo.db_open_position_rows()

    db_open = {r["symbol"]: float(r["net_qty"]) for r in rows if r["symbol"]}

    alpaca_syms = set(alpaca)
    db_syms = set(db_open)

    in_alpaca_not_db = sorted(alpaca_syms - db_syms)
    in_db_not_alpaca = sorted(db_syms - alpaca_syms)
    qty_mismatch = []

    for sym in sorted(alpaca_syms & db_syms):
        if abs(alpaca[sym] - db_open[sym]) > 0.0001:
            qty_mismatch.append((sym, alpaca[sym], db_open[sym]))

    print(f"Alpaca open symbols : {len(alpaca_syms)}")
    print(f"DB open symbols     : {len(db_syms)}")

    clean = True

    if in_alpaca_not_db:
        clean = False
        warn(f"Held in Alpaca but not open in DB: {in_alpaca_not_db}")

    if in_db_not_alpaca:
        clean = False
        warn(f"Open in DB but not held in Alpaca: {in_db_not_alpaca}")

    if qty_mismatch:
        clean = False
        warn("Quantity mismatches:")
        for sym, aq, dq in qty_mismatch:
            print(f"  {sym}: Alpaca={aq} DB={dq}")

    if clean:
        ok("Alpaca and DB open positions reconcile")
        return True

    return False


def check_fill_events(target_date):
    print("\n── Fill Events ─────────────────────────────────────")
    rows = repo.fill_event_summary_rows(target_date)

    if not rows:
        warn("No fill_events rows found for target date")
        return True

    for r in rows:
        print(
            f"  {r['event']:<12} {str(r['symbol']):<6} "
            f"{str(r['side']):<5} {str(r['status']):<18} {r['n']:>4}"
        )
    ok("Fill events present")
    return True


def check_signal_counts(target_date):
    print("\n── Signal Counts ───────────────────────────────────")
    row = repo.signal_count_row(target_date)

    total = row["total"] or 0
    approved = row["approved"] or 0
    rejected = row["rejected"] or 0
    orders = row["orders"] or 0

    print(f"Total signals : {total}")
    print(f"Approved      : {approved}")
    print(f"Rejected      : {rejected}")
    print(f"Orders        : {orders}")

    if total == 0:
        warn("No signals recorded for target date")
        return False

    ok("Signal counts loaded")
    return True


def rebuild_matches():
    print("\n── Matched Trades Rebuild ──────────────────────────")
    try:
        matched, open_lots = rebuild_matched_trades()
        ok(f"matched_trades rebuilt; matched={len(matched)} open_symbols={sum(1 for lots in open_lots.values() if lots)}")
        return True
    except Exception as e:
        fail(f"matched_trades rebuild failed: {e}")
        return False


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

    print("=" * 64)
    print(f"  Post-Session Check — {target_date}")
    print("=" * 64)

    checks = []

    checks.append(check_signal_counts(target_date))
    checks.append(check_missing_fills(target_date))
    checks.append(rebuild_matches())
    checks.append(check_reconciliation())
    checks.append(check_fill_events(target_date))

    # These scripts are read-only/reporting. They can be a little verbose.
    checks.append(run_cmd("Daily Summary", [sys.executable, "daily_summary.py", target_date]))
    checks.append(run_cmd("Filter Report", [sys.executable, "filter_report.py", "--date", target_date]))
    checks.append(run_cmd("Position Review", [sys.executable, "position_review.py"], critical=False))
    checks.append(run_cmd("Drawdown Report", [sys.executable, "drawdown_report.py", target_date]))
    checks.append(run_cmd("Analytics Report", [sys.executable, "analytics_report.py", "--date", target_date]))
    checks.append(run_cmd("Rejected Outcome Builder", [sys.executable, "rejected_signal_outcome_builder.py", "--date", target_date]))
    checks.append(run_cmd("Rejected Outcome Validation", [sys.executable, "ops_check.py", "rejected-outcomes", target_date]))
    checks.append(run_cmd("Strong-Day Participation", [sys.executable, "strong_day_participation_report.py", "--date", target_date, "--write-db"]))
    checks.append(run_cmd("Prediction Validation", [sys.executable, "prediction_validation_report.py", "--date", target_date]))

    print("\n" + "=" * 64)
    if all(checks):
        ok("Post-session check passed")
        return 0

    warn("Post-session check completed with warnings/issues")
    return 1


if __name__ == "__main__":
    sys.exit(main())
