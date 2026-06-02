#!/usr/bin/env python3
"""Train the optional HMM regime model from SQLite feature snapshots."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from db import DB_PATH
from services.regime_switching_service import train_hmm_regime_model


def _closes(limit: int) -> list[float]:
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT last_price
            FROM feature_snapshots
            WHERE symbol = 'SPY'
              AND last_price IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [float(row["last_price"]) for row in reversed(rows)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--artifact-output", default="ml/models/regime_hmm_v1/model.joblib")
    args = parser.parse_args()
    result = train_hmm_regime_model(
        closes=_closes(args.limit),
        artifact_path=Path(args.artifact_output),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
