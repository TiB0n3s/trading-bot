"""Operator report for volatile-session intelligence diagnostics."""

from __future__ import annotations

from pathlib import Path

from services.volatile_session_intelligence_service import (
    build_volatile_session_intelligence_payload,
)


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def run_volatile_session_intelligence_report(
    target_date: str,
    *,
    base_dir: Path,
    symbols: list[str],
    bucket_volume: float = 500_000.0,
    window_buckets: int = 20,
    start_time: str = "09:30",
    end_time: str = "10:00",
    timeframe: str = "1m",
) -> bool:
    payload = build_volatile_session_intelligence_payload(
        target_date=target_date,
        symbols=symbols,
        base_dir=base_dir,
        bucket_volume=bucket_volume,
        window_buckets=window_buckets,
        start_time=start_time,
        end_time=end_time,
        timeframe=timeframe,
    )
    penalty = payload["asymmetric_penalty"]
    summary = payload["summary"]
    window = payload["market_time_window"]

    print()
    print("=" * 72)
    print("  Volatile Session Intelligence")
    print("=" * 72)
    print(f"report_version                  : {payload['report_version']}")
    print(f"runtime_effect                  : {payload['runtime_effect']}")
    print(f"target_date                     : {payload['target_date']}")
    print(f"timeframe                       : {payload['timeframe']}")
    print(
        "market_time_window             : "
        f"{window['start_time']}..{window['end_time']} {window['timezone']}"
    )
    print(f"symbol_count                    : {payload['symbol_count']}")

    print()
    print("Asymmetric penalty probe")
    print(f"  provider                      : {penalty['provider']}")
    print(f"  objective                     : {penalty['objective']}")
    print(f"  configured_penalty            : {penalty['configured_penalty']:g}x")
    print(f"  gradient_penalty_ratio        : {penalty['gradient_penalty_ratio']}")
    print(f"  status                        : {penalty['status']}")

    print()
    print("Stress summary")
    print(f"  vpin_elevated_or_severe       : {summary['vpin_elevated_or_severe_symbols']}")
    print(f"  vpin_severe                   : {summary['vpin_severe_symbols']}")
    print(f"  vpin_insufficient             : {summary['vpin_insufficient_symbols']}")
    print(f"  symbols_with_window_rows      : {summary['symbols_with_window_rows']}")
    print(f"  transformer_size_down         : {summary['transformer_size_down_symbols']}")
    print(f"  transformer_block             : {summary['transformer_block_symbols']}")

    print()
    print("Symbol diagnostics")
    rows = payload["symbols"]
    if not rows:
        print("  none")
    for row in rows:
        print(
            f"  {row['symbol']:<6} rows={row['window_rows']:<5}/{row['source_rows']:<5} "
            f"buckets={row['vpin_bucket_count']:<4} "
            f"vpin={_fmt(row['latest_vpin']):<10} max={_fmt(row['max_vpin']):<10} "
            f"toxicity={row['toxicity_bucket']:<20} "
            f"transformer={row['transformer_decision']:<12} "
            f"mult={_fmt(row['transformer_size_multiplier']):<8} "
            f"prob={_fmt(row['transformer_probability'])}"
        )
        if row.get("transformer_reason"):
            print(f"         transformer_reason     : {row['transformer_reason']}")
        if row.get("latest_feature_timestamp"):
            print(f"         latest_feature_ts       : {row['latest_feature_timestamp']}")

    print()
    if summary["diagnostic_ready"]:
        print("[OK] volatile-session intelligence diagnostics evaluated")
        return True
    print("[WARN] volatile-session diagnostics are incomplete")
    return False
