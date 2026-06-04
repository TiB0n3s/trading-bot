"""Operator report for missed-buy forward-outcome review."""

from __future__ import annotations

from pathlib import Path

from repositories.candidate_universe_repo import CandidateUniverseRepository
from services.missed_buy_review_service import build_missed_buy_review_payload


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _pct(value) -> str:
    if value is None:
        return "-"
    return f"{100.0 * float(value):.1f}%"


def run_missed_buy_review(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    samples: int = 20,
    min_mfe_pct: float = 0.8,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Missed Buy Review - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = CandidateUniverseRepository(db_path)
    rows = [dict(row) for row in repo.rows_for_date(target_date, symbol=symbol)]
    payload = build_missed_buy_review_payload(rows, min_mfe_pct=min_mfe_pct)
    summary = payload.summary

    print(f"report_version                      : {summary['report_version']}")
    print(f"runtime_effect                      : {summary['runtime_effect']}")
    print(f"authority_ready                     : {summary['authority_ready']}")
    print(f"authority_note                      : {summary['authority_note']}")
    if symbol:
        print(f"symbol                              : {symbol.upper()}")
    print()
    print("Coverage")
    print(f"  candidate_rows                    : {summary['candidate_rows']}")
    print(f"  rows_with_forward_outcome         : {summary['rows_with_forward_outcome']} ({_pct(summary['forward_outcome_coverage_rate'])})")
    print(f"  non_taken_with_forward_outcome    : {summary['non_taken_with_forward_outcome']}")
    print(f"  min_mfe_pct                       : {_fmt(summary['min_mfe_pct'])}")
    print()
    print("Missed-buy outcome labels")
    print(f"  missed_good_candidates            : {summary['missed_good_candidates']}")
    print(f"  high_quality_missed_candidates    : {summary['high_quality_missed_candidates']}")
    print(f"  correctly_avoided_or_bad_candidates: {summary['correctly_avoided_or_bad_candidates']}")
    print(f"  missed_good_rate                  : {_pct(summary['missed_good_rate_of_non_taken_with_forward'])}")
    print(f"  soft_block_missed_good_candidates : {summary['soft_block_missed_good_candidates']}")
    print(f"  paper_promotion_review_candidates : {summary['paper_promotion_review_candidates']}")
    print(f"  avg_missed_good_mfe_pct           : {_fmt(summary['avg_missed_good_mfe_pct'])}")
    print(f"  avg_missed_good_return_pct        : {_fmt(summary['avg_missed_good_return_pct'])}")

    if summary.get("quality_counts"):
        print()
        print("Missed-buy quality counts")
        for label, count in summary["quality_counts"].items():
            print(f"  {label:<38} {count:>6}")

    if payload.reason_token_counts:
        print()
        print("Top rejection / watch reasons among missed-good rows")
        for row in payload.reason_token_counts[:samples]:
            print(f"  {row['key'][:58]:<58} {row['count']:>6}")

    if payload.symbol_counts:
        print()
        print("Missed-good rows by symbol")
        for row in payload.symbol_counts[:samples]:
            print(f"  {row['key']:<8} {row['count']:>6}")

    if payload.pattern_counts:
        print()
        print("Missed-good rows by pattern/setup")
        for row in payload.pattern_counts[:samples]:
            print(f"  {row['key'][:58]:<58} {row['count']:>6}")

    if payload.top_missed:
        print()
        print("Top non-taken BUY candidates by forward MFE")
        print(
            f"  {'time':<19} {'sym':<6} {'status':<24} {'pattern':<28} "
            f"{'score':>8} {'mfe':>8} {'ret':>8} {'mae':>8} reasons"
        )
        for item in payload.top_missed[:samples]:
            reasons = ",".join(item.get("reason_tokens") or []) or str(item.get("reason") or "-")
            promotion_marker = " paper_promotion_review" if item.get("paper_promotion_review_candidate") else ""
            print(
                f"  {str(item.get('candidate_ts') or '-')[:19]:<19} "
                f"{str(item.get('symbol') or '-'):<6} "
                f"{str(item.get('candidate_status') or '-'):<24} "
                f"{str(item.get('pattern') or '-')[:28]:<28} "
                f"{_fmt(item.get('score')):>8} "
                f"{_fmt(item.get('forward_mfe_pct')):>8} "
                f"{_fmt(item.get('forward_return_pct')):>8} "
                f"{_fmt(item.get('forward_mae_pct')):>8} "
                f"{reasons[:120]}{promotion_marker}"
            )

    if payload.learning_actions:
        print()
        print("Learning actions")
        for action in payload.learning_actions:
            print(f"  - {action}")

    if not rows:
        print("[WARN] no candidate-universe rows found")
        return False
    if summary["rows_with_forward_outcome"] == 0:
        print("[WARN] no candidate forward outcomes found; run candidate-outcome-backfill first")
        return False

    print()
    print("[OK] missed-buy review summarized; no live authority changed")
    return True
