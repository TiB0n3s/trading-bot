"""Post-trade learning operator report."""

from __future__ import annotations

from pathlib import Path

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.lifecycle_analysis_service import LifecycleAnalysisService
from services.post_trade_learning_service import build_post_trade_learning_payload


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _print_rows(title: str, rows: list[dict], *, limit: int = 8) -> None:
    print()
    print(title)
    for row in rows[:limit]:
        print(
            f"  {str(row.get('bucket') or row.get('gate') or row.get('pattern'))[:58]:<58} "
            f"n={row.get('count') or row.get('rejections'):<4} "
            f"avg={_fmt(row.get('avg_return_pct') or row.get('avg_counterfactual_return_pct'))}"
        )


def run_post_trade_learning_report(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Post-Trade Learning Report - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(start_date=target_date, symbol=symbol)
    payload = build_post_trade_learning_payload(lifecycle_payload.rows)

    for key, value in payload.summary.items():
        print(f"{key:<36}: {value}")

    if not payload.summary["rows"]:
        print("[WARN] no lifecycle rows found")
        return False

    for dimension in (
        "setup_regime",
        "setup_label",
        "market_regime",
        "decision_hour",
        "session_phase",
        "execution_cost_bucket",
        "execution_quality_decision",
        "participation_state",
        "volatility_chase_risk",
    ):
        _print_rows(
            f"Expectancy by {dimension}",
            payload.expectancy_by_dimension.get(dimension) or [],
            limit=6,
        )

    _print_rows("Blocked-vs-allowed counterfactual gate value", payload.gate_value, limit=10)
    _print_rows("Top approved-loser patterns", payload.false_positive_patterns, limit=8)
    _print_rows("Top rejected-winner patterns", payload.false_negative_patterns, limit=8)

    print()
    print("[OK] post-trade learning report completed")
    return True
