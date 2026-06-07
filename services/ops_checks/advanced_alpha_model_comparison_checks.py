"""Operator report for advanced alpha model comparison."""

from __future__ import annotations

from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository
from services.advanced_alpha_model_comparison_service import (
    build_advanced_alpha_model_comparison_payload,
)


def run_advanced_alpha_model_comparison(
    target_date: str,
    *,
    base_dir: Path,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Advanced Alpha Model Comparison - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = OpsCheckRepository(db_path)
    rows = [dict(row) for row in repo.pattern_learning_bar_pattern_rows(target_date)]
    payload = build_advanced_alpha_model_comparison_payload(rows)
    data = payload.to_dict()

    print(f"report_version          : {data['report_version']}")
    print(f"runtime_effect          : {data['runtime_effect']}")
    print(f"rows                    : {data['rows']}")
    print(f"rows_with_outcome       : {data['rows_with_outcome']}")
    print(f"authority_ready         : {data['summary']['authority_ready']}")

    print()
    print(
        f"  {'profile':<36} {'taken':>7} {'win_rate':>9} "
        f"{'avg_ret':>9} {'net':>9} {'max_dd':>9} {'sharpe':>9} {'fp':>6}"
    )
    print(f"  {'-' * 36} {'-' * 7} {'-' * 9} {'-' * 9} {'-' * 9} {'-' * 9} {'-' * 9} {'-' * 6}")
    for profile in data["profiles"]:
        win_rate = profile["win_rate"]
        avg_return = profile["avg_forward_return_pct"]
        sharpe = profile["sharpe_proxy"]
        print(
            f"  {profile['name']:<36} "
            f"{profile['trades_taken']:>7} "
            f"{(win_rate * 100.0 if win_rate is not None else 0.0):>8.2f}% "
            f"{(avg_return if avg_return is not None else 0.0):>9.4f} "
            f"{profile['net_return_units']:>9.4f} "
            f"{profile['max_drawdown_units']:>9.4f} "
            f"{(sharpe if sharpe is not None else 0.0):>9.4f} "
            f"{profile['false_positives']:>6}"
        )

    print()
    print(f"false_positive_reduction: {data['summary']['false_positive_reduction']}")
    print(f"drawdown_reduction_units: {data['summary']['drawdown_reduction_units']}")
    print(f"sharpe_proxy_delta      : {data['summary']['sharpe_proxy_delta']}")
    print(
        "asym_takes_fewer_trades : "
        f"{data['summary']['asymmetric_takes_fewer_or_equal_trades']}"
    )
    if data["rows_with_outcome"] == 0:
        print("[WARN] no forward outcomes available for comparison")
        return False

    print()
    print("[OK] advanced alpha model comparison completed; no live authority changed")
    return True
