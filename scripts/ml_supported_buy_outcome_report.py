#!/usr/bin/env python3
"""Report ML-supported auto-buy candidates taken vs skipped."""

from __future__ import annotations

import argparse
from datetime import datetime

import pytz

from services.ml_supported_buy_outcome_service import MlSupportedBuyOutcomeService

ET = pytz.timezone("America/New_York")


def _fmt(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(ET).strftime("%Y-%m-%d"))
    parser.add_argument("--min-score", type=float, default=14.0)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    service = MlSupportedBuyOutcomeService()
    service.config = service.config.__class__(min_score=args.min_score)
    report = service.report(args.date)

    print("=" * 88)
    print("  ML-Supported Buy Outcome Report")
    print("=" * 88)
    print(f"report_version          : {report['report_version']}")
    print(f"runtime_effect          : {report['runtime_effect']}")
    print(f"date                    : {report['date']}")
    print(f"min_score               : {report['min_score']}")
    print(f"rows                    : {report['rows']}")
    print(f"taken_rows              : {report['taken_rows']}")
    print(f"skipped_rows            : {report['skipped_rows']}")

    print()
    print("Outcome Summary")
    for status, bucket in sorted(report["by_status"].items()):
        print(
            f"  {status:<8} rows={bucket['rows']:<4} "
            f"avg15={_fmt(bucket.get('avg_return_15m_pct')):>9} "
            f"avg60={_fmt(bucket.get('avg_return_60m_pct')):>9}"
        )

    print()
    print("Top Candidates")
    print(
        f"{'Time':<19} {'Sym':<6} {'Status':<8} {'Score':>7} "
        f"{'Decision':<22} {'Ret15':>9} {'Ret60':>9} Reason"
    )
    print("-" * 120)
    for item in report["candidates"][: args.top]:
        print(
            f"{str(item['timestamp'])[:19]:<19} "
            f"{item['symbol']:<6} "
            f"{item['status']:<8} "
            f"{_fmt(item['score']):>7} "
            f"{str(item['decision']):<22} "
            f"{_fmt(item.get('return_15m_pct')):>9} "
            f"{_fmt(item.get('return_60m_pct')):>9} "
            f"{item.get('hard_block_reason') or item.get('reason') or ''}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
