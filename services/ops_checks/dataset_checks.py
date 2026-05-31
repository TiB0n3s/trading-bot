from __future__ import annotations

from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository


CORE_TABLES = [
    "trades",
    "matched_trades",
    "feature_snapshots",
    "labeled_setups",
    "daily_symbol_context",
    "daily_symbol_events",
    "daily_symbol_predictions",
    "strong_day_participation",
    "bot_events",
]

DATED_TABLES = [
    ("daily_symbol_context", "market_date"),
    ("daily_symbol_events", "market_date"),
    ("daily_symbol_predictions", "market_date"),
    ("strong_day_participation", "market_date"),
]


def _count_label(count: int | None) -> str:
    return "missing" if count is None else str(count)


def run_dataset_health(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"
    repo = OpsCheckRepository(db_path)

    print()
    print("=" * 72)
    print(f"  Dataset Health - {target_date}")
    print("=" * 72)

    if not repo.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    ok = True

    print("Core table counts")
    for table in CORE_TABLES:
        n = repo.table_count(table)
        print(f"  {table:<26} {_count_label(n):>8}")

    print()
    print(f"Target-date rows ({target_date})")
    target_counts = {}
    for table, col in DATED_TABLES:
        n = repo.table_count(table, f"{col} = ?", (target_date,))
        target_counts[table] = n
        print(f"  {table:<26} {_count_label(n):>8}")

    print()
    print("Recent intelligence dates")
    for table in (
        "daily_symbol_context",
        "daily_symbol_events",
        "daily_symbol_predictions",
        "strong_day_participation",
    ):
        if not repo.table_exists(table):
            print(f"  {table}: missing")
            continue

        rows = repo.recent_market_date_rows(table)
        if not rows:
            print(f"  {table}: none")
            continue

        print(f"  {table}:")
        for r in rows:
            print(f"    {r['market_date']:<12} {r['n']:>5}")

    print()
    print("Feature/label coverage")
    snapshots = repo.table_count("feature_snapshots") or 0
    labels = repo.table_count("labeled_setups") or 0
    matched = repo.table_count("matched_trades") or 0
    trades = repo.table_count("trades") or 0

    label_coverage = (labels / snapshots * 100.0) if snapshots else 0.0
    match_coverage = (matched / trades * 100.0) if trades else 0.0

    print(f"  feature_snapshots       {snapshots:>8}")
    print(f"  labeled_setups          {labels:>8}")
    print(f"  label_coverage_pct      {label_coverage:>7.1f}%")
    print(f"  trades                  {trades:>8}")
    print(f"  matched_trades          {matched:>8}")
    print(f"  match_coverage_pct      {match_coverage:>7.1f}%")

    if snapshots == 0:
        print("[WARN] no feature_snapshots yet; intraday ML dataset is not collecting samples")
    if labels == 0:
        print("[WARN] no labeled_setups yet; no supervised setup dataset is available")
    if matched == 0:
        print("[WARN] no matched_trades yet; strategy learning has no closed-trade outcomes")

    print()
    print("Prediction confidence")
    if repo.table_exists("daily_symbol_predictions"):
        rows = repo.prediction_confidence_rows(target_date)
        if rows:
            for r in rows:
                print(f"  {r['confidence']:<10} {r['n']}")
        else:
            print("  none")
    else:
        print("  daily_symbol_predictions table missing")

    context_count = target_counts.get("daily_symbol_context") or 0
    prediction_count = target_counts.get("daily_symbol_predictions") or 0

    freshness = None
    if all(
        repo.table_exists(table)
        for table in ("daily_symbol_events", "daily_symbol_context", "daily_symbol_predictions")
    ):
        freshness = repo.intelligence_freshness_row(target_date)

        print()
        print("Intelligence freshness")
        print(f"  latest event      : {freshness['latest_event_at'] or '-'}")
        print(f"  latest context    : {freshness['latest_context_at'] or '-'}")
        print(f"  latest prediction : {freshness['latest_prediction_at'] or '-'}")

    if context_count <= 0:
        print("[FAIL] no target-date daily_symbol_context rows found")
        ok = False
    if prediction_count not in (0, context_count):
        print("[WARN] target-date prediction count does not match context count")
    if freshness:
        if (
            freshness["latest_event_at"]
            and freshness["latest_context_at"]
            and freshness["latest_event_at"] > freshness["latest_context_at"]
        ):
            print("[WARN] latest event row is newer than daily_symbol_context")
        if (
            freshness["latest_context_at"]
            and freshness["latest_prediction_at"]
            and freshness["latest_context_at"] > freshness["latest_prediction_at"]
        ):
            print("[WARN] latest context row is newer than daily_symbol_predictions")

    print()
    if ok:
        print("[OK] dataset health check completed")
    else:
        print("[FAIL] dataset health check found issues")

    return ok
