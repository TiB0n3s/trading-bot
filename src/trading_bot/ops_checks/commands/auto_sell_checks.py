from __future__ import annotations

from pathlib import Path

from repositories import auto_sell_repo


def _int_row_value(row, key: str) -> int:
    if row is None:
        return 0
    return int(row[key] or 0)


def _fmt(value) -> str:
    return f"{float(value):.2f}" if value is not None else "-"


def run_auto_sell_health(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"

    print()
    print("=" * 72)
    print(f"  Auto-Sell Candidates - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    if not auto_sell_repo.table_exists("auto_sell_candidates", db_path=db_path):
        print(
            "[WARN] auto_sell_candidates table is missing; run position_momentum_monitor.py first"
        )
        return False

    print("Action/severity distribution")
    rows = auto_sell_repo.candidate_action_rows(target_date, db_path=db_path)
    if rows:
        for row in rows:
            print(
                f"  {str(row['action'] or '-'):<18} {str(row['severity'] or '-'):<24} "
                f"{row['n']:>6} submitted={_int_row_value(row, 'submitted'):>4} "
                f"avg_plpc={_fmt(row['avg_plpc']):>7} "
                f"avg_ml={_fmt(row['avg_ml_confidence']):>7}"
            )
    else:
        print("  none")

    print()
    print("Layered ML influence")
    rows = auto_sell_repo.layered_ml_summary(target_date, db_path=db_path)
    if rows:
        for row in rows:
            print(
                f"  {str(row['instruction'] or '-'):<24} {row['n']:>6} "
                f"sell_candidates={_int_row_value(row, 'sell_candidates'):>4} "
                f"avg_master={_fmt(row['avg_master']):>7} "
                f"avg_ensemble={_fmt(row['avg_ensemble']):>7}"
            )
    else:
        print("  none")

    print()
    print("Top auto-sell candidates")
    rows = auto_sell_repo.top_candidate_rows(target_date, db_path=db_path)
    if rows:
        for row in rows:
            print(
                f"  {row['timestamp']} {row['symbol']:<6} "
                f"{row['action']:<15} {row['severity']:<24} "
                f"plpc={_fmt(row['unrealized_plpc']):>7} "
                f"pressure={_fmt(row['sell_pressure_score']):>7} "
                f"ml={_fmt(row['layered_ml_master_confidence_score']):>7} "
                f"order={row['order_id'] or '-'}"
            )
    else:
        print("  none")

    print()
    print("Auto-sell audit snapshots")
    if auto_sell_repo.table_exists("auto_sell_decision_snapshots", db_path=db_path):
        row = auto_sell_repo.decision_snapshot_summary(target_date, db_path=db_path)
        print(f"  snapshots             {_int_row_value(row, 'n'):>8}")
        print(f"  submitted             {_int_row_value(row, 'submitted'):>8}")
        print(f"  layered_rows          {_int_row_value(row, 'layered_rows'):>8}")
    else:
        print("  [WARN] auto_sell_decision_snapshots table missing")

    print()
    print("[OK] auto-sell candidate check completed")
    return True
