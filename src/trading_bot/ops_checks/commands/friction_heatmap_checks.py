"""Operator report for LSI friction heatmap diagnostics."""

from __future__ import annotations

from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository
from services.friction_heatmap_service import build_friction_heatmap_payload


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def run_friction_heatmap(
    target_date: str,
    *,
    base_dir: Path,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Friction Heatmap - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = OpsCheckRepository(db_path)
    rows = [dict(row) for row in repo.pattern_learning_bar_pattern_rows(target_date)]
    payload = build_friction_heatmap_payload(rows)
    data = payload.to_dict()

    print(f"report_version          : {data['report_version']}")
    print(f"runtime_effect          : {data['runtime_effect']}")
    print(f"rows                    : {data['rows']}")
    print(f"rows_with_outcome       : {data['rows_with_outcome']}")
    print(f"authority_ready         : {data['summary']['authority_ready']}")
    print(f"symmetric_toxic_stopouts: {data['summary']['symmetric_toxic_stopouts']}")
    print(f"asym_toxic_avoided     : {data['summary']['asymmetric_toxic_stopouts_avoided']}")
    print(f"asym_scale_down_cands  : {data['summary']['asymmetric_lsi_scale_down_candidates']}")

    print()
    print(
        f"  {'profile':<28} {'bucket':<10} {'rows':>7} {'taken':>7} "
        f"{'stop':>7} {'toxic':>7} {'avg_lsi':>9} {'avg_ret':>9} {'stop_rate':>10}"
    )
    print(
        f"  {'-' * 28} {'-' * 10} {'-' * 7} {'-' * 7} {'-' * 7} "
        f"{'-' * 7} {'-' * 9} {'-' * 9} {'-' * 10}"
    )
    for cell in data["heatmap"]:
        stopout_rate = cell["stopout_rate"]
        print(
            f"  {cell['profile']:<28} "
            f"{cell['liquidity_stress_bucket']:<10} "
            f"{cell['rows']:>7} "
            f"{cell['trades_taken']:>7} "
            f"{cell['stopouts']:>7} "
            f"{cell['toxic_stopouts']:>7} "
            f"{_fmt(cell['avg_lsi_score'], 2):>9} "
            f"{_fmt(cell['avg_forward_return_pct'], 4):>9} "
            f"{((stopout_rate or 0.0) * 100.0):>9.2f}%"
        )

    if data["rows_with_outcome"] == 0:
        print("[WARN] no forward outcomes available for friction heatmap")
        return False

    print()
    print("[OK] friction heatmap completed; no live authority changed")
    return True
