"""Operator report for observe-only candidate model shadow predictions."""

from __future__ import annotations

from pathlib import Path
from statistics import mean

from repositories.shadow_prediction_repo import ShadowPredictionRepository
from services.shadow_prediction_service import SHADOW_REPORT_VERSION


def _bucket(score) -> str:
    try:
        value = float(score)
    except Exception:
        return "missing"
    if value >= 70:
        return "high_70_plus"
    if value >= 55:
        return "constructive_55_69"
    if value >= 45:
        return "neutral_45_54"
    return "weak_below_45"


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def run_shadow_prediction_report(target_date: str, *, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print(f"  Shadow Prediction Report - {target_date}")
    print("=" * 72)
    print(f"report_version         : {SHADOW_REPORT_VERSION}")
    print("runtime_effect         : observe_only_no_live_authority")

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    rows = ShadowPredictionRepository(db_path).load_shadow_prediction_outcomes(target_date)
    print(f"rows                   : {len(rows)}")
    if not rows:
        print("[WARN] no shadow prediction rows found")
        return False

    with_outcomes = [
        row
        for row in rows
        if row.get("ret_fwd_15m") is not None or row.get("ret_fwd_30m") is not None
    ]
    print(f"rows_with_outcomes     : {len(with_outcomes)}")

    by_model: dict[str, list[dict]] = {}
    by_bucket: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        model_id = str(row.get("model_id") or "unknown")
        bucket = _bucket(row.get("prediction_score"))
        by_model.setdefault(model_id, []).append(row)
        by_bucket.setdefault((model_id, bucket), []).append(row)

    print()
    print("By model")
    for model_id, model_rows in sorted(by_model.items()):
        outcome_rows = [row for row in model_rows if row.get("ret_fwd_15m") is not None]
        ret15 = [float(row["ret_fwd_15m"]) for row in outcome_rows]
        wins = sum(1 for value in ret15 if value > 0)
        avg_ret = _avg(ret15)
        avg_text = f"{avg_ret:.4f}" if avg_ret is not None else "-"
        win_rate = (wins / len(ret15) * 100.0) if ret15 else None
        win_text = f"{win_rate:.1f}%" if win_rate is not None else "-"
        print(
            f"  {model_id:<36} rows={len(model_rows):>5} "
            f"outcomes={len(outcome_rows):>5} win_rate={win_text:>7} avg15={avg_text:>9}"
        )

    print()
    print("By model/bucket")
    for (model_id, bucket), bucket_rows in sorted(by_bucket.items()):
        outcome_rows = [row for row in bucket_rows if row.get("ret_fwd_15m") is not None]
        ret15 = [float(row["ret_fwd_15m"]) for row in outcome_rows]
        ret30 = [
            float(row["ret_fwd_30m"]) for row in bucket_rows if row.get("ret_fwd_30m") is not None
        ]
        avg15 = _avg(ret15)
        avg30 = _avg(ret30)
        avg15_text = f"{avg15:.4f}" if avg15 is not None else "-"
        avg30_text = f"{avg30:.4f}" if avg30 is not None else "-"
        print(
            f"  {model_id[:28]:<28} {bucket:<20} rows={len(bucket_rows):>5} "
            f"outcomes={len(outcome_rows):>5} avg15={avg15_text:>9} avg30={avg30_text:>9}"
        )

    if not with_outcomes:
        print()
        print("[WARN] shadow predictions exist but labeled forward outcomes are not available yet")
        return False

    print()
    print("[OK] shadow predictions are scoreable against labeled outcomes")
    return True
