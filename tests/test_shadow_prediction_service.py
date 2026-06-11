#!/usr/bin/env python3
"""Tests for observe-only shadow prediction scoring."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.shadow_prediction_repo import ShadowPredictionRepository
from services.shadow_prediction_service import ShadowPredictionService


class ExtremeModel:
    def predict_proba(self, matrix):
        return [[-1.0, 1.7] for _ in matrix]


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE feature_snapshots (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                timestamp TEXT,
                feature_available_at TEXT,
                ret_1m REAL,
                ret_5m REAL
            )
            """
        )
        con.execute(
            """
            INSERT INTO feature_snapshots (
                id, symbol, timestamp, feature_available_at, ret_1m, ret_5m
            ) VALUES (
                1, 'AAPL', '2026-06-03T10:00:00+00:00',
                '2026-06-03T10:00:05+00:00', 0.1, 0.2
            )
            """
        )


def test_shadow_prediction_service_writes_clipped_observe_only_rows():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        registry_path = base / "registry.json"
        artifact_path = base / "candidate.joblib"
        _build_db(db_path)
        joblib.dump(
            {
                "model": ExtremeModel(),
                "metadata": {
                    "feature_columns": ["ret_1m", "ret_5m"],
                    "generated_at": "2026-06-03T09:00:00+00:00",
                },
            },
            artifact_path,
        )
        registry_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "models": [
                        {
                            "model_id": "candidate-1",
                            "status": "candidate",
                            "artifact_path": str(artifact_path),
                            "created_at": "2026-06-03T09:00:00+00:00",
                        }
                    ],
                }
            )
        )
        service = ShadowPredictionService(
            repository=ShadowPredictionRepository(db_path),
            registry_path=registry_path,
        )

        payload = service.run(market_date="2026-06-03")
        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM shadow_predictions").fetchone()

    assert payload["status"] == "completed"
    assert payload["runtime_effect"] == "observe_only_no_live_authority"
    assert row["symbol"] == "AAPL"
    assert row["model_id"] == "candidate-1"
    assert row["raw_prediction_score"] == 170.0
    assert row["prediction_score"] == 100.0
    assert row["runtime_effect"] == "shadow_only_no_live_authority"


def test_shadow_prediction_service_skips_when_no_candidate_exists():
    with tempfile.TemporaryDirectory() as tmp:
        registry_path = Path(tmp) / "registry.json"
        registry_path.write_text(json.dumps({"version": 1, "models": []}))
        service = ShadowPredictionService(
            repository=ShadowPredictionRepository(Path(tmp) / "missing.db"),
            registry_path=registry_path,
        )

        payload = service.run(market_date="2026-06-03")

    assert payload["status"] == "skipped_no_candidate_model"
    assert payload["rows_written"] == 0


def test_shadow_prediction_health_reports_runtime_divergence():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE shadow_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_date TEXT,
                    symbol TEXT,
                    prediction_time TEXT,
                    model_id TEXT,
                    artifact_path TEXT,
                    prediction_score REAL,
                    raw_prediction_score REAL,
                    feature_snapshot_id INTEGER,
                    feature_available_at TEXT,
                    generated_at TEXT,
                    runtime_effect TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE decision_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_time TEXT,
                    symbol TEXT,
                    action TEXT,
                    approved INTEGER,
                    final_decision TEXT
                )
                """
            )
            con.executemany(
                """
                INSERT INTO shadow_predictions (
                    market_date, symbol, prediction_time, model_id, artifact_path,
                    prediction_score, raw_prediction_score, generated_at, runtime_effect
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "2026-06-03",
                        "AAPL",
                        "2026-06-03T10:00:00+00:00",
                        "candidate-1",
                        "x",
                        80.0,
                        80.0,
                        "2026-06-03T10:00:01+00:00",
                        "shadow_only_no_live_authority",
                    ),
                    (
                        "2026-06-03",
                        "MSFT",
                        "2026-06-03T10:00:00+00:00",
                        "candidate-1",
                        "x",
                        20.0,
                        20.0,
                        "2026-06-03T10:00:01+00:00",
                        "shadow_only_no_live_authority",
                    ),
                ],
            )
            con.executemany(
                """
                INSERT INTO decision_snapshots (
                    decision_time, symbol, action, approved, final_decision
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("2026-06-03T10:01:00+00:00", "AAPL", "buy", 1, "approved"),
                    ("2026-06-03T10:01:00+00:00", "MSFT", "buy", 1, "approved"),
                ],
            )

        service = ShadowPredictionService(
            repository=ShadowPredictionRepository(db_path),
            registry_path=Path(tmp) / "registry.json",
        )
        payload = service.health_report(
            market_date="2026-06-03",
            min_comparable_rows=2,
            max_divergence_rate=0.25,
        )

    assert payload["status"] == "divergence_alert"
    assert payload["comparable_rows"] == 2
    assert payload["divergence_rows"] == 1
    assert payload["divergence_rate"] == 0.5
    assert payload["promotion_certified"] is False


if __name__ == "__main__":
    tests = [
        test_shadow_prediction_service_writes_clipped_observe_only_rows,
        test_shadow_prediction_service_skips_when_no_candidate_exists,
        test_shadow_prediction_health_reports_runtime_divergence,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} shadow prediction service tests passed.")
