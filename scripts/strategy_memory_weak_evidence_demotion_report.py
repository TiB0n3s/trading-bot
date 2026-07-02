#!/usr/bin/env python3
"""No-write strategy-memory weak-evidence demotion report.

Examples:
  python3 scripts/strategy_memory_weak_evidence_demotion_report.py \
    --start-date 2026-06-21 --end-date 2026-07-01
  python3 scripts/strategy_memory_weak_evidence_demotion_report.py \
    --start-date 2026-06-21 --end-date 2026-07-01 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
for path in (BASE_DIR / "scripts", BASE_DIR / "src", BASE_DIR):
    path_s = str(path)
    if path_s not in sys.path:
        sys.path.insert(0, path_s)

from trading_bot.persistence.repositories.auto_buy_counterfactual_score_repo import (  # noqa: E402
    load_auto_buy_rows_for_counterfactual_score,
    load_auto_buy_rows_for_counterfactual_score_range,
)
from trading_bot.services.strategy_memory_weak_evidence_demotion_service import (  # noqa: E402
    StrategyMemoryDemotionConfig,
    replay_strategy_memory_weak_evidence_demotion,
)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _dates_between(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("--end-date must be on or after --start-date")
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _load_rows(start: date, end: date, db_path: Path, limit: int | None) -> tuple[list[dict], list[dict]]:
    if limit is None:
        rows = load_auto_buy_rows_for_counterfactual_score_range(
            start.isoformat(),
            end.isoformat(),
            db_path=db_path,
        )
        counts = {day.isoformat(): 0 for day in _dates_between(start, end)}
        for row in rows:
            timestamp = str(row.get("timestamp") or "")
            day = timestamp[:10]
            if day in counts:
                counts[day] += 1
        return rows, [{"date": day, "rows": count} for day, count in counts.items()]

    rows: list[dict] = []
    coverage: list[dict] = []
    for day in _dates_between(start, end):
        day_rows = load_auto_buy_rows_for_counterfactual_score(
            day.isoformat(),
            db_path=db_path,
            limit=limit,
        )
        rows.extend(day_rows)
        coverage.append({"date": day.isoformat(), "rows": len(day_rows)})
    return rows, coverage


def _print_group(title: str, rows: list[dict]) -> None:
    print(title)
    if not rows:
        print("  -")
        return
    print("  group                    rows known avg_ret med_ret prof pos neg below_ev")
    for row in rows:
        print(
            f"  {row['group']:<24} "
            f"{row['rows']:>4} "
            f"{row['known_outcome_rows']:>5} "
            f"{_fmt(row['avg_return_pct']):>7} "
            f"{_fmt(row['median_return_pct']):>7} "
            f"{row['profitable_rows']:>4} "
            f"{row['positive_rows']:>3} "
            f"{row['negative_rows']:>3} "
            f"{row['below_ev_bar_rows']:>8}"
        )


def _print_examples(title: str, rows: list[dict]) -> None:
    print(title)
    if not rows:
        print("  -")
        return
    print("  ts                         sym  score band                  ret60 hard_reason")
    for row in rows[:8]:
        hard = str(row.get("hard_block_reason") or "")
        if len(hard) > 52:
            hard = f"{hard[:49]}..."
        print(
            f"  {str(row.get('timestamp') or '-')[:25]:<25} "
            f"{str(row.get('symbol') or '-'):<4} "
            f"{_fmt(row.get('score')):>5} "
            f"{row.get('score_band', '-'):<21} "
            f"{_fmt(row.get('outcome_pct')):>6} "
            f"{hard}"
        )


def _render(payload: dict) -> bool:
    print("=" * 94)
    print("  Strategy-Memory Weak-Evidence Demotion Replay")
    print("=" * 94)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"date_window             : {payload['start_date']}..{payload['end_date']}")
    print(f"rows                    : {payload['row_count']}")
    print(f"scored_rows             : {payload['scored_rows']}")
    print(f"near_threshold_min      : {payload['near_threshold_min']}")
    print(f"watch_threshold         : {payload['watch_threshold']}")
    print(f"score_cap               : {payload['score_cap']}")
    print(f"outcome_field           : {payload['outcome_field']}")
    print(f"ev_profit_threshold_pct : {payload['profitable_return_threshold_pct']}")
    print()
    print("date coverage")
    for row in payload["date_coverage"]:
        print(f"  {row['date']}: {row['rows']}")
    print()
    print(f"eligible_rows                         : {payload['eligible_rows']}")
    print(f"would_watch_rows                      : {payload['would_watch_rows']}")
    print(f"remaining_context_block_rows          : {payload['remaining_context_block_rows']}")
    print(
        "ineligible_other_setup_tape_ml_chase : "
        f"{payload['ineligible_other_setup_tape_ml_chase_rows']}"
    )
    watch = payload["would_watch_summary"]
    baseline = payload["baseline_no_hard_block_summary"]
    print()
    print(
        "would_watch summary      "
        f"known={watch['known_outcome_rows']} "
        f"avg={_fmt(watch['avg_return_pct'])} "
        f"med={_fmt(watch['median_return_pct'])} "
        f"prof={watch['profitable_rows']} "
        f"pos={watch['positive_rows']} "
        f"neg={watch['negative_rows']} "
        f"below_ev={watch['below_ev_bar_rows']}"
    )
    print(
        "no-hard-block baseline   "
        f"known={baseline['known_outcome_rows']} "
        f"avg={_fmt(baseline['avg_return_pct'])} "
        f"med={_fmt(baseline['median_return_pct'])} "
        f"prof={baseline['profitable_rows']} "
        f"pos={baseline['positive_rows']} "
        f"neg={baseline['negative_rows']} "
        f"below_ev={baseline['below_ev_bar_rows']}"
    )
    print(f"ev_delta_vs_baseline_pct : {_fmt(payload['ev_delta_vs_no_hard_block_pct'])}")
    print(f"passes_net_ev_guard      : {payload['passes_net_ev_guard']}")
    print()
    _print_group("would_watch by weak reason", payload["would_watch_by_reason"])
    print()
    _print_group("would_watch by score band", payload["would_watch_by_score_band"])
    print()
    _print_group("eligible by weak reason", payload["eligible_by_reason"])
    print()
    _print_examples("top profitable would-watch rows", payload["top_profitable_would_watch"])
    print()
    _print_examples("top losing would-watch rows", payload["top_losing_would_watch"])
    print()
    print("[OK] demotion replay completed; no live authority changed")
    return payload["scored_rows"] > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default=date.today().isoformat())
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--db-path", default=str(BASE_DIR / "trades.db"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--strong-threshold", type=float, default=13.0)
    parser.add_argument("--watch-threshold", type=float, default=7.0)
    parser.add_argument("--near-threshold-min", type=float, default=10.0)
    parser.add_argument("--outcome-field", default="return_60m")
    parser.add_argument("--profitable-return-threshold-pct", type=float, default=0.25)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    start = _parse_date(args.start_date)
    end = _parse_date(args.end_date)
    rows, coverage = _load_rows(start, end, Path(args.db_path), args.limit)
    payload = replay_strategy_memory_weak_evidence_demotion(
        rows,
        config=StrategyMemoryDemotionConfig(
            strong_threshold=args.strong_threshold,
            watch_threshold=args.watch_threshold,
            near_threshold_min=args.near_threshold_min,
            outcome_field=args.outcome_field,
            profitable_return_threshold_pct=args.profitable_return_threshold_pct,
        ),
    )
    payload["start_date"] = start.isoformat()
    payload["end_date"] = end.isoformat()
    payload["date_coverage"] = coverage
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0 if payload["scored_rows"] > 0 else 1
    return 0 if _render(payload) else 1


if __name__ == "__main__":
    raise SystemExit(main())
