import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.prediction_validation_service import PredictionValidationService


class FakeRepository:
    def load_predictions(self, target_date):
        return [{"symbol": "AAPL"}]

    def load_signal_outcomes(self, target_date):
        return {"AAPL": {"signals": 1}}

    def load_matched_trades(self, target_date):
        return {"AAPL": {"matched_trades": 1}}

    def load_strong_day_participation(self, target_date):
        return {"AAPL": {"primary_status": "full_participation"}}

    def load_gate_ml_state_rows(self, target_date):
        return [
            {
                "account_state_json": (
                    '{"prediction_gate": {'
                    '"prediction_decision": "pass",'
                    '"prediction_score": 60,'
                    '"ml_prediction_compare_decision": "pass",'
                    '"ml_prediction_score": 62,'
                    '"ml_prediction_agrees_with_gate": true'
                    "}}"
                )
            },
            {"account_state_json": "not-json"},
        ]


def test_prediction_validation_payload_loads_all_sections():
    service = PredictionValidationService(repository=FakeRepository())

    payload = service.payload("2026-05-30")

    assert payload.predictions == [{"symbol": "AAPL"}]
    assert payload.signals["AAPL"]["signals"] == 1
    assert payload.matched["AAPL"]["matched_trades"] == 1
    assert payload.strong_days["AAPL"]["primary_status"] == "full_participation"
    assert payload.agreement_rows == [
        {
            "gate_decision": "pass",
            "gate_score": 60,
            "ml_decision": "pass",
            "ml_score": 62,
            "agrees": True,
        }
    ]


if __name__ == "__main__":
    test_prediction_validation_payload_loads_all_sections()
    print("[OK] test_prediction_validation_payload_loads_all_sections")
    print("\nAll 1 prediction validation service tests passed.")
