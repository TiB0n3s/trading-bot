#!/usr/bin/env python3
"""Train/evaluate the observe-only supervised prediction scaffold."""

from __future__ import annotations

import argparse
import json

from services.supervised_prediction_training_service import (
    fetch_training_rows,
    train_supervised_prediction_model,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol")
    parser.add_argument(
        "--horizon",
        default="15m",
        choices=("5m", "15m", "30m", "triple_barrier", "triple_barrier_label", "trend_scan", "trend_scan_label"),
    )
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--min-samples", type=int, default=40)
    parser.add_argument("--artifact-output", default="ml/models/supervised_entry_v1/model.joblib")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows = fetch_training_rows(symbol=args.symbol, limit=args.limit)
    result = train_supervised_prediction_model(
        rows=rows,
        horizon=args.horizon,
        min_samples=args.min_samples,
        artifact_path=args.artifact_output,
    ).to_dict()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("=== Supervised Prediction Training ===")
        print(f"provider       : {result['provider']}")
        print(f"trained        : {result['trained']}")
        print(f"sample_size    : {result['sample_size']}")
        print(f"accuracy       : {result['accuracy']}")
        print(f"positive_rate  : {result['baseline_positive_rate']}")
        print(f"reason         : {result['reason']}")
        print(f"artifact       : {result['artifact_path']}")
        missing = result["dependency_status"].get("missing") or []
        if missing:
            print(f"missing deps   : {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
