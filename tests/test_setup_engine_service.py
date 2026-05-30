import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.setup_engine_repo import SetupEngineRepository
from services.setup_engine_service import (
    SetupEngineService,
    classify_feature_snapshot,
)


def test_classify_known_setup_preserves_label_and_score():
    result = classify_feature_snapshot(
        {
            "trend_direction": "neutral",
            "trend_strength": "weak",
            "distance_from_vwap": 0.01,
            "relative_strength_5m": -0.31,
        }
    )

    assert result.setup_label == "near_vwap_weak_strength_followthrough"
    assert result.recommendation == "favorable"
    assert result.setup_score == 88
    assert result.setup_key == "neutral/weak|near_vwap|weak"


def test_classify_unknown_snapshot_uses_existing_fallback():
    result = classify_feature_snapshot({})

    assert result.setup_label == "unclassified_transition"
    assert result.recommendation == "neutral"
    assert result.setup_score == 40
    assert result.setup_key == "unknown/unknown|unknown|unknown"


def test_score_modifiers_preserve_label_and_adjust_score():
    result = classify_feature_snapshot(
        {
            "trend_direction": "neutral",
            "trend_strength": "weak",
            "distance_from_vwap": 0.01,
            "relative_strength_5m": -0.31,
            "momentum_acceleration_pct": -0.06,
            "volume_surge_ratio": 3.0,
        }
    )

    assert result.setup_label == "near_vwap_weak_strength_followthrough"
    assert result.setup_score == 84
    assert "strong_decel" in result.rationale
    assert "vol_surge" in result.rationale


class FakeRepository:
    def __init__(self):
        self.loaded_id = None
        self.loaded_symbol = None

    def load_snapshot_by_id(self, snapshot_id):
        self.loaded_id = snapshot_id
        return {"id": snapshot_id, "symbol": "QQQ"}

    def load_latest_snapshot_for_symbol(self, symbol):
        self.loaded_symbol = symbol
        return {"id": 5, "symbol": symbol}


def test_service_delegates_snapshot_reads_to_repository():
    repo = FakeRepository()
    service = SetupEngineService(repository=repo)

    assert service.load_snapshot_by_id(7)["id"] == 7
    assert repo.loaded_id == 7
    assert service.load_latest_snapshot_for_symbol("qqq")["symbol"] == "qqq"
    assert repo.loaded_symbol == "qqq"


def test_repository_reads_feature_snapshots(tmp_path):
    db_path = tmp_path / "trades.db"
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        con.execute(
            """
            CREATE TABLE feature_snapshots (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                symbol TEXT,
                market_session TEXT,
                market_bias TEXT,
                trend_direction TEXT,
                trend_strength TEXT,
                relative_strength_5m REAL,
                distance_from_vwap REAL,
                ret_5m REAL,
                ret_15m REAL,
                bar_timeframe TEXT,
                bar_count INTEGER,
                momentum_acceleration_pct REAL,
                volume_surge_ratio REAL,
                extension_from_recent_base_pct REAL,
                prior_session_return_pct REAL
            )
            """
        )
        con.execute(
            """
            INSERT INTO feature_snapshots (
                id, timestamp, symbol, trend_direction, trend_strength,
                relative_strength_5m, distance_from_vwap
            )
            VALUES (1, '2026-05-30T10:00:00', 'QQQ', 'neutral', 'weak', -0.5, 0.0)
            """
        )

    repo = SetupEngineRepository(db_path=db_path)

    by_id = repo.load_snapshot_by_id(1)
    latest = repo.load_latest_snapshot_for_symbol("qqq")

    assert by_id["symbol"] == "QQQ"
    assert latest["id"] == 1


if __name__ == "__main__":
    import tempfile

    tests = [
        test_classify_known_setup_preserves_label_and_score,
        test_classify_unknown_snapshot_uses_existing_fallback,
        test_score_modifiers_preserve_label_and_adjust_score,
        test_service_delegates_snapshot_reads_to_repository,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    with tempfile.TemporaryDirectory() as tmp:
        test_repository_reads_feature_snapshots(Path(tmp))
    print("[OK] test_repository_reads_feature_snapshots")
    print(f"\nAll {len(tests) + 1} setup engine service tests passed.")
