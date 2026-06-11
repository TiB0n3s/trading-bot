#!/usr/bin/env python3
"""Tests for governed Transformer authority service."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import services.transformer_authority_model_service as transformer_service  # noqa: E402
from services.transformer_authority_model_service import (  # noqa: E402
    evaluate_transformer_authority,
    train_transformer_authority_model,
)


def test_transformer_training_blocks_small_samples():
    result = train_transformer_authority_model(
        rows=[{"triple_barrier_label": 1, "ret_1m": 1.0}],
        min_samples=5,
    ).to_dict()

    assert result["trained"] is False
    assert "insufficient labeled rows" in result["reason"]


def test_transformer_authority_disabled_without_env():
    result = evaluate_transformer_authority(
        symbol="AAPL",
        action="buy",
        env={},
    )

    assert result["decision"] == "no_authority"
    assert result["can_increase_size"] is False
    assert result["can_submit_orders"] is False


def test_transformer_authority_rejects_unpromoted_registry_status():
    with tempfile.TemporaryDirectory() as tmp:
        registry_path = Path(tmp) / "registry.json"
        registry_path.write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "model_id": "tx1",
                            "status": "observe_only",
                            "artifact_path": str(Path(tmp) / "missing.pt"),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = evaluate_transformer_authority(
            symbol="AAPL",
            action="buy",
            env={
                "TRANSFORMER_AUTHORITY_ENABLED": "true",
                "TRANSFORMER_AUTHORITY_MODE": "paper_gate",
                "TRANSFORMER_MODEL_ID": "tx1",
                "TRANSFORMER_MODEL_MAX_AGE_SECONDS": "86400",
            },
            registry_path=registry_path,
        )

    assert result["decision"] == "no_authority"
    assert result["status"] == "observe_only"
    assert "does not grant" in result["reason"]


def test_transformer_authority_paper_gates_high_risk_excursion_forecast():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_path = Path(tmp) / "model.pt"
        artifact_path.write_text("placeholder", encoding="utf-8")
        registry_path = Path(tmp) / "registry.json"
        registry_path.write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "model_id": "tx1",
                            "status": "paper_gate",
                            "artifact_path": str(artifact_path),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with patch.object(
            transformer_service,
            "score_transformer_authority_artifact",
            return_value={
                "scored": True,
                "probability": 0.81,
                "runtime_effect": "model_score_only",
            },
        ):
            result = evaluate_transformer_authority(
                symbol="AAPL",
                action="buy",
                account_state={
                    "tft_multi_horizon_forecast": {
                        "high_risk_excursion_probability": 0.78,
                    }
                },
                env={
                    "TRANSFORMER_AUTHORITY_ENABLED": "true",
                    "TRANSFORMER_AUTHORITY_MODE": "paper_gate",
                    "TRANSFORMER_MODEL_ID": "tx1",
                    "TRANSFORMER_MODEL_MAX_AGE_SECONDS": "86400",
                    "TRANSFORMER_HIGH_RISK_EXCURSION_THRESHOLD": "0.70",
                },
                registry_path=registry_path,
            )

    assert result["decision"] == "block"
    assert result["size_multiplier"] == 0.0
    assert result["risk_excursion_probability"] == 0.78
    assert "high-risk excursion" in result["reason"]


if __name__ == "__main__":
    tests = [
        test_transformer_training_blocks_small_samples,
        test_transformer_authority_disabled_without_env,
        test_transformer_authority_rejects_unpromoted_registry_status,
        test_transformer_authority_paper_gates_high_risk_excursion_forecast,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} transformer authority tests passed.")
