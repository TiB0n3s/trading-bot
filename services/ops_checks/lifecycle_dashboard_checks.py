"""Decision lifecycle dashboard operator report."""

from __future__ import annotations

from pathlib import Path

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.lifecycle_analysis_service import LifecycleAnalysisService
from services.lifecycle_dashboard_service import build_lifecycle_dashboard_payload


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_lifecycle_dashboard(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    samples: int = 15,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Decision Lifecycle Dashboard - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(start_date=target_date, symbol=symbol)
    payload = build_lifecycle_dashboard_payload(
        lifecycle_payload.rows,
        samples=samples,
    )

    summary = payload.summary
    print(f"report_version                 : {summary['report_version']}")
    print(f"runtime_effect                 : {summary['runtime_effect']}")
    print(f"rows                           : {summary['rows']}")
    print(f"approved_rows                  : {summary['approved_rows']}")
    print(f"rejected_rows                  : {summary['rejected_rows']}")
    print(f"approved_exit_link_gaps        : {summary['approved_exit_link_gaps']}")
    print(
        "approved_matched_exit_missing_snapshot: "
        f"{summary['approved_matched_exit_missing_snapshot']}"
    )
    print(
        "approved_open_or_unlinked_exit: "
        f"{summary['approved_open_or_unlinked_exit']}"
    )
    print(f"rejected_snapshot_only_rows    : {summary['rejected_snapshot_only_rows']}")
    print(f"rejected_forward_outcome_gaps  : {summary['rejected_forward_outcome_gaps']}")
    print(f"approved_avg_return_pct        : {_fmt(summary['approved_avg_return_pct'])}")
    print(
        "rejected_cf_avg_return_pct     : "
        f"{_fmt(summary['rejected_counterfactual_avg_return_pct'])}"
    )
    print(f"analysis_ready                 : {summary['analysis_ready']}")

    if not summary["rows"]:
        print("[WARN] no lifecycle rows found")
        return False

    print()
    print("Lifecycle status")
    for item in payload.status_counts:
        print(f"  {item['bucket']:<38} {item['count']:>6}")

    print()
    print("Decision paths")
    for item in payload.decision_path_counts[:12]:
        print(f"  {item['bucket']:<58} {item['count']:>6}")

    print()
    print("Exit triggers")
    for item in payload.exit_trigger_counts[:12]:
        print(f"  {item['bucket']:<38} {item['count']:>6}")

    if payload.top_missed_rejections:
        print()
        print("Top rejected rows by forward MFE")
        print(
            f"  {'time':<19} {'sym':<6} {'mfe60':>8} {'ret60':>8} "
            f"{'setup':<18} {'regime':<20} reason"
        )
        for item in payload.top_missed_rejections:
            print(
                f"  {str(item.get('decision_time') or '-')[:19]:<19} "
                f"{str(item.get('symbol') or '-'):<6} "
                f"{_fmt(item.get('rejected_max_favorable_60m')):>8} "
                f"{_fmt(item.get('rejected_return_60m')):>8} "
                f"{str(item.get('setup_label') or '-')[:18]:<18} "
                f"{str(item.get('market_regime') or '-')[:20]:<20} "
                f"{item.get('rejection_reason') or '-'}"
            )

    ok = bool(summary["analysis_ready"])
    print()
    print("[OK] lifecycle dashboard is analysis-ready" if ok else "[WARN] lifecycle dashboard has coverage gaps")
    return ok
