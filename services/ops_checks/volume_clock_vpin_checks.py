"""Operator report for volume-clock VPIN research."""

from __future__ import annotations

from pathlib import Path

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository
from services.volume_clock_vpin_service import build_volume_clock_vpin_payload


def run_volume_clock_vpin_report(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str,
    bucket_volume: float = 500_000.0,
    window_buckets: int = 20,
    timeframe: str = "1m",
    limit: int = 20000,
    print_limit: int = 12,
) -> bool:
    rows = BarPatternFeatureRepository(base_dir / "trades.db").volume_clock_source_rows(
        target_date=target_date,
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
    )
    payload = build_volume_clock_vpin_payload(
        rows=rows,
        symbol=symbol,
        target_date=target_date,
        bucket_volume=bucket_volume,
        window_buckets=window_buckets,
    )
    data = payload.to_dict()
    summary = data["summary"]

    print()
    print("=" * 72)
    print("  Volume-Clock VPIN")
    print("=" * 72)
    print(f"report_version          : {data['report_version']}")
    print(f"runtime_effect          : {data['runtime_effect']}")
    print(f"symbol                  : {data['symbol']}")
    print(f"target_date             : {data['target_date']}")
    print(f"timeframe               : {timeframe}")
    print(f"source_rows             : {data['source_rows']}")
    print(f"bucket_volume           : {data['bucket_volume']}")
    print(f"window_buckets          : {data['window_buckets']}")
    print(f"bucket_count            : {summary['bucket_count']}")
    print(f"latest_vpin             : {summary['latest_vpin']}")
    print(f"avg_vpin                : {summary['avg_vpin']}")
    print(f"max_vpin                : {summary['max_vpin']}")
    print(f"toxicity_bucket         : {summary['toxicity_bucket']}")
    print(f"method                  : {summary['method']}")
    print(f"true_trade_level        : {summary['true_trade_level']}")

    print()
    print("Recent buckets")
    buckets = data["buckets"][-max(1, int(print_limit or 1)) :]
    if buckets:
        for bucket in buckets:
            print(
                f"  #{bucket['bucket_id']:<4} {bucket['start_ts']}..{bucket['end_ts']} "
                f"vol={bucket['volume']:<10} oi={bucket['order_imbalance']:<8} "
                f"vpin={bucket['vpin']}"
            )
    else:
        print("  none")

    print()
    if data["buckets"]:
        print("[OK] volume-clock VPIN buckets generated")
        return True
    print("[WARN] insufficient rows/volume for volume-clock VPIN buckets")
    return False
