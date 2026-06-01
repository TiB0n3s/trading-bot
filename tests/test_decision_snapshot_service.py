import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.decision_snapshot_service import (
    DECISION_SNAPSHOT_FEATURE_SEMANTIC_VERSION,
    DecisionSnapshotService,
)
from services.canonical_intelligence_service import CANONICAL_INTELLIGENCE_VERSION


class FakeRepository:
    def __init__(self):
        self.inserted = None
        self.summary_date = None

    def insert_snapshot(self, row):
        self.inserted = dict(row)
        return 123

    def summarize_snapshots(self, target_date):
        self.summary_date = target_date
        return {"total": 1, "symbols": 1, "by_decision": []}


def _record_snapshot(tmp_path, *, prediction_gate):
    (tmp_path / "market_context.json").write_text('{"market_date": "2026-05-30"}')
    repo = FakeRepository()
    service = DecisionSnapshotService(repository=repo, base_dir=tmp_path)

    snapshot_id = service.record_decision_snapshot(
        trade_id=7,
        timestamp="2026-05-30 09:31:00",
        source="unit",
        symbol="AAPL",
        action="buy",
        signal_price=100.0,
        decision={"approved": True, "confidence": "high", "position_size_pct": 1.0},
        order={"order_id": "abc", "status": "filled"},
        context={
            "market_bias": "buy",
            "session_trend_label": "strong_uptrend",
            "session_momentum_60m_pct": 1.2,
            "session_momentum_120m_pct": 1.8,
            "session_trend_regime": "mature_uptrend",
            "trend_persistence_score": 5,
            "pullback_with_trend_score": 1,
            "late_chase_maturity_score": 4,
            "reversal_attempt_score": 0,
        },
        account_state={
            "prediction_gate": prediction_gate,
            "setup_observation": {
                "setup_label": "near_vwap_recovery",
                "setup_confidence": "high",
                "setup_policy_action": "boost",
            },
            "strategy_observation": {
                "trader_brain": {
                    "score": 80,
                    "setup_type": "test",
                    "approved_by_scorer": True,
                    "reason": "ok",
                }
            },
            "buy_opportunity": {
                "buy_opportunity_score": 65,
                "buy_opportunity_recommendation": "buy_candidate",
            },
            "intelligence_context": {
                "summary": {
                    "support_count": 2,
                    "risk_count": 1,
                },
            },
        },
        raw_signal={"symbol": "AAPL"},
    )
    return snapshot_id, repo.inserted


def test_record_decision_snapshot_builds_expected_row(tmp_path):
    snapshot_id, row = _record_snapshot(
        tmp_path,
        prediction_gate={
            "prediction_score": 71,
            "prediction_decision": "observe_only",
            "ml_prediction_score": 63,
            "ml_prediction_confidence": "medium",
            "ml_prediction_sample_size": 42,
        },
    )

    assert snapshot_id == 123
    assert row["feature_semantic_version"] == DECISION_SNAPSHOT_FEATURE_SEMANTIC_VERSION
    assert row["canonical_intelligence_version"] == CANONICAL_INTELLIGENCE_VERSION
    assert len(row["canonical_intelligence_hash"]) == 64
    canonical = json.loads(row["canonical_intelligence_json"])
    assert canonical["version"] == CANONICAL_INTELLIGENCE_VERSION
    assert canonical["symbol"] == "AAPL"
    assert canonical["event_state"]["support_count"] == 2
    assert canonical["prediction_state"]["ml_score"] == 63
    assert canonical["momentum_state"]["session_momentum_60m_pct"] == 1.2
    assert canonical["momentum_state"]["session_trend_regime"] == "mature_uptrend"
    assert canonical["feature_vector_hash"] == row["canonical_intelligence_hash"]
    assert row["trade_id"] == 7
    assert row["symbol"] == "AAPL"
    assert row["approved"] == 1
    assert row["final_decision"] == "approved"
    assert row["order_id"] == "abc"
    assert row["market_bias"] == "buy"
    assert row["session_trend_label"] == "strong_uptrend"
    assert row["session_momentum_60m_pct"] == 1.2
    assert row["session_momentum_120m_pct"] == 1.8
    assert row["session_trend_regime"] == "mature_uptrend"
    assert row["late_chase_maturity_score"] == 4
    assert row["prediction_score"] == 63
    assert row["prediction_confidence"] == "medium"
    assert row["prediction_sample_size"] == 42
    assert row["setup_label"] == "near_vwap_recovery"
    assert row["setup_confidence"] == "high"
    assert row["trader_brain_approved"] == 1
    assert row["buy_opportunity_score"] == 65
    assert row["market_context_date"] == "2026-05-30"
    assert row["market_context_hash"]
    assert row["raw_signal_json"] == '{"symbol": "AAPL"}'


def test_prediction_feature_fallback_uses_ml_when_present(tmp_path):
    _, row = _record_snapshot(
        tmp_path,
        prediction_gate={
            "prediction_score": 71,
            "prediction_confidence": "deterministic",
            "prediction_sample_size": 99,
            "ml_prediction_score": 63,
            "ml_prediction_confidence": "medium",
            "ml_prediction_sample_size": 42,
        },
    )

    assert row["prediction_score"] == 63
    assert row["prediction_confidence"] == "medium"
    assert row["prediction_sample_size"] == 42


def test_prediction_feature_fallback_uses_deterministic_when_ml_absent(tmp_path):
    _, row = _record_snapshot(
        tmp_path,
        prediction_gate={
            "prediction_score": 71,
            "prediction_confidence": "deterministic",
            "prediction_sample_size": 99,
        },
    )

    assert row["prediction_score"] == 71
    assert row["prediction_confidence"] == "deterministic"
    assert row["prediction_sample_size"] == 99


def test_prediction_feature_fallback_preserves_zero_sample_size(tmp_path):
    _, row = _record_snapshot(
        tmp_path,
        prediction_gate={
            "prediction_score": 71,
            "prediction_confidence": "deterministic",
            "prediction_sample_size": 99,
            "ml_prediction_score": 63,
            "ml_prediction_confidence": None,
            "ml_prediction_sample_size": 0,
        },
    )

    assert row["prediction_score"] == 63
    assert row["prediction_confidence"] == "deterministic"
    assert row["prediction_sample_size"] == 0


def test_prediction_feature_fallback_handles_absent_scores(tmp_path):
    _, row = _record_snapshot(tmp_path, prediction_gate={})

    assert row["prediction_score"] is None
    assert row["prediction_confidence"] is None
    assert row["prediction_sample_size"] is None


def test_summarize_snapshots_delegates_to_repository(tmp_path):
    repo = FakeRepository()
    service = DecisionSnapshotService(repository=repo, base_dir=tmp_path)

    assert service.summarize_snapshots("2026-05-30")["total"] == 1
    assert repo.summary_date == "2026-05-30"


if __name__ == "__main__":
    import tempfile

    tests = [
        test_record_decision_snapshot_builds_expected_row,
        test_prediction_feature_fallback_uses_ml_when_present,
        test_prediction_feature_fallback_uses_deterministic_when_ml_absent,
        test_prediction_feature_fallback_preserves_zero_sample_size,
        test_prediction_feature_fallback_handles_absent_scores,
        test_summarize_snapshots_delegates_to_repository,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} decision snapshot service tests passed.")
