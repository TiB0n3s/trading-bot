#!/usr/bin/env python3
"""
TradingView alert coverage report.

Reporting-only tool. Does not affect trading behavior.

Flags TradingView-alert symbols with:
- no alerts
- premarket-only alerts
- late first regular-session alert
- thin alert coverage

This is intended to catch TSCO/GLD-style strategy coverage gaps where
the bot cannot act because the upstream TradingView strategy never fired
or fired after the move was already mature.
"""

from __future__ import annotations

import argparse
from datetime import datetime, time
from zoneinfo import ZoneInfo

from symbols_config import TRADINGVIEW_ALERT_SYMBOLS_LIST

from repositories.trades_repo import tradingview_alert_rows

ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ET)
        return dt.astimezone(ET)
    except Exception:
        return None


def regular_session(ts: datetime) -> bool:
    t = ts.timetz().replace(tzinfo=None)
    return MARKET_OPEN <= t <= MARKET_CLOSE


def minutes_after_open(ts: datetime | None) -> int | None:
    if ts is None:
        return None
    return (ts.hour * 60 + ts.minute) - (MARKET_OPEN.hour * 60 + MARKET_OPEN.minute)


def classify(
    alert_count: int,
    first_regular: datetime | None,
    late_minutes: int,
    thin_count: int,
) -> tuple[str, str]:
    if alert_count == 0:
        return "missing_alerts", "no TradingView alerts found for report date"

    if first_regular is None:
        return "premarket_only", "alerts exist, but none during regular session"

    mins = minutes_after_open(first_regular)
    if mins is not None and mins > late_minutes:
        return "late_first_alert", f"first regular-session alert arrived {mins} minutes after open"

    if alert_count < thin_count:
        return "thin_alert_coverage", f"only {alert_count} alerts found"

    return "normal", "coverage appears normal"


def load_rows(report_date: str) -> dict[str, list]:
    symbols = list(TRADINGVIEW_ALERT_SYMBOLS_LIST)
    rows_by_symbol = {symbol: [] for symbol in symbols}

    if not symbols:
        return rows_by_symbol

    rows = tradingview_alert_rows(report_date, symbols)

    for row in rows:
        rows_by_symbol[row["symbol"]].append(row)

    return rows_by_symbol


def build_report(report_date: str, late_minutes: int, thin_count: int) -> list[dict]:
    rows_by_symbol = load_rows(report_date)
    report = []

    for symbol in TRADINGVIEW_ALERT_SYMBOLS_LIST:
        rows = rows_by_symbol.get(symbol, [])
        parsed = [(row, parse_ts(row["timestamp"])) for row in rows]
        parsed = [(row, ts) for row, ts in parsed if ts is not None]
        regular = [(row, ts) for row, ts in parsed if regular_session(ts)]

        first_alert = parsed[0][1] if parsed else None
        last_alert = parsed[-1][1] if parsed else None
        first_regular = regular[0][1] if regular else None

        status, note = classify(
            alert_count=len(parsed),
            first_regular=first_regular,
            late_minutes=late_minutes,
            thin_count=thin_count,
        )

        report.append(
            {
                "symbol": symbol,
                "alert_count": len(parsed),
                "first_alert": first_alert.strftime("%Y-%m-%d %H:%M:%S %Z") if first_alert else "",
                "last_alert": last_alert.strftime("%Y-%m-%d %H:%M:%S %Z") if last_alert else "",
                "first_regular_session_alert": first_regular.strftime("%Y-%m-%d %H:%M:%S %Z")
                if first_regular
                else "",
                "minutes_after_open": minutes_after_open(first_regular),
                "coverage_status": status,
                "notes": note,
            }
        )

    priority = {
        "missing_alerts": 0,
        "premarket_only": 1,
        "late_first_alert": 2,
        "thin_alert_coverage": 3,
        "normal": 4,
    }
    report.sort(key=lambda row: (priority.get(row["coverage_status"], 99), row["symbol"]))
    return report


def render(report_date: str, report: list[dict]) -> None:
    print()
    print("=" * 132)
    print(f"TradingView Alert Coverage Report — {report_date}")
    print("=" * 132)
    print(
        f"{'Symbol':<8} {'Alerts':>6} {'First regular':<24} {'MinAfterOpen':>12} {'Status':<22} Notes"
    )
    print("-" * 132)

    for row in report:
        mins = row["minutes_after_open"]
        print(
            f"{row['symbol']:<8} "
            f"{row['alert_count']:>6} "
            f"{row['first_regular_session_alert']:<24} "
            f"{'' if mins is None else mins:>12} "
            f"{row['coverage_status']:<22} "
            f"{row['notes']}"
        )

    flagged = [row for row in report if row["coverage_status"] != "normal"]
    print()
    print(f"Flagged symbols: {len(flagged)} / {len(report)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Market date in YYYY-MM-DD format")
    parser.add_argument("--late-minutes", type=int, default=45)
    parser.add_argument("--thin-count", type=int, default=3)
    args = parser.parse_args()

    report = build_report(args.date, args.late_minutes, args.thin_count)
    render(args.date, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
