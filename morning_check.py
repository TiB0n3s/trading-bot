#!/usr/bin/env python3
"""
Morning readiness check — read-only operational premarket validation.

Usage:
  python3 morning_check.py
"""

import json
import os
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")


def reexec_under_venv_if_available():
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


reexec_under_venv_if_available()


def load_env_file(path=ENV_FILE):
    if not path.exists():
        return False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return True


load_env_file()

from config import APPROVED_SYMBOLS
from db_migrations import status as migration_status
from broker import get_account
from market_time import expected_market_context_date

MARKET_CONTEXT = BASE_DIR / "market_context.json"
ROLLING_MOMENTUM = BASE_DIR / "rolling_momentum.json"

SERVICES = [
    "trading-bot",
    "fill-stream",
    "cloudflared",
    "nginx",
]


def ok(msg):
    print(f"[OK]   {msg}")


def warn(msg):
    print(f"[WARN] {msg}")


def fail(msg):
    print(f"[FAIL] {msg}")


def service_active(name):
    try:
        r = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip()
    except Exception as e:
        return f"error: {e}"


def check_market_context():
    print("\n── Market Context ─────────────────────────────────────")

    if not MARKET_CONTEXT.exists():
        fail("market_context.json not found")
        return False

    try:
        ctx = json.loads(MARKET_CONTEXT.read_text())
    except Exception as e:
        fail(f"market_context.json could not be parsed: {e}")
        return False

    expected_date = expected_market_context_date().isoformat()
    market_date = ctx.get("market_date")
    symbols = ctx.get("symbols") or {}

    if market_date == expected_date:
        ok(f"market_date matches expected trading session: {market_date}")
    else:
        fail(f"market_date is stale or unexpected: {market_date} != {expected_date}")

    missing = sorted(APPROVED_SYMBOLS - set(symbols))
    extra = sorted(set(symbols) - APPROVED_SYMBOLS)

    if not missing:
        ok(f"all approved symbols present: {len(symbols)}/{len(APPROVED_SYMBOLS)}")
    else:
        fail(f"missing symbols: {missing}")

    if extra:
        warn(f"extra symbols present: {extra}")

    bias_counts = Counter(
        (entry or {}).get("bias", "missing")
        for entry in symbols.values()
        if isinstance(entry, dict)
    )

    print(f"macro_sentiment : {ctx.get('macro_sentiment')}")
    print(f"source          : {ctx.get('source')}")
    print(f"format          : {ctx.get('format')}")
    print(f"bias counts     : {dict(bias_counts)}")

    if bias_counts.get("buy", 0) == 0 and bias_counts.get("avoid", 0) == 0:
        warn("all symbols appear neutral/default; verify this is intentional")

    low_default = [
        sym for sym, e in symbols.items()
        if isinstance(e, dict)
        and e.get("confidence") == "low"
        and e.get("reason") == "no signals found"
    ]

    if len(low_default) > len(APPROVED_SYMBOLS) // 2:
        warn(f"{len(low_default)} symbols are default neutral/low; parser may not have captured full brief")
    else:
        ok("market bias entries appear populated")

    return market_date == expected_date and not missing


def check_rolling_momentum():
    print("\n── Rolling Momentum Context ─────────────────────────")

    if not ROLLING_MOMENTUM.exists():
        warn("rolling_momentum.json not found; observe-only context unavailable")
        return True

    try:
        data = json.loads(ROLLING_MOMENTUM.read_text())
    except Exception as e:
        warn(f"rolling_momentum.json could not be parsed: {e}")
        return True

    symbols = data.get("symbols") or {}
    missing = sorted(APPROVED_SYMBOLS - set(symbols))
    errors = [
        sym for sym, entry in symbols.items()
        if isinstance(entry, dict) and entry.get("error")
    ]

    print(f"generated_at  : {data.get('generated_at')}")
    print(f"market_time_et: {data.get('market_time_et')}")
    print(f"mode          : {data.get('mode')}")
    print(f"symbols       : {len(symbols)}/{len(APPROVED_SYMBOLS)}")
    print(f"errors        : {len(errors)}")

    if missing:
        warn(f"rolling momentum missing symbols: {missing}")
    else:
        ok("rolling momentum contains all approved symbols")

    if errors:
        warn(f"rolling momentum symbol errors: {errors[:10]}")
    else:
        ok("rolling momentum has no symbol errors")

    # Observe-only: do not fail morning readiness on this yet.
    return True


def check_services():
    print("\n── Services ───────────────────────────────────────────")
    all_ok = True

    for svc in SERVICES:
        status = service_active(svc)
        if status == "active":
            ok(f"{svc} active")
        else:
            fail(f"{svc} status={status}")
            all_ok = False

    return all_ok


def check_alpaca():
    print("\n── Alpaca Account ─────────────────────────────────────")
    try:
        acct = get_account()
    except Exception as e:
        fail(f"Alpaca account check failed: {e}")
        return False

    if not acct:
        fail("Alpaca account unavailable")
        return False

    ok(f"Alpaca reachable; status={acct.get('status')}")
    print(f"balance         : {acct.get('balance')}")
    print(f"portfolio_value : {acct.get('portfolio_value')}")
    print(f"buying_power    : {acct.get('buying_power')}")
    return True


def check_debug_endpoint():
    print("\n── Local Debug Endpoint ───────────────────────────────")

    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        warn("WEBHOOK_SECRET not in current shell env; skipping /debug endpoint check")
        return True

    url = f"http://localhost:5000/debug/symbol/QQQ?secret={secret}"

    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
    except Exception as e:
        fail(f"/debug/symbol endpoint failed: {e}")
        return False

    if data.get("symbol") == "QQQ":
        ok("/debug/symbol/QQQ reachable")
    else:
        fail(f"unexpected debug response symbol={data.get('symbol')}")
        return False

    blocks = data.get("would_block_buy_because")
    print(f"QQQ market_bias : {(data.get('market_bias') or {}).get('bias')}")
    print(f"QQQ trend       : {data.get('trend')}")
    print(f"QQQ buy blocks  : {blocks}")
    return True


def check_market_alignment_report():
    """Run observe-only market alignment report as part of morning readiness."""
    print("\n── Market Alignment Report ───────────────────────────")
    try:
        result = subprocess.run(
            [sys.executable, "market_alignment_report.py"],
            cwd=BASE_DIR,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            ok("Market alignment report completed")
            return True

        warn(f"Market alignment report exited with code {result.returncode}")
        return False

    except Exception as e:
        warn(f"Market alignment report failed: {e}")
        return False


def check_db_migrations():
    print("\n── DB Migrations ─────────────────────────────────────")
    try:
        rows = migration_status(BASE_DIR / "trades.db")
    except Exception as e:
        fail(f"migration status check failed: {e}")
        return False

    pending = [row for row in rows if not row["applied"]]
    for row in rows:
        marker = "applied" if row["applied"] else "pending"
        print(f"{marker:>8}  {row['migration_id']}")

    if pending:
        fail(f"{len(pending)} pending DB migration(s)")
        return False

    ok("all DB migrations applied")
    return True


def main():
    print("=" * 64)
    print("  Morning Readiness Check")
    print("=" * 64)

    checks = [
        check_market_context(),
        check_rolling_momentum(),
        check_db_migrations(),
        check_market_alignment_report(),
        check_services(),
        check_alpaca(),
        check_debug_endpoint(),
    ]

    print("\n" + "=" * 64)
    if all(checks):
        ok("Morning readiness check passed")
        return 0

    fail("Morning readiness check found issues")
    return 1


if __name__ == "__main__":
    sys.exit(main())
