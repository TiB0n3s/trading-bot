"""Operator report for governed Transformer authority wiring."""

from __future__ import annotations

import os
from pathlib import Path

from services.transformer_authority_model_service import evaluate_transformer_authority


def run_transformer_authority_report(
    *,
    base_dir: Path,
    symbol: str = "SPY",
    action: str = "buy",
) -> bool:
    result = evaluate_transformer_authority(
        symbol=symbol,
        action=action,
        account_state={},
        registry_path=base_dir / "ml" / "models" / "registry.json",
    )

    print()
    print("=" * 72)
    print("  Transformer Authority")
    print("=" * 72)
    print(f"version                 : {result.get('version')}")
    print(f"runtime_effect          : {result.get('runtime_effect')}")
    print(f"symbol                  : {result.get('symbol')}")
    print(f"action                  : {result.get('action')}")
    print(f"enabled                 : {result.get('enabled')}")
    print(f"mode                    : {result.get('mode')}")
    print(f"model_id                : {result.get('model_id') or '-'}")
    print(f"decision                : {result.get('decision')}")
    print(f"size_multiplier         : {result.get('size_multiplier')}")
    print(f"probability             : {result.get('probability')}")
    print(f"reason                  : {result.get('reason')}")
    print(f"can_increase_size       : {result.get('can_increase_size')}")
    print(f"can_submit_orders       : {result.get('can_submit_orders')}")
    print()
    print("Environment contract")
    for key in (
        "TRANSFORMER_AUTHORITY_ENABLED",
        "TRANSFORMER_AUTHORITY_MODE",
        "TRANSFORMER_MODEL_ID",
        "TRANSFORMER_MODEL_MAX_AGE_SECONDS",
        "TRANSFORMER_BLOCK_THRESHOLD",
        "TRANSFORMER_SIZE_DOWN_THRESHOLD",
    ):
        value = os.getenv(key)
        print(f"  {key:<38} {value if value not in {None, ''} else '-'}")

    print()
    if result.get("decision") in {"allow", "size_down", "block"}:
        print("[OK] transformer authority adapter evaluated")
        return True
    print("[WARN] transformer authority is not active")
    return False
