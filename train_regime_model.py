#!/usr/bin/env python3
"""Train the optional HMM regime model from SQLite feature snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from repositories.regime_repo import fetch_spy_closes
from services.regime_switching_service import train_hmm_regime_model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--artifact-output", default="ml/models/regime_hmm_v1/model.joblib")
    args = parser.parse_args()
    result = train_hmm_regime_model(
        closes=fetch_spy_closes(args.limit),
        artifact_path=Path(args.artifact_output),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
