#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from repositories.live_features_repo import LiveFeaturesRepository
from setup_engine import classify_feature_snapshot as classify_setup


def load_rows_missing_setup(limit: int = 5000) -> list[Any]:
    return LiveFeaturesRepository().snapshots_missing_setup_rows(limit)


def update_setup_fields(row: Any) -> None:
    snapshot = dict(row)
    setup = classify_setup(snapshot)

    LiveFeaturesRepository().update_snapshot_setup_fields(
        snapshot_id=row["id"],
        setup_label=setup.setup_label,
        setup_recommendation=setup.recommendation,
        setup_score=setup.setup_score,
        setup_confidence=setup.confidence,
        setup_key=setup.setup_key,
    )


def main() -> int:
    rows = load_rows_missing_setup(limit=100000)
    if not rows:
        print("No feature_snapshots rows need setup backfill.")
        return 0

    updated = 0
    failed = 0

    for row in rows:
        try:
            update_setup_fields(row)
            updated += 1
        except Exception as e:
            failed += 1
            print(f"Failed snapshot id={row['id']} symbol={row['symbol']}: {e}")

    print(f"Setup backfill complete: updated={updated}, failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
