import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.decision_snapshot_service import DecisionSnapshotService


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


def test_record_decision_snapshot_builds_expected_row(tmp_path):
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
        context={"market_bias": "buy", "session_trend_label": "strong_uptrend"},
        account_state={
            "prediction_gate": {
                "prediction_score": 71,
                "prediction_decision": "observe_only",
            },
            "setup_observation": {
                "setup_label": "near_vwap_recovery",
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
        },
        raw_signal={"symbol": "AAPL"},
    )

    row = repo.inserted
    assert snapshot_id == 123
    assert row["trade_id"] == 7
    assert row["symbol"] == "AAPL"
    assert row["approved"] == 1
    assert row["final_decision"] == "approved"
    assert row["order_id"] == "abc"
    assert row["market_bias"] == "buy"
    assert row["session_trend_label"] == "strong_uptrend"
    assert row["prediction_score"] == 71
    assert row["setup_label"] == "near_vwap_recovery"
    assert row["trader_brain_approved"] == 1
    assert row["buy_opportunity_score"] == 65
    assert row["market_context_date"] == "2026-05-30"
    assert row["market_context_hash"]
    assert row["raw_signal_json"] == '{"symbol": "AAPL"}'


def test_summarize_snapshots_delegates_to_repository(tmp_path):
    repo = FakeRepository()
    service = DecisionSnapshotService(repository=repo, base_dir=tmp_path)

    assert service.summarize_snapshots("2026-05-30")["total"] == 1
    assert repo.summary_date == "2026-05-30"


if __name__ == "__main__":
    import tempfile

    tests = [
        test_record_decision_snapshot_builds_expected_row,
        test_summarize_snapshots_delegates_to_repository,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} decision snapshot service tests passed.")
