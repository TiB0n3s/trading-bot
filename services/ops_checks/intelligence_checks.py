from __future__ import annotations

from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository


def run_intelligence_summary(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"
    repo = OpsCheckRepository(db_path)

    print()
    print("=" * 72)
    print(f"  Intelligence Summary - {target_date}")
    print("=" * 72)

    if not repo.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    ok = True

    context_count = repo.intelligence_row_count("daily_symbol_context", target_date)
    event_count = repo.intelligence_row_count("daily_symbol_events", target_date)
    prediction_count = repo.intelligence_row_count("daily_symbol_predictions", target_date)
    strong_day_count = 0
    if repo.table_exists("strong_day_participation"):
        strong_day_count = repo.intelligence_row_count("strong_day_participation", target_date)

    print(f"context rows    : {context_count}")
    print(f"event rows      : {event_count}")
    print(f"prediction rows : {prediction_count}")
    print(f"strong-day rows : {strong_day_count}")

    freshness = repo.intelligence_freshness_row(target_date)

    print()
    print("Freshness")
    print(f"  latest event      : {freshness['latest_event_at'] or '-'}")
    print(f"  latest context    : {freshness['latest_context_at'] or '-'}")
    print(f"  latest prediction : {freshness['latest_prediction_at'] or '-'}")

    print()
    print("Bias counts")
    rows = repo.context_bias_rows(target_date)
    if rows:
        for r in rows:
            print(f"  {r['bias']:<10} {r['n']}")
    else:
        print("  none")

    print()
    print("Prediction confidence")
    rows = repo.prediction_confidence_rows(target_date)
    if rows:
        for r in rows:
            print(f"  {r['confidence']:<10} {r['n']}")
    else:
        print("  none")

    print()
    print("Avoid rows")
    rows = repo.context_avoid_rows(target_date)
    if rows:
        for r in rows:
            print(
                f"  {r['symbol']:<6} "
                f"risk={r['risk_level']} "
                f"entry={r['entry_quality']} "
                f"avoid_type={r['avoid_type']} "
                f"reason={r['reason']}"
            )
    else:
        print("  none")

    print()
    print("Latest context updates")
    rows = repo.latest_context_update_rows(target_date)
    if rows:
        for r in rows:
            print(f"  {r['symbol']:<6} {r['updated_at']}")
    else:
        print("  none")

    if context_count <= 0:
        print("[FAIL] no daily_symbol_context rows found")
        ok = False

    if prediction_count not in (0, context_count):
        print("[WARN] prediction row count does not match context row count")

    if (
        freshness["latest_event_at"]
        and freshness["latest_context_at"]
        and freshness["latest_event_at"] > freshness["latest_context_at"]
    ):
        print("[WARN] latest event row is newer than daily_symbol_context; run apply_event_scores.py")

    if (
        freshness["latest_context_at"]
        and freshness["latest_prediction_at"]
        and freshness["latest_context_at"] > freshness["latest_prediction_at"]
    ):
        print("[WARN] latest context row is newer than daily_symbol_predictions; run predict_symbol_outcomes.py")

    if ok:
        print()
        print("[OK] intelligence summary completed")

    return ok
