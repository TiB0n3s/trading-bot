import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.prediction_cache_service import PredictionCacheService


class FakeRepository:
    def __init__(self, rows=None, raises=False):
        self.rows = rows or []
        self.raises = raises
        self.market_dates = []

    def daily_predictions(self, market_date):
        self.market_dates.append(market_date)
        if self.raises:
            raise RuntimeError("db unavailable")
        return self.rows


def _service(repo):
    return PredictionCacheService(
        repository_factory=lambda db_path: repo,
        ttl_seconds=60,
        target_latency_ms=25,
        hard_timeout_ms=50,
        expected_date_provider=lambda: date(2026, 5, 27),
    )


def test_load_predictions_normalizes_symbols_and_metadata():
    repo = FakeRepository(
        rows=[
            {
                "market_date": "2026-05-27",
                "symbol": "aapl",
                "prediction_score": 72.5,
                "confidence": "medium",
            },
            {"market_date": "2026-05-27", "symbol": "", "prediction_score": 10},
        ]
    )
    service = _service(repo)

    loaded = service.load_predictions_from_db(market_date="2026-05-27")

    assert list(loaded) == ["AAPL"]
    assert loaded["AAPL"]["symbol"] == "AAPL"
    assert loaded["AAPL"]["provider"] == "daily_symbol_predictions_ttl_cache"
    assert loaded["AAPL"]["runtime_effect"] == "observe_only_compare"
    assert loaded["AAPL"]["cache_loaded_at"]
    assert repo.market_dates == ["2026-05-27"]


def test_load_predictions_hard_clips_extreme_model_outputs():
    repo = FakeRepository(
        rows=[
            {
                "market_date": "2026-05-27",
                "symbol": "AAPL",
                "prediction_score": 999,
                "timing_score": -10,
                "probability_of_profit": 1.5,
                "expected_win_rate": -0.2,
            },
        ]
    )
    service = _service(repo)

    loaded = service.load_predictions_from_db(market_date="2026-05-27")
    pred = loaded["AAPL"]

    assert pred["prediction_score"] == 100.0
    assert pred["timing_score"] == 0.0
    assert pred["probability_of_profit"] == 1.0
    assert pred["expected_win_rate"] == 0.0
    assert pred["prediction_output_clipped"] is True
    assert set(pred["prediction_output_clipped_fields"]) == {
        "prediction_score",
        "timing_score",
        "probability_of_profit",
        "expected_win_rate",
    }


def test_refresh_populates_memory_and_lookup_is_read_only_copy():
    repo = FakeRepository(
        rows=[
            {
                "market_date": "2026-05-27",
                "symbol": "AAPL",
                "prediction_score": 72.5,
            }
        ]
    )
    service = _service(repo)

    status = service.refresh(market_date="2026-05-27")
    pred = service.get_cached_prediction("aapl", market_date="2026-05-27")
    pred["prediction_score"] = 1

    assert status["symbol_count"] == 1
    assert status["market_date"] == "2026-05-27"
    assert service.get_cached_prediction("AAPL", market_date="2026-05-27")[
        "prediction_score"
    ] == 72.5
    assert service.get_cached_prediction("AAPL", market_date="2026-05-28") is None


def test_refresh_failure_records_status_error_without_raising():
    service = _service(FakeRepository(raises=True))

    status = service.refresh(market_date="2026-05-27")

    assert status["last_error"] == "db unavailable"
    assert status["symbol_count"] == 0


if __name__ == "__main__":
    tests = [
        test_load_predictions_normalizes_symbols_and_metadata,
        test_load_predictions_hard_clips_extreme_model_outputs,
        test_refresh_populates_memory_and_lookup_is_read_only_copy,
        test_refresh_failure_records_status_error_without_raising,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} prediction cache service tests passed.")
