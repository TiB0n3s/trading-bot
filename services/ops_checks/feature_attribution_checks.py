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
    rolling_window_size: int = 50,
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
        rolling_window_size=rolling_window_size,
    )

    summary = payload.summary
    baseline = summary["baseline"]
    print(f"report_version          : {summary['report_version']}")
    print(f"rows                    : {summary['rows']}")
    print(f"rows_with_outcome       : {summary['rows_with_outcome']}")
    print(f"authority_note          : {summary['authority_note']}")
    print(f"baseline_hit_rate       : {_fmt(baseline.get('hit_rate'))}")
    print(f"baseline_ev_pct         : {_fmt(baseline.get('ev_pct'))}")
    print(f"min_sample_size         : {summary['min_sample_size']}")
    print(f"rolling_window_size     : {summary['rolling_window_size']}")

    if not summary["rows_with_outcome"]:
        print("[WARN] no lifecycle rows with realized/counterfactual outcomes")
        return False

    print()
    print("Feature family ranking")
    ranked = sorted(
        payload.families,
        key=lambda item: (
            -abs((item.get("best_bucket") or {}).get("ev_delta_pct") or 0.0),
            -((item.get("best_bucket") or {}).get("false_positive_reduction") or 0.0),
            ((item.get("best_bucket") or {}).get("false_negative_increase") or 0.0),
            item["family"],
        ),
    )
    print(
        f"  {'rank':>4} {'family':<26} {'bucket':<28} {'ev_delta':>9} "
        f"{'hit_delta':>9} {'fp_red':>8} {'fn_cost':>8} {'stable':>8} {'roll':>8}"
    )
    for idx, family in enumerate(ranked, start=1):
        best = family.get("best_bucket") or {}
        stability = family.get("stability") or {}
        print(
            f"  {idx:>4} {family['family']:<26} {str(best.get('bucket') or '-')[:28]:<28} "
            f"{_fmt(best.get('ev_delta_pct')):>9} "
            f"{_fmt(best.get('hit_rate_delta')):>9} "
            f"{_fmt(best.get('false_positive_reduction')):>8} "
            f"{_fmt(best.get('false_negative_increase')):>8} "
            f"{_fmt(stability.get('stable_window_share')):>8} "
            f"{_fmt(stability.get('rolling_stable_window_share')):>8}"
        )

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
        stability = item.get("stability") or {}
        print(
            f"  {item['family']:<26} status={item['status']:<22} "
            f"sample={item['sample_size']:<5} "
            f"missing={_fmt(item['missing_rate'])} "
            f"ev_spread={_fmt(item['ev_spread_pct'])} "
            f"stable_windows={_fmt(stability.get('stable_window_share'))} "
            f"daily={_fmt(stability.get('daily_stable_window_share'))} "
            f"rolling={_fmt(stability.get('rolling_stable_window_share'))}"
        )

    if payload.feature_overlap:
        print()
        print("Potential feature-family overlap")
        for item in payload.feature_overlap[:12]:
            print(
                f"  {item['left_family']}={item['left_bucket']} "
                f"<-> {item['right_family']}={item['right_bucket']} "
                f"overlap={item['overlap_rate']:.4f} "
                f"n={item['sample_size']} risk={item['risk']}"
            )

    print()
    print("[OK] feature attribution report completed; no live authority changed")
    return True
