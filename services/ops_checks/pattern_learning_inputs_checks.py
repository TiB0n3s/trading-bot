"""Operator report for pattern-learning input coverage."""

from __future__ import annotations

from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository
from services.pattern_learning_inputs_service import build_pattern_learning_inputs_payload


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _pct(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "-"
    return f"{100.0 * numerator / denominator:.1f}%"


def run_pattern_learning_inputs_report(
    target_date: str,
    *,
    base_dir: Path,
    limit: int = 20,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Pattern Learning Inputs - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = OpsCheckRepository(db_path)
    matched_rows = [dict(row) for row in repo.pattern_learning_matched_rows(target_date)]
    candidate_rows = [dict(row) for row in repo.pattern_learning_candidate_rows(target_date)]
    payload = build_pattern_learning_inputs_payload(matched_rows, candidate_rows)
    summary = payload.summary

    print(f"report_version                      : {summary['report_version']}")
    print(f"runtime_effect                      : {summary['runtime_effect']}")
    print(f"authority_ready                     : {summary['authority_ready']}")
    print(f"authority_note                      : {summary['authority_note']}")
    print()
    print("Executed trade learning inputs")
    print(
        f"  matched_trades                    : {summary['matched_trades']}"
    )
    print(
        "  matched_with_realized_outcome     : "
        f"{summary['matched_with_realized_outcome']} "
        f"({_pct(summary['matched_with_realized_outcome'], summary['matched_trades'])})"
    )
    print(
        "  matched_with_mfe                  : "
        f"{summary['matched_with_mfe']} "
        f"({_pct(summary['matched_with_mfe'], summary['matched_trades'])})"
    )
    print(
        "  matched_with_capture_ratio        : "
        f"{summary['matched_with_capture_ratio']} "
        f"({_pct(summary['matched_with_capture_ratio'], summary['matched_trades'])})"
    )
    print(
        "  matched_with_pattern_context      : "
        f"{summary['matched_with_pattern_context']} "
        f"({_pct(summary['matched_with_pattern_context'], summary['matched_trades'])})"
    )
    print(
        "  fully_integrated_pattern_outcomes : "
        f"{summary['fully_integrated_pattern_outcome_rows']} "
        f"({_pct(summary['fully_integrated_pattern_outcome_rows'], summary['matched_trades'])})"
    )

    print()
    print("Buy/sell quality labels")
    for label, count in summary["quality_counts"].items():
        print(f"  {label:<38} {count:>6}")

    print()
    print("Expectancy by dimension")
    for dimension, rows in payload.expectancy_by_dimension.items():
        print(f"  {dimension}")
        for row in rows[:limit]:
            print(
                f"    {str(row['bucket'])[:34]:<34} "
                f"n={row['rows']:<4} win={_fmt(row.get('win_rate')):<8} "
                f"ret={_fmt(row.get('avg_return_pct')):<8} "
                f"mfe={_fmt(row.get('avg_mfe_pct')):<8} "
                f"capture={_fmt(row.get('avg_capture_ratio'))}"
            )

    coverage = payload.candidate_label_coverage
    print()
    print("Candidate-universe learning inputs")
    print(f"  candidate_rows                    : {coverage['rows']}")
    print(
        "  rows_with_forward_outcome         : "
        f"{coverage['rows_with_forward_outcome']} "
        f"({_pct(coverage['rows_with_forward_outcome'], coverage['rows'])})"
    )
    print(
        "  rows_with_forward_mfe             : "
        f"{coverage['rows_with_forward_mfe']} "
        f"({_pct(coverage['rows_with_forward_mfe'], coverage['rows'])})"
    )
    print(f"  proven_good                       : {coverage['proven_good']}")
    print(f"  proven_bad                        : {coverage['proven_bad']}")

    if coverage["status_counts"]:
        print()
        print("Candidate status counts")
        for status, count in coverage["status_counts"].items():
            print(f"  {status:<30} {count:>6}")

    top_missed = coverage["top_missed_by_mfe"]
    if top_missed:
        print()
        print("Top non-taken candidates by forward MFE")
        print(
            f"  {'time':<19} {'sym':<6} {'status':<24} {'pattern':<28} "
            f"{'score':>8} {'mfe':>8} {'ret':>8} reason"
        )
        for item in top_missed[:limit]:
            print(
                f"  {str(item.get('candidate_ts') or '-')[:19]:<19} "
                f"{str(item.get('symbol') or '-'):<6} "
                f"{str(item.get('candidate_status') or '-'):<24} "
                f"{str(item.get('pattern') or '-')[:28]:<28} "
                f"{str(item.get('score') if item.get('score') is not None else '-'):>8} "
                f"{_fmt(item.get('forward_mfe_pct')):>8} "
                f"{_fmt(item.get('forward_return_pct')):>8} "
                f"{item.get('reason') or '-'}"
            )

    if payload.learning_actions:
        print()
        print("Learning actions")
        for action in payload.learning_actions:
            print(f"  - {action}")

    if not summary["matched_trades"] and not coverage["rows"]:
        print("[WARN] no matched trades or candidate rows available")
        return False

    print()
    print("[OK] pattern learning inputs summarized; no live authority changed")
    return True
