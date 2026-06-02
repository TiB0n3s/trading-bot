#!/usr/bin/env python3
"""Tests for extended regime switching service: artifact inference and state persistence."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.regime_switching_service import (
    _state_to_canonical_regime_map,
    detect_regime,
    infer_regime_from_artifact,
    load_regime_state,
    save_regime_state,
    train_hmm_regime_model,
)


class _PredictOnlyModel:
    def predict(self, _features):
        return [2]


def test_infer_regime_from_artifact_falls_back_on_missing_path():
    closes = [100 + i * 0.2 for i in range(40)]
    obs = infer_regime_from_artifact(closes=closes, artifact_path="/nonexistent/path.joblib")
    # Should fall back to deterministic; reasons must document the fallback.
    reasons_str = " ".join(obs.reasons)
    assert "artifact_load_failed" in reasons_str or "falling_back" in reasons_str
    assert obs.regime_id is not None or obs.regime_label == "insufficient_data"


def test_infer_regime_from_artifact_falls_back_on_short_closes():
    obs = infer_regime_from_artifact(closes=[100.0, 101.0], artifact_path="/nonexistent/path.joblib")
    assert obs.regime_id is None
    assert obs.regime_label == "insufficient_data"


def test_train_hmm_regime_model_includes_state_to_regime_map():
    closes = [100 + (i % 5) * 0.3 for i in range(80)]
    result = train_hmm_regime_model(closes=closes)
    if not result["trained"]:
        # hmmlearn not installed; skip content check
        return
    assert "state_to_regime_map" in result
    smap = result["state_to_regime_map"]
    canonical_values = set(smap.values())
    # All canonical regime IDs must be in {0, 1, 2}
    assert canonical_values.issubset({0, 1, 2})
    assert len(smap) == 3
    assert result["state_mapping_method"] == "risk_score_then_return"


def test_state_mapping_uses_volatility_for_high_risk_slot():
    means = [
        [0.10, 0.10],   # decent return, low vol
        [0.08, 2.50],   # decent return, high vol -> high-risk
        [-0.02, 0.40],  # lower return, moderate vol
    ]
    state_map = _state_to_canonical_regime_map(means)
    assert state_map["1"] == 2
    assert state_map["0"] == 0


def test_train_hmm_regime_model_artifact_includes_state_map():
    closes = [100 + (i % 5) * 0.3 for i in range(80)]
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / "regime_hmm_test.joblib"
        result = train_hmm_regime_model(closes=closes, artifact_path=artifact_path)
        if not result["trained"]:
            return  # hmmlearn not installed

        # Artifact file must exist and be loadable
        assert artifact_path.exists()
        try:
            import joblib
            artifact = joblib.load(artifact_path)
            assert "model" in artifact
            assert "state_to_regime_map" in artifact
            assert "metadata" in artifact
        except ImportError:
            pass


def test_infer_regime_uses_saved_artifact_when_present():
    closes = [100 + i * 0.15 for i in range(60)]
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / "regime_hmm_test.joblib"
        result = train_hmm_regime_model(closes=closes, artifact_path=artifact_path)
        if not result["trained"]:
            return  # hmmlearn not installed

        obs = infer_regime_from_artifact(
            closes=closes,
            artifact_path=artifact_path,
            regime_history=[0, 0, 0, 0],
        )
        assert obs.regime_id in {0, 1, 2}
        assert obs.regime_label in {"quiet_bull", "choppy_range", "high_volatility_risk"}
        assert obs.runtime_effect == "observe_only_no_order_authority"
        reasons_str = " ".join(obs.reasons)
        assert "hmmlearn_gaussian_hmm" in reasons_str


def test_infer_regime_falls_back_when_artifact_lacks_state_map():
    closes = [100 + i * 0.15 for i in range(60)]
    try:
        import joblib
    except Exception:
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / "bad_artifact.joblib"
        joblib.dump({"model": _PredictOnlyModel()}, artifact_path)

        obs = infer_regime_from_artifact(closes=closes, artifact_path=artifact_path)
        assert "artifact_load_failed" in " ".join(obs.reasons)


def test_load_regime_state_returns_empty_on_missing_file():
    state = load_regime_state("/nonexistent/regime_state.json")
    assert state["history"] == []
    assert state["last_updated"] is None


def test_save_and_load_regime_state_roundtrip():
    closes = [100 + i * 0.2 for i in range(40)]
    obs = detect_regime(closes=closes, regime_history=[0, 0, 0])

    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "regime_state.json"
        save_regime_state(state_path, obs)

        loaded = load_regime_state(state_path)
        assert "history" in loaded
        assert "last_observation" in loaded
        assert "last_updated" in loaded
        assert isinstance(loaded["history"], list)
        if obs.regime_id is not None:
            assert loaded["history"][-1] == obs.regime_id


def test_save_regime_state_caps_history_at_max():
    closes = [100 + i * 0.2 for i in range(40)]
    obs = detect_regime(closes=closes, regime_history=[0] * 10)

    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "regime_state.json"
        # Seed with a long existing history
        import json
        state_path.write_text(json.dumps({"history": list(range(200)), "last_updated": None}))
        save_regime_state(state_path, obs, max_history=10)

        loaded = load_regime_state(state_path)
        assert len(loaded["history"]) <= 10


def main():
    tests = [
        test_infer_regime_from_artifact_falls_back_on_missing_path,
        test_infer_regime_from_artifact_falls_back_on_short_closes,
        test_train_hmm_regime_model_includes_state_to_regime_map,
        test_state_mapping_uses_volatility_for_high_risk_slot,
        test_train_hmm_regime_model_artifact_includes_state_map,
        test_infer_regime_uses_saved_artifact_when_present,
        test_infer_regime_falls_back_when_artifact_lacks_state_map,
        test_load_regime_state_returns_empty_on_missing_file,
        test_save_and_load_regime_state_roundtrip,
        test_save_regime_state_caps_history_at_max,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} extended regime switching tests passed.")


if __name__ == "__main__":
    main()
