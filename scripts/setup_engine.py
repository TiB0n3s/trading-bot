#!/usr/bin/env python3
"""Compatibility wrapper and CLI for setup-engine classification."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from services.setup_engine_service import (
    SetupEngineService,
    build_default_setup_engine_service,
    classify_feature_snapshot,
)

_DEFAULT_SERVICE: SetupEngineService | None = None


def _service() -> SetupEngineService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = build_default_setup_engine_service()
    return _DEFAULT_SERVICE


def load_snapshot_by_id(snapshot_id: int) -> dict | None:
    return _service().load_snapshot_by_id(snapshot_id)


def load_latest_snapshot_for_symbol(symbol: str) -> dict | None:
    return _service().load_latest_snapshot_for_symbol(symbol)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Classify the latest snapshot for a symbol")
    parser.add_argument("--snapshot-id", type=int, help="Classify one snapshot by id")
    args = parser.parse_args()

    if not args.symbol and args.snapshot_id is None:
        parser.error("Provide either --symbol or --snapshot-id")
    if args.symbol and args.snapshot_id is not None:
        parser.error("Use either --symbol or --snapshot-id, not both")

    if args.snapshot_id is not None:
        snapshot = load_snapshot_by_id(args.snapshot_id)
    else:
        snapshot = load_latest_snapshot_for_symbol(args.symbol)

    if not snapshot:
        print("No matching snapshot found.")
        return 1

    result = classify_feature_snapshot(snapshot)

    out = {
        "snapshot": snapshot,
        "setup": asdict(result),
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
