"""Feature attribution operator report."""

from __future__ import annotations

from pathlib import Path

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.feature_attribution_service import build_feature_attribution_payload
from services.lifecycle_analysis_service import LifecycleAnalysisService


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_feature_attribution_report(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    min_sample_size: int = 30,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Feature Attribution Report - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(start_date=target_date, symbol=symbol)
    payload = build_feature_attribution_payload(
        lifecycle_payload.rows,
        min_sample_size=min_sample_size,
    )

    summary = payload.summary
    baseline = summary["baseline"]
    print(f"rows                    : {summary['rows']}")
    print(f"rows_with_outcome       : {summary['rows_with_outcome']}")
    print(f"authority_note          : {summary['authority_note']}")
    print(f"baseline_hit_rate       : {_fmt(baseline.get('hit_rate'))}")
    print(f"baseline_ev_pct         : {_fmt(baseline.get('ev_pct'))}")
    print(f"min_sample_size         : {summary['min_sample_size']}")

    if not summary["rows_with_outcome"]:
        print("[WARN] no lifecycle rows with realized/counterfactual outcomes")
        return False

    print()
    print("Feature family attribution")
    print(
        f"  {'family':<26} {'covered':>7} {'missing':>7} "
        f"{'best_bucket':<34} {'best_ev':>8} {'worst_bucket':<34} {'worst_ev':>8}"
    )
    for family in payload.families:
        best = family.get("best_bucket") or {}
        worst = family.get("worst_bucket") or {}
        print(
            f"  {family['family']:<26} "
            f"{family['covered_rows']:>7} "
            f"{family['missing_rows']:>7} "
            f"{str(best.get('bucket') or '-')[:34]:<34} "
            f"{_fmt(best.get('ev_pct')):>8} "
            f"{str(worst.get('bucket') or '-')[:34]:<34} "
            f"{_fmt(worst.get('ev_pct')):>8}"
        )

    print()
    print("Rollout guardrails")
    for item in payload.rollout_guardrails:
        print(
            f"  {item['family']:<26} status={item['status']:<22} "
            f"sample={item['sample_size']:<5} "
            f"missing={_fmt(item['missing_rate'])} "
            f"ev_spread={_fmt(item['ev_spread_pct'])}"
        )

    print()
    print("[OK] feature attribution report completed; no live authority changed")
    return True
