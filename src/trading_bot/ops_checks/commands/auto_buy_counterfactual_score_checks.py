"""Operator report for observe-only auto-buy scoring counterfactuals."""

from __future__ import annotations

from pathlib import Path

from trading_bot.persistence.repositories.auto_buy_counterfactual_score_repo import (
    load_auto_buy_rows_for_counterfactual_score,
)
from trading_bot.services.auto_buy_counterfactual_scoring_service import (
    ScoreReplayConfig,
    replay_counterfactual_scores,
)


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_auto_buy_counterfactual_score(
    target_date: str,
    *,
    base_dir: Path,
    samples: int = 10,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Auto-Buy Counterfactual Score Replay - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    rows = load_auto_buy_rows_for_counterfactual_score(target_date, db_path=db_path)
    payload = replay_counterfactual_scores(rows, config=ScoreReplayConfig())

    print(f"report_version                 : {payload['report_version']}")
    print(f"runtime_effect                 : {payload['runtime_effect']}")
    print(f"strong_threshold               : {payload['strong_threshold']}")
    print(f"watch_threshold                : {payload['watch_threshold']}")
    print(f"outcome_field                  : {payload['outcome_field']}")
    print(f"candidate_rows                 : {payload['row_count']}")
    print(f"scored_rows                    : {payload['scored_rows']}")
    print()
    print("Variant summary")
    print(
        "  variant                              rows changed unlocks prof loss "
        "hardblk avg_ret avg_delta max_delta"
    )
    for row in payload["variants"]:
        print(
            f"  {row['variant']:<36} "
            f"{row['rows']:>4} "
            f"{row['changed_rows']:>7} "
            f"{row['score_unlocks']:>7} "
            f"{row['profitable_unlocks']:>4} "
            f"{row['losing_unlocks']:>4} "
            f"{row['still_hard_blocked_unlocks']:>7} "
            f"{_fmt(row['avg_unlock_return_pct']):>7} "
            f"{_fmt(row['avg_score_delta']):>9} "
            f"{_fmt(row['max_score_delta']):>9}"
        )

    recommended = next(
        (
            row
            for row in payload["variants"]
            if row["variant"] == "tape_cap_-8_context_risk_collapsed"
        ),
        None,
    )
    if recommended and recommended["top_unlocks"]:
        print()
        print("Top score-threshold unlocks for tape_cap_-8_context_risk_collapsed")
        print(
            f"  {'time':<19} {'sym':<6} {'old':>7} {'new':>7} "
            f"{'delta':>7} {'ret':>8} {'mfe':>8} {'hard_block'}"
        )
        for item in recommended["top_unlocks"][:samples]:
            print(
                f"  {str(item.get('timestamp') or '-')[:19]:<19} "
                f"{str(item.get('symbol') or '-'):<6} "
                f"{_fmt(item.get('current_score')):>7} "
                f"{_fmt(item.get('variant_score')):>7} "
                f"{_fmt(item.get('score_delta')):>7} "
                f"{_fmt(item.get('outcome_pct')):>8} "
                f"{_fmt(item.get('forward_mfe_pct')):>8} "
                f"{str(item.get('hard_block_reason') or '-')[:80]}"
            )

    if not rows:
        print("[WARN] no auto-buy candidate rows found")
        return False
    if payload["scored_rows"] == 0:
        print("[WARN] no scored auto-buy rows found")
        return False

    print()
    print("[OK] counterfactual score replay completed; no live authority changed")
    return True
