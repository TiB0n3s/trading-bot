"""Tests for candidate-universe forward outcome backfill."""

from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.candidate_outcome_backfill_service import (
    CandidateOutcomeBackfillService,
    compute_candidate_outcome,
)


class FakeRepository:
    def __init__(self):
        self.updated = {}

    def rows_for_date(self, target_date, symbol=None):
        return [
            {
                "id": 1,
                "candidate_ts": f"{target_date}T10:00:00-04:00",
                "symbol": "AAPL",
                "action": "buy",
                "candidate_json": '{"candidate": {"symbol": "AAPL"}}',
            }
        ]

    def update_candidate_json(self, candidate_id, payload):
        self.updated[candidate_id] = payload


class FakeMarketData:
    def fetch_day_bars(self, *, symbol, start_dt, end_dt):
        return [
            {
                "timestamp": "2026-06-02T10:00:00-04:00",
                "close": 100.0,
                "high": 100.5,
                "low": 99.8,
            },
            {
                "timestamp": "2026-06-02T10:05:00-04:00",
                "close": 101.0,
                "high": 101.3,
                "low": 100.2,
            },
            {
                "timestamp": "2026-06-02T10:30:00-04:00",
                "close": 102.0,
                "high": 102.5,
                "low": 100.9,
            },
            {
                "timestamp": "2026-06-02T11:00:00-04:00",
                "close": 103.0,
                "high": 103.4,
                "low": 101.5,
            },
        ]


def test_compute_candidate_outcome_uses_first_bar_close_reference():
    outcome = compute_candidate_outcome(
        {
            "candidate_ts": "2026-06-02T10:00:00-04:00",
            "action": "buy",
        },
        FakeMarketData().fetch_day_bars(symbol="AAPL", start_dt=None, end_dt=None),
    )

    assert outcome["candidate_outcome_version"] == "candidate_outcome_backfill_v1"
    assert outcome["forward_reference_price"] == 100.0
    assert outcome["forward_reference_price_source"] == "first_bar_close_at_or_after_candidate_ts"
    assert outcome["return_5m"] == 1.0
    assert outcome["return_30m"] == 2.0
    assert outcome["return_60m"] == 3.0
    assert outcome["max_favorable_60m"] == 3.4
    assert outcome["max_adverse_60m"] == -0.2
    assert outcome["label_status"] == "labeled"


def test_compute_candidate_outcome_prefers_captured_reference_price():
    outcome = compute_candidate_outcome(
        {
            "candidate_ts": "2026-06-02T10:00:00-04:00",
            "action": "buy",
            "candidate_json": '{"reference_price": 99.5, "reference_price_source": "quote_mid", "quote_ts": "2026-06-02T10:00:00-04:00"}',
        },
        FakeMarketData().fetch_day_bars(symbol="AAPL", start_dt=None, end_dt=None),
    )

    assert outcome["forward_reference_price"] == 99.5
    assert outcome["forward_reference_price_source"] == "quote_mid"
    assert outcome["forward_reference_ts"] == "2026-06-02T10:00:00-04:00"
    assert outcome["return_5m"] == 1.507538


def test_backfill_updates_candidate_json_with_forward_outcome():
    repo = FakeRepository()
    service = CandidateOutcomeBackfillService(repo, FakeMarketData())

    result = service.backfill("2026-06-02")

    assert result.updated == 1
    assert result.error == 0
    assert result.coverage_before["rows_with_forward_outcome"] == 0
    assert result.projected_coverage_after["rows_with_forward_outcome"] == 1
    assert result.projected_coverage_after["forward_outcome_coverage_rate"] == 1.0
    updated = repo.updated[1]
    assert updated["candidate"]["symbol"] == "AAPL"
    assert updated["forward_return_pct"] == 3.0
    assert updated["forward_mfe_pct"] == 3.4
    assert updated["runtime_effect"] if "runtime_effect" in updated else True


def test_backfill_skips_existing_unless_overwrite():
    class ExistingRepo(FakeRepository):
        def rows_for_date(self, target_date, symbol=None):
            row = super().rows_for_date(target_date, symbol=symbol)[0]
            row["candidate_json"] = json.dumps({"forward_return_pct": 1.2})
            return [row]

    repo = ExistingRepo()
    service = CandidateOutcomeBackfillService(repo, FakeMarketData())

    result = service.backfill("2026-06-02")

    assert result.skipped_existing == 1
    assert result.updated == 0
    assert repo.updated == {}


if __name__ == "__main__":
    test_compute_candidate_outcome_uses_first_bar_close_reference()
    test_compute_candidate_outcome_prefers_captured_reference_price()
    test_backfill_updates_candidate_json_with_forward_outcome()
    test_backfill_skips_existing_unless_overwrite()
    print("candidate outcome backfill service tests passed")
