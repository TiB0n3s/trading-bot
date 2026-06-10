"""Operator report for observe-only symbol pattern outcomes."""

from __future__ import annotations

from pathlib import Path

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.lifecycle_analysis_service import LifecycleAnalysisService
from services.symbol_pattern_outcome_service import build_symbol_pattern_outcome_payload


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_symbol_pattern_outcomes(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    min_sample_size: int = 30,
    limit: int = 20,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Symbol Pattern Outcomes - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(start_date=target_date, symbol=symbol)
    payload = build_symbol_pattern_outcome_payload(
        lifecycle_payload.rows,
        min_sample_size=min_sample_size,
    )
    summary = payload.summary
    baseline = summary["baseline"]
    print(f"report_version          : {summary['report_version']}")
    print(f"runtime_effect          : {summary['runtime_effect']}")
    print(f"rows                    : {summary['rows']}")
    print(f"rows_with_outcome       : {summary['rows_with_outcome']}")
    print(f"pattern_rows            : {summary['pattern_rows']}")
    print(f"distinct_patterns       : {summary['distinct_patterns']}")
    print(f"baseline_hit_rate       : {_fmt(baseline.get('hit_rate'))}")
    print(f"baseline_ev_pct         : {_fmt(baseline.get('ev_pct'))}")
    print(f"min_sample_size         : {summary['min_sample_size']}")
    if symbol:
        print(f"symbol                  : {symbol.upper()}")

    if not summary["rows"]:
        print("[WARN] no lifecycle rows found")
        return False
    if not summary["rows_with_outcome"]:
        print("[WARN] no lifecycle rows with realized/counterfactual outcomes")
        return False

    if payload.quality_warnings:
        print()
        print("Quality warnings")
        for item in payload.quality_warnings:
            detail = item.get("rate", item.get("count", item.get("distinct_patterns", "-")))
            print(
                f"  {item['severity']:<5} {item['warning']:<34} "
                f"value={_fmt(detail)} reason={item.get('reason') or '-'}"
            )

    print()
    print("Pattern outcomes")
    print(
        f"  {'pattern':<36} {'n':>5} {'appr':>5} {'rej':>5} "
        f"{'hit':>7} {'ev':>8} {'ev_delta':>9} {'mfe':>8} {'mae':>8} "
        f"{'wbl':>7} {'source_mix'}"
    )
    for item in payload.pattern_outcomes[:limit]:
        print(
            f"  {item['pattern'][:36]:<36} "
            f"{item['sample_size']:>5} {item['approved_count']:>5} {item['rejected_count']:>5} "
            f"{_fmt(item.get('hit_rate')):>7} {_fmt(item.get('ev_pct')):>8} "
            f"{_fmt(item.get('ev_delta_pct')):>9} {_fmt(item.get('mfe_pct')):>8} "
            f"{_fmt(item.get('mae_pct')):>8} {_fmt(item.get('winner_became_loser_rate')):>7} "
            f"{item.get('source_mix') or {}}"
        )

    print()
    print("Calibration buckets")
    print(f"  {'interaction':<22} {'bucket':<52} {'n':>5} {'hit':>7} {'ev':>8}")
    for item in payload.calibration_buckets[:limit]:
        print(
            f"  {item['interaction']:<22} {item['bucket'][:52]:<52} "
            f"{item['sample_size']:>5} {_fmt(item.get('hit_rate')):>7} {_fmt(item.get('ev_pct')):>8}"
        )

    print()
    print("Rollout governance")
    for item in payload.rollout_governance[:limit]:
        blockers = ", ".join(item.get("blockers") or []) or "-"
        print(
            f"  {item['pattern'][:34]:<34} status={item['status']:<24} "
            f"sample={item['sample_size']:<5} ev={_fmt(item.get('ev_pct')):<8} "
            f"fp={_fmt(item.get('false_positive_rate')):<8} blockers={blockers}"
        )

    if payload.exit_patterns:
        print()
        print("Exit-pattern learning")
        print(f"  {'bucket':<56} {'n':>5} {'ev':>8} {'capture':>8} {'missed':>8}")
        for item in payload.exit_patterns[:limit]:
            print(
                f"  {item['bucket'][:56]:<56} {item['sample_size']:>5} "
                f"{_fmt(item.get('ev_pct')):>8} {_fmt(item.get('avg_capture_ratio')):>8} "
                f"{_fmt(item.get('avg_missed_upside_pct')):>8}"
            )

    print()
    print("[OK] symbol pattern diagnostics completed; no live authority changed")
    return True
