#!/usr/bin/env python3
"""Tests for candidate-universe persistence."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.candidate_universe_repo import CandidateUniverseRepository  # noqa: E402
from services.intelligence.candidates.universe import (  # noqa: E402
    CANDIDATE_UNIVERSE_CONTRACT_VERSION,
    CandidateCapture,
    CandidateUniverseService,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def test_persist_entry_candidates_and_near_threshold_status():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        service = CandidateUniverseService(CandidateUniverseRepository(db_path))

        row_id = service.persist_scored_candidate(
            candidate_ts="2026-06-01T14:30:00+00:00",
            symbol="aapl",
            action="buy",
            score=94,
            threshold=100,
            taken=False,
            source="auto_buy",
            setup_label="breakout",
            regime="trend_expansion",
            payload={"rank": 2},
        )

        rows = service.rows_for_date("2026-06-01")
        assert_true(row_id > 0, "row id")
        assert_equal(len(rows), 1, "row count")
        assert_equal(rows[0]["symbol"], "AAPL", "symbol normalized")
        assert_equal(rows[0]["candidate_status"], "near_threshold", "status")
        assert_equal(rows[0]["threshold_distance"], -6.0, "threshold distance")
        payload = json.loads(rows[0]["candidate_json"])
        assert_equal(payload["contract_version"], CANDIDATE_UNIVERSE_CONTRACT_VERSION, "version")
        assert_equal(
            rows[0]["runtime_effect"], "candidate_capture_only_no_live_authority", "effect"
        )


def test_persist_exit_candidate_considered_not_taken():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        service = CandidateUniverseService(CandidateUniverseRepository(db_path))

        service.persist(
            CandidateCapture(
                candidate_ts="2026-06-01T15:00:00+00:00",
                symbol="MSFT",
                action="sell",
                candidate_kind="exit",
                candidate_status="exit_considered_not_taken",
                score=0.42,
                decision="hold",
                reason="exit_pressure_below_threshold",
                payload={"exit_pressure_state": "moderate_exit_pressure"},
            )
        )

        rows = service.rows_for_date("2026-06-01", candidate_kind="exit")
        assert_equal(len(rows), 1, "exit row count")
        assert_equal(rows[0]["candidate_kind"], "exit", "kind")
        assert_equal(rows[0]["candidate_status"], "exit_considered_not_taken", "status")


def test_candidate_summary_between_uses_forward_outcome_payloads():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        service = CandidateUniverseService(CandidateUniverseRepository(db_path))

        service.persist_scored_candidate(
            candidate_ts="2026-06-01T14:30:00+00:00",
            symbol="AAPL",
            action="buy",
            score=94,
            threshold=100,
            taken=False,
            payload={"forward_return_pct": 0.7},
        )
        service.persist_scored_candidate(
            candidate_ts="2026-06-01T14:32:00+00:00",
            symbol="MSFT",
            action="buy",
            score=70,
            threshold=100,
            taken=True,
            payload={"candidate": {"return_60m": -0.2}},
        )
        service.persist_scored_candidate(
            candidate_ts="2026-06-01T14:34:00+00:00",
            symbol="NVDA",
            action="buy",
            score=50,
            threshold=100,
            taken=False,
            payload={"note": "no outcome yet"},
        )

        summary = CandidateUniverseRepository(db_path).summary_between(
            "2026-06-01",
            "2026-06-01",
        )

        assert_equal(summary["rows"], 3, "rows")
        assert_equal(summary["rows_with_forward_outcome"], 2, "forward rows")
        assert_equal(summary["missing_forward_outcome"], 1, "missing forward")
        assert_equal(summary["non_taken_rows"], 2, "non-taken rows")
        assert_equal(summary["non_taken_with_forward_outcome"], 1, "non-taken forward")
        assert_equal(summary["by_kind"]["entry"], 3, "kind count")


def test_rows_between_honors_limit():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        service = CandidateUniverseService(CandidateUniverseRepository(db_path))

        for idx in range(5):
            service.persist_scored_candidate(
                candidate_ts=f"2026-06-01T14:3{idx}:00+00:00",
                symbol=f"SYM{idx}",
                action="buy",
                score=50 + idx,
                threshold=100,
                taken=False,
                payload={"idx": idx},
            )

        rows = CandidateUniverseRepository(db_path).rows_between(
            "2026-06-01",
            "2026-06-01",
            candidate_kind="entry",
            limit=2,
        )

        assert_equal(len(rows), 2, "limited rows")
        assert_equal(rows[0]["symbol"], "SYM0", "first row")
        assert_equal(rows[1]["symbol"], "SYM1", "second row")


def test_persist_reuses_repository_initialization():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        repository = CandidateUniverseRepository(db_path)
        service = CandidateUniverseService(repository)

        service.persist_scored_candidate(
            candidate_ts="2026-06-01T14:30:00+00:00",
            symbol="AAPL",
            action="buy",
            score=50,
            threshold=100,
            taken=False,
        )
        service.persist_scored_candidate(
            candidate_ts="2026-06-01T14:31:00+00:00",
            symbol="MSFT",
            action="buy",
            score=51,
            threshold=100,
            taken=False,
        )

        assert_true(repository._initialized, "repository initialized")
        rows = service.rows_for_date("2026-06-01")
        assert_equal(len(rows), 2, "row count")


def test_learned_tiebreaker_stats_splits_symbol_and_pattern_buckets():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        service = CandidateUniverseService(CandidateUniverseRepository(db_path))

        for idx, (symbol, ret) in enumerate(
            [
                ("AAPL", 0.6),
                ("AAPL", 0.4),
                ("MSFT", -0.2),
            ]
        ):
            service.persist_scored_candidate(
                candidate_ts=f"2026-06-01T14:3{idx}:00+00:00",
                symbol=symbol,
                action="buy",
                score=99,
                threshold=100,
                taken=False,
                setup_label="trend_reclaim",
                payload={
                    "candidate": {"symbol_pattern": "trend_reclaim"},
                    "forward_return_pct": ret,
                    "forward_mfe_pct": 1.2,
                    "forward_mae_pct": -0.3,
                },
            )

        stats = CandidateUniverseRepository(db_path).learned_tiebreaker_stats(
            "2026-06-01",
            "2026-06-01",
            symbol="AAPL",
            pattern="trend_reclaim",
            candidate_statuses=("near_threshold", "taken"),
        )

        assert_equal(stats["symbol_pattern_stats"]["sample_size"], 2, "symbol-pattern sample size")
        assert_equal(stats["symbol_pattern_stats"]["win_rate"], 1.0, "symbol win rate")
        assert_equal(stats["pattern_stats"]["sample_size"], 3, "pattern sample size")
        assert_equal(stats["pattern_stats"]["win_rate"], 0.6667, "pattern win rate")


def test_invalid_candidate_contract_values_are_rejected():
    service = CandidateUniverseService(CandidateUniverseRepository(":memory:"))
    try:
        service.persist(
            CandidateCapture(
                candidate_ts="2026-06-01T15:00:00+00:00",
                symbol="MSFT",
                action="buy",
                candidate_kind="unknown",
                candidate_status="scored_not_taken",
            )
        )
    except ValueError as exc:
        assert_true("candidate_kind" in str(exc), "kind error")
        return
    raise AssertionError("expected invalid candidate kind to raise")


def main():
    tests = [
        test_persist_entry_candidates_and_near_threshold_status,
        test_persist_exit_candidate_considered_not_taken,
        test_candidate_summary_between_uses_forward_outcome_payloads,
        test_rows_between_honors_limit,
        test_persist_reuses_repository_initialization,
        test_learned_tiebreaker_stats_splits_symbol_and_pattern_buckets,
        test_invalid_candidate_contract_values_are_rejected,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} candidate universe service tests passed.")


if __name__ == "__main__":
    main()
