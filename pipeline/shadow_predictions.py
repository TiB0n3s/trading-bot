#!/usr/bin/env python3
"""Generate observe-only candidate model shadow predictions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from repositories.shadow_prediction_repo import ShadowPredictionRepository
from services.shadow_prediction_service import ShadowPredictionService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--db-path")
    parser.add_argument("--registry-path")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    kwargs = {}
    if args.registry_path:
        kwargs["registry_path"] = args.registry_path
    service = ShadowPredictionService(
        repository=ShadowPredictionRepository(args.db_path),
        **kwargs,
    )
    payload = service.run(market_date=args.date, limit=args.limit)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
