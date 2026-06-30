import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.daily_summary_service import DailySummaryService
from repositories.summary_repo import SummaryRepository


class FakeRepository:
    def __init__(self):
        self.calls = []

    def trades_for_day(self, target_date):
        self.calls.append(("trades_for_day", target_date))
        return [{"id": 1}]

    def matched_trades_for_day(self, target_date):
        self.calls.append(("matched_for_day", target_date))
        return [{"symbol": "AAPL"}]

    def trade_context_rows_for_day(self, target_date):
        self.calls.append(("context_for_day", target_date))
        return [{"setup_label": "x"}]

    def auto_buy_hard_block_audit_for_day(self, target_date):
        self.calls.append(("hard_block_audit_for_day", target_date))
        return {"rows_seen": 1, "counterfactual_strong_rows": 0}

    def prediction_model_summary_for_day(self, target_date):
        self.calls.append(("prediction_model_summary_for_day", target_date))
        return {"predictions": {"rows": 3}, "shadow_predictions": {"rows": 0}}

    def trades_for_range(self, start_date, end_date):
        self.calls.append(("trades_for_range", start_date, end_date))
        return [{"id": 2}]

    def matched_trades_for_range(self, start_date, end_date):
        self.calls.append(("matched_for_range", start_date, end_date))
        return [{"symbol": "QQQ"}]

    def trade_context_rows_for_range(self, start_date, end_date):
        self.calls.append(("context_for_range", start_date, end_date))
        return [{"setup_label": "y"}]

    def auto_buy_hard_block_audit_for_range(self, start_date, end_date):
        self.calls.append(("hard_block_audit_for_range", start_date, end_date))
        return {"rows_seen": 2, "counterfactual_strong_rows": 1}

    def prediction_model_summary_for_range(self, start_date, end_date):
        self.calls.append(("prediction_model_summary_for_range", start_date, end_date))
        return {"predictions": {"rows": 12}, "shadow_predictions": {"rows": 4}}


def test_daily_payload_refreshes_and_loads_day_rows():
    refreshed = []
    repo = FakeRepository()
    service = DailySummaryService(
        repository=repo,
        refresh_matched=lambda: refreshed.append(True),
    )

    payload = service.daily_payload("2026-05-30")

    assert refreshed == [True]
    assert payload.rows == [{"id": 1}]
    assert payload.matched == [{"symbol": "AAPL"}]
    assert payload.trade_rows == [{"setup_label": "x"}]
    assert payload.auto_buy_hard_block_audit == {
        "rows_seen": 1,
        "counterfactual_strong_rows": 0,
    }
    assert payload.prediction_model_summary == {
        "predictions": {"rows": 3},
        "shadow_predictions": {"rows": 0},
    }
    assert payload.header == "DAILY SUMMARY — 2026-05-30"
    assert repo.calls == [
        ("trades_for_day", "2026-05-30"),
        ("matched_for_day", "2026-05-30"),
        ("context_for_day", "2026-05-30"),
        ("hard_block_audit_for_day", "2026-05-30"),
        ("prediction_model_summary_for_day", "2026-05-30"),
    ]


def test_weekly_payload_uses_market_week_range():
    repo = FakeRepository()
    service = DailySummaryService(repository=repo, refresh_matched=lambda: None)

    payload = service.weekly_payload("2026-05-30")

    assert payload.header == "WEEKLY SUMMARY — 2026-05-25 to 2026-05-29"
    assert payload.auto_buy_hard_block_audit == {
        "rows_seen": 2,
        "counterfactual_strong_rows": 1,
    }
    assert payload.prediction_model_summary == {
        "predictions": {"rows": 12},
        "shadow_predictions": {"rows": 4},
    }
    assert repo.calls == [
        ("trades_for_range", "2026-05-25", "2026-05-30"),
        ("matched_for_range", "2026-05-25", "2026-05-30"),
        ("context_for_range", "2026-05-25", "2026-05-30"),
        ("hard_block_audit_for_range", "2026-05-25", "2026-05-30"),
        ("prediction_model_summary_for_range", "2026-05-25", "2026-05-30"),
    ]


def test_refresh_failure_is_reported_but_payload_still_loads():
    warnings = []
    repo = FakeRepository()
    service = DailySummaryService(
        repository=repo,
        refresh_matched=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        warning_sink=warnings.append,
    )

    payload = service.daily_payload("2026-05-30")

    assert payload.rows == [{"id": 1}]
    assert warnings == ["WARNING: matched_trades rebuild failed: boom"]


def test_prediction_model_summary_reads_scores_and_sample_sizes(tmp_path):
    db = tmp_path / "trades.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE daily_symbol_predictions ("
        "market_date TEXT NOT NULL, symbol TEXT NOT NULL, prediction_score REAL, "
        "sample_size INTEGER, probability_of_profit REAL, "
        "probability_of_profit_sample_size INTEGER, trend_score REAL, "
        "trend_similarity_sample_size INTEGER)"
    )
    con.execute(
        "CREATE TABLE shadow_predictions ("
        "market_date TEXT NOT NULL, symbol TEXT NOT NULL, model_id TEXT, "
        "prediction_score REAL)"
    )
    con.executemany(
        "INSERT INTO daily_symbol_predictions "
        "(market_date, symbol, prediction_score, sample_size, probability_of_profit, "
        "probability_of_profit_sample_size, trend_score, trend_similarity_sample_size) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("2026-06-29", "AAPL", 55.0, 30, 0.61, 578, 50.0, 0),
            ("2026-06-29", "MSFT", 52.0, 28, 0.58, 341, 49.0, 0),
        ],
    )
    con.execute(
        "INSERT INTO shadow_predictions "
        "(market_date, symbol, model_id, prediction_score) VALUES (?, ?, ?, ?)",
        ("2026-06-29", "AAPL", "model_v1", 13.5),
    )
    con.commit()
    con.close()

    summary = SummaryRepository(db_path=db).prediction_model_summary_for_day("2026-06-29")

    assert summary["predictions"]["rows"] == 2
    assert summary["predictions"]["prediction_score_rows"] == 2
    assert summary["predictions"]["sample_size_rows"] == 2
    assert summary["predictions"]["avg_prediction_score"] == 53.5
    assert summary["predictions"]["top_symbols"][0]["symbol"] == "AAPL"
    assert summary["shadow_predictions"]["rows"] == 1
    assert summary["shadow_predictions"]["prediction_score_rows"] == 1
    assert summary["shadow_predictions"]["models"][0]["model_id"] == "model_v1"


if __name__ == "__main__":
    tests = [
        test_daily_payload_refreshes_and_loads_day_rows,
        test_weekly_payload_uses_market_week_range,
        test_refresh_failure_is_reported_but_payload_still_loads,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} daily summary service tests passed.")
