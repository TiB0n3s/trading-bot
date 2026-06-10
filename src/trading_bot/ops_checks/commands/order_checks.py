from __future__ import annotations

from pathlib import Path

from repositories import fill_repo


def _int_row_value(row, key: str) -> int:
    if row is None:
        return 0
    return int(row[key] or 0)


def run_order_health(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"

    print()
    print("=" * 72)
    print(f"  Order Health - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    ok = True

    if not fill_repo.table_exists("trades", db_path=db_path):
        print("[FAIL] trades table is missing")
        return False

    print("Trade order fields")
    rows = fill_repo.trade_order_field_summary(target_date, db_path=db_path)
    approved_rows = _int_row_value(rows, "approved_rows")
    missing_order_id = _int_row_value(rows, "missing_order_id")
    print(f"  approved_rows          {approved_rows:>8}")
    print(f"  with_order_id          {_int_row_value(rows, 'with_order_id'):>8}")
    print(f"  missing_order_id       {missing_order_id:>8}")
    print(f"  missing_order_status   {_int_row_value(rows, 'missing_order_status'):>8}")
    if missing_order_id:
        print("[WARN] approved rows without order_id found")

    print()
    print("Order status distribution")
    rows = fill_repo.trade_order_status_rows(target_date, db_path=db_path)
    if rows:
        for r in rows:
            print(f"  {r['order_status']:<22} {r['n']}")
    else:
        print("  none")

    print()
    print("Recent approved rows")
    rows = fill_repo.recent_approved_order_rows(target_date, db_path=db_path)
    if rows:
        for r in rows:
            print(
                f"  {r['timestamp']} {r['symbol'] or '-':<6} {r['action'] or '-':<4} "
                f"status={r['order_status'] or '-'} order_id={r['order_id'] or '-'} "
                f"qty={r['qty']} fill={r['fill_price']} size={r['position_size_pct']} "
                f"stop={r['stop_loss_pct']} target={r['take_profit_pct']}"
            )
    else:
        print("  none")

    print()
    print("Fill events")
    if fill_repo.table_exists("fill_events", db_path=db_path):
        rows = fill_repo.fill_event_summary_rows(target_date, db_path=db_path)
        if rows:
            for r in rows:
                print(f"  event={r['event']:<18} status={r['status']:<18} {r['n']}")
        else:
            print("  none")
    else:
        print("  fill_events table missing")

    print()
    print("External Alpaca orders")
    if fill_repo.table_exists("external_alpaca_orders", db_path=db_path):
        rows = fill_repo.external_alpaca_order_summary_rows(target_date, db_path=db_path)
        if rows:
            for r in rows:
                print(f"  status={r['status']:<18} side={r['side']:<8} {r['n']}")
        else:
            print("  none")
    else:
        print("  external_alpaca_orders table missing")

    print()
    print("Execution ledger reconciliation")
    bridge_gap_rows = fill_repo.bridge_routed_without_trade_rows(target_date, db_path=db_path)
    filled_missing_rows = fill_repo.filled_trade_rows_missing_fill_fields(
        target_date,
        db_path=db_path,
    )
    sell_without_buy_rows = fill_repo.sell_rows_without_prior_buy_rows(
        target_date,
        db_path=db_path,
    )
    print(f"  bridge_routed_without_trade_rows {len(bridge_gap_rows):>8}")
    print(f"  filled_rows_missing_fill_fields  {len(filled_missing_rows):>8}")
    print(f"  sells_without_prior_local_buy     {len(sell_without_buy_rows):>8}")
    if bridge_gap_rows:
        ok = False
        print("  Bridge ledger gaps")
        for r in bridge_gap_rows[:10]:
            print(
                f"    snapshot_id={r['id']} {r['candidate_timestamp']} "
                f"{r['symbol']} order_id={r['routed_order_id'] or r['order_id']} "
                f"status={r['order_status'] or '-'}"
            )
    if filled_missing_rows:
        ok = False
        print("  Filled rows missing qty/fill_price")
        for r in filled_missing_rows[:10]:
            print(
                f"    trade_id={r['id']} {r['timestamp']} {r['symbol']} {r['action']} "
                f"order_id={r['order_id'] or '-'} status={r['order_status'] or '-'} "
                f"qty={r['qty']} fill={r['fill_price']}"
            )
    if sell_without_buy_rows:
        print("  Sells without prior local buy basis")
        for r in sell_without_buy_rows[:10]:
            print(
                f"    trade_id={r['id']} {r['timestamp']} {r['symbol']} "
                f"order_id={r['order_id'] or '-'} qty={r['qty']} fill={r['fill_price']}"
            )

    if approved_rows and missing_order_id:
        ok = False

    print()
    if ok:
        print("[OK] order health completed")
    else:
        print("[WARN] order health found issues")
    return ok
