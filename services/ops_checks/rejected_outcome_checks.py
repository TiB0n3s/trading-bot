from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable

import pytz

from repositories.ops_check_repo import OpsCheckRepository


def _int_row_value(row, key: str) -> int:
    if row is None:
        return 0
    return int(row[key] or 0)


def _parse_ts(value, *, local_tz, et):
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = local_tz.localize(dt)
    return dt.astimezone(et)


def _validate_partial_rows(rows, *, local_tz, et) -> tuple[int, int]:
    bad_near_close = 0
    bad_partial_60m = 0

    for row in rows:
        try:
            signal_dt = _parse_ts(row["timestamp"], local_tz=local_tz, et=et)
            close_dt = et.localize(datetime.combine(signal_dt.date(), time(16, 0)))
            near_close = signal_dt + timedelta(minutes=60) > close_dt
            partial_reason = row["partial_reason"]
            if partial_reason == "near_close_no_60m_window" and not near_close:
                bad_near_close += 1
            if partial_reason != "near_close_no_60m_window" and near_close:
                bad_near_close += 1
            if partial_reason == "near_close_no_60m_window" and row["return_60m"] is not None:
                bad_partial_60m += 1
        except Exception:
            bad_near_close += 1

    return bad_near_close, bad_partial_60m


def run_rejected_outcomes_health(
    target_date: str,
    *,
    base_dir: Path,
    env_get: Callable[[str, str], str] | None = None,
) -> bool:
    db_path = base_dir / "trades.db"
    repo = OpsCheckRepository(db_path)
    env_get = env_get or (lambda _name, default: default)
    local_tz = pytz.timezone(env_get("TRADING_BOT_LOCAL_TZ", "America/Chicago"))
    et = pytz.timezone("America/New_York")

    print()
    print("=" * 72)
    print(f"  Rejected Signal Outcomes - {target_date}")
    print("=" * 72)

    if not repo.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    if not repo.table_exists("rejected_signal_outcomes"):
        print("[FAIL] rejected_signal_outcomes table is missing")
        return False

    rejected = repo.rejected_outcome_rejected_counts(target_date)
    outcomes = repo.rejected_outcome_status_counts(target_date)

    covered = _int_row_value(outcomes, "n")
    rejected_total = _int_row_value(rejected, "n")
    missing = rejected_total - covered
    print(f"  rejected_rows          {rejected_total:>8}")
    print(f"  rejected_buy_rows      {_int_row_value(rejected, 'buy_n'):>8}")
    print(f"  rejected_sell_rows     {_int_row_value(rejected, 'sell_n'):>8}")
    print(f"  outcome_rows           {covered:>8}")
    print(f"  missing_outcomes       {missing:>8}")
    print(f"  labeled                {_int_row_value(outcomes, 'labeled'):>8}")
    print(f"  partial                {_int_row_value(outcomes, 'partial'):>8}")
    print(f"  pending                {_int_row_value(outcomes, 'pending'):>8}")
    print(f"  no_bars                {_int_row_value(outcomes, 'no_bars'):>8}")
    print(f"  error                  {_int_row_value(outcomes, 'error'):>8}")

    cols = repo.table_columns("rejected_signal_outcomes")
    if "partial_reason" in cols:
        print()
        print("Partial reasons")
        rows = repo.rejected_outcome_partial_reason_rows(target_date)
        if rows:
            for row in rows:
                print(f"  {row['partial_reason']:<30} {row['n']:>6}")
        else:
            print("  none")
    elif _int_row_value(outcomes, "partial"):
        print()
        print("[INFO] partial rows may be near-close structural partials or pending forward bars")

    print()
    print("Horizon completeness")
    horizon_rows = repo.rejected_outcome_horizon_rows(target_date)
    if horizon_rows:
        for row in horizon_rows:
            print(
                f"  {row['label_status']:<10} n={row['n']:>5} "
                f"5m={row['has_5m']:>5} 15m={row['has_15m']:>5} "
                f"30m={row['has_30m']:>5} 60m={row['has_60m']:>5} "
                f"eod={row['has_eod']:>5} mfe={row['has_mfe']:>5} mae={row['has_mae']:>5}"
            )
    else:
        print("  none")

    print()
    print("By action/status")
    rows = repo.rejected_outcome_action_status_rows(target_date)
    if rows:
        for row in rows:
            avg15 = row["avg_return_15m"]
            avg60 = row["avg_return_60m"]
            avgeod = row["avg_return_eod"]
            avg15_s = f"{avg15:.3f}%" if avg15 is not None else "-"
            avg60_s = f"{avg60:.3f}%" if avg60 is not None else "-"
            avgeod_s = f"{avgeod:.3f}%" if avgeod is not None else "-"
            print(
                f"  {row['action']:<5} {row['label_status']:<10} "
                f"{row['n']:>6} avg15={avg15_s:>9} avg60={avg60_s:>9} avgeod={avgeod_s:>9}"
            )
    else:
        print("  none")

    invalid_labeled = repo.rejected_outcome_invalid_labeled_count(target_date)
    bad_excursions = repo.rejected_outcome_bad_excursion_count(target_date)
    partial_rows = repo.rejected_outcome_partial_rows(target_date)
    bad_near_close, bad_partial_60m = _validate_partial_rows(
        partial_rows,
        local_tz=local_tz,
        et=et,
    )

    print()
    print("Validation checks")
    print(f"  labeled_missing_horizons     {int(invalid_labeled or 0):>6}")
    print(f"  bad_action_adjusted_mfe_mae  {int(bad_excursions or 0):>6}")
    print(f"  bad_near_close_partials      {bad_near_close:>6}")
    print(f"  near_close_with_60m_return    {bad_partial_60m:>6}")

    print()
    print("Top rejection categories with outcomes")
    rows = repo.rejected_outcome_category_rows(target_date)
    if rows:
        for row in rows:
            avg15 = row["avg_return_15m"]
            mfe = row["avg_mfe_60m"]
            avg15_s = f"{avg15:.3f}%" if avg15 is not None else "-"
            mfe_s = f"{mfe:.3f}%" if mfe is not None else "-"
            print(f"  {row['category']:<30} {row['n']:>6} avg15={avg15_s:>9} mfe60={mfe_s:>9}")
    else:
        print("  none")

    failures = []
    if missing > 0:
        failures.append("missing rejected outcome rows")
    if _int_row_value(outcomes, "error") > 0:
        failures.append("error rows present")
    if int(invalid_labeled or 0) > 0:
        failures.append("labeled rows missing required horizons")
    if int(bad_excursions or 0) > 0:
        failures.append("action-adjusted MFE/MAE sign check failed")
    if bad_near_close > 0 or bad_partial_60m > 0:
        failures.append("near-close partial attribution failed")

    if failures:
        print()
        print("[WARN] rejected outcome validation needs follow-up:")
        for failure in failures:
            print(f"  - {failure}")
        return False

    print()
    print("[OK] rejected outcome coverage completed")
    return True
