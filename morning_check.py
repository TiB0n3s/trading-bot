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
from datetime import datetime
from pathlib import Path

import pytz

from config import APPROVED_SYMBOLS
from broker import get_account

BASE_DIR = Path(__file__).resolve().parent
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

    today_et = datetime.now(pytz.timezone("America/New_York")).date().isoformat()
    market_date = ctx.get("market_date")
    symbols = ctx.get("symbols") or {}

    if market_date == today_et:
        ok(f"market_date is today: {market_date}")
    else:
        fail(f"market_date is stale or unexpected: {market_date} != {today_et}")

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

    return market_date == today_et and not missing


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


def main():
    print("=" * 64)
    print("  Morning Readiness Check")
    print("=" * 64)

    checks = [
        check_market_context(),
        check_rolling_momentum(),
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
