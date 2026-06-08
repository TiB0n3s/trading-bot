"""Exit intelligence learning summary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repositories.exit_snapshot_repo import ExitSnapshotRepository


EXIT_INTELLIGENCE_VERSION = "exit_intelligence_summary_v1"


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.3f}"
    except Exception:
        return str(value)


def run_exit_intelligence_summary(
    *,
    base_dir: Path,
    start_date: str,
    end_date: str | None = None,
    limit: int = 12,
) -> bool:
    end_date = end_date or start_date
    payload = ExitSnapshotRepository(base_dir / "trades.db").exit_intelligence_summary(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    summary = payload.get("summary") or {}
    rows = int(summary.get("rows") or 0)
    print()
    print("=" * 72)
    print("  Exit Intelligence Summary")
    print("=" * 72)
    print(f"report_version                 : {EXIT_INTELLIGENCE_VERSION}")
    print("runtime_effect                 : exit_learning_report_no_live_authority")
    print(f"date_filter                    : {start_date}..{end_date}")
    print(f"exit_snapshots                 : {rows}")
    print(f"avg_realized_return_pct        : {_fmt(summary.get('avg_realized_return_pct'))}")
    print(f"avg_mfe_pct                    : {_fmt(summary.get('avg_mfe_pct'))}")
    print(f"avg_capture_ratio              : {_fmt(summary.get('avg_capture_ratio'))}")
    print(f"avg_missed_upside_pct          : {_fmt(summary.get('avg_missed_upside_pct'))}")
    print(f"avg_post_exit_return_30m_pct   : {_fmt(summary.get('avg_post_exit_return_30m_pct'))}")
    print(f"high_missed_upside_count       : {int(summary.get('high_missed_upside_count') or 0)}")
    print(f"post_exit_recovery_count       : {int(summary.get('post_exit_recovery_count') or 0)}")
    print(f"avoided_drawdown_count         : {int(summary.get('avoided_drawdown_count') or 0)}")
    if payload.get("trigger_rows"):
        print()
        print("Exit triggers")
        for row in payload["trigger_rows"]:
            print(
                f"  {row['exit_trigger']:<28} rows={int(row['rows']):<4} "
                f"ret={_fmt(row.get('avg_realized_return_pct')):<8} "
                f"capture={_fmt(row.get('avg_capture_ratio')):<8} "
                f"missed={_fmt(row.get('avg_missed_upside_pct')):<8}"
            )
    if payload.get("symbol_rows"):
        print()
        print("Symbols")
        for row in payload["symbol_rows"]:
            print(
                f"  {row['symbol']:<8} rows={int(row['rows']):<4} "
                f"ret={_fmt(row.get('avg_realized_return_pct')):<8} "
                f"capture={_fmt(row.get('avg_capture_ratio')):<8} "
                f"missed={_fmt(row.get('avg_missed_upside_pct')):<8}"
            )
    print()
    if rows:
        print("[OK] exit intelligence summary generated")
        return True
    print("[WARN] no exit snapshots available for date window")
    return True
