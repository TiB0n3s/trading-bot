"""Prediction validation report data service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from repositories.prediction_validation_repo import PredictionValidationRepository


@dataclass(frozen=True)
class PredictionValidationPayload:
    predictions: list[dict[str, Any]]
    signals: dict[str, Any]
    matched: dict[str, Any]
    strong_days: dict[str, Any]
    agreement_rows: list[dict[str, Any]]


class PredictionValidationService:
    def __init__(self, *, repository: PredictionValidationRepository):
        self.repository = repository

    def load_gate_ml_agreement(self, target_date: str) -> list[dict[str, Any]]:
        rows = self.repository.load_gate_ml_state_rows(target_date)
        out = []
        for row in rows:
            try:
                state = json.loads(row["account_state_json"] or "{}")
                gate = state.get("prediction_gate") or {}
                if gate.get("ml_prediction_compare_decision") is None:
                    continue
                out.append(
                    {
                        "gate_decision": (
                            gate.get("deterministic_signal_quality_decision")
                            or gate.get("prediction_decision")
                        ),
                        "gate_score": (
                            gate.get("deterministic_signal_quality_score")
                            or gate.get("prediction_score")
                        ),
                        "ml_decision": gate.get("ml_prediction_compare_decision"),
                        "ml_score": gate.get("ml_prediction_score"),
                        "agrees": gate.get("ml_prediction_agrees_with_gate"),
                    }
                )
            except Exception:
                continue
        return out

    def payload(self, target_date: str) -> PredictionValidationPayload:
        return PredictionValidationPayload(
            predictions=self.repository.load_predictions(target_date),
            signals=self.repository.load_signal_outcomes(target_date),
            matched=self.repository.load_matched_trades(target_date),
            strong_days=self.repository.load_strong_day_participation(target_date),
            agreement_rows=self.load_gate_ml_agreement(target_date),
        )


def build_default_prediction_validation_service(db_path=None) -> PredictionValidationService:
    repository = (
        PredictionValidationRepository(db_path=db_path)
        if db_path is not None
        else PredictionValidationRepository()
    )
    return PredictionValidationService(repository=repository)
