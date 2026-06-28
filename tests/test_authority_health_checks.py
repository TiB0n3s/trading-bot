#!/usr/bin/env python3
"""Tests for authority-health diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from trading_bot.ops_checks.commands.authority_health_checks import (  # noqa: E402
    build_authority_health_payload,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_matrix(base_dir: Path) -> None:
    _write_json(
        base_dir / "ops" / "authority_matrix.json",
        {
            "version": "authority_matrix_v1",
            "runtime_effect": "governance_metadata_no_live_authority",
            "gates": [
                {
                    "id": "strategy_memory_recent",
                    "owner": "scripts/strategy_learner.py",
                    "source": "strategy_memory.json",
                    "authority": "tighten_only_contextual_memory",
                    "mode_scope": "paper_and_cash_tightening_only",
                    "freshness": "generated_at should be recent",
                    "fallback": "neutral",
                    "tests": ["tests/test_strategy_memory.py"],
                    "notes": "test fixture",
                }
            ],
        },
    )


def _write_strategy_memory(base_dir: Path, generated_at: str) -> None:
    _write_json(
        base_dir / "strategy_memory.json",
        {
            "generated_at": generated_at,
            "trade_count": 12,
            "bar_pattern_rows": 120,
            "bar_pattern_label_context": {
                "mixed_bar_pattern": {
                    "rows": 120,
                    "forward_outcome_rows": 110,
                    "authority_ready": True,
                }
            },
        },
    )


def _write_cache_chunk(base_dir: Path, symbol: str = "AAPL") -> None:
    cache_dir = base_dir / "data" / "historical_bars" / "polygon_1min"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{symbol}_1min_rth_2026-01-01_2026-01-05.csv").write_text(
        "Timestamp,Open,High,Low,Close,Volume\n"
        "2026-01-01T14:30:00+00:00,1,2,1,2,100\n",
        encoding="utf-8",
    )


def _write_manifest(base_dir: Path, *, errors: list[str] | None = None) -> None:
    _write_json(
        base_dir
        / "data"
        / "historical_bars"
        / "polygon_1min"
        / "backfill_manifests"
        / "historical_bar_backfill_20260105T120000Z.json",
        {
            "attempted_chunks": 1,
            "successful_chunks": 1,
            "cached_rows": 1,
            "persisted_rows": 1,
            "errors": errors or [],
        },
    )


def _write_model_diag(
    base_dir: Path,
    label: str,
    *,
    rows_loaded: int,
    trained: bool = True,
    accuracy: float | None = 0.75,
) -> None:
    training = {"trained": trained}
    if accuracy is not None:
        training["accuracy"] = accuracy
    _write_json(
        base_dir
        / "ml"
        / "models"
        / "historical_bar_patterns_v1"
        / "candidates"
        / f"historical_bar_{label}_20260105T120000Z.diagnostic.json",
        {
            "model_id": f"historical_bar_{label}_20260105T120000Z",
            "label_target": label,
            "runtime_effect": "observe_only_no_live_authority",
            "rows_loaded": rows_loaded,
            "symbol_count": 1,
            "training": training,
            "generated_at": "2026-01-05T12:00:00+00:00",
        },
    )


def test_authority_health_clean_fixture():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _write_matrix(base_dir)
        _write_strategy_memory(base_dir, "2026-01-05 12:00:00")
        _write_cache_chunk(base_dir)
        _write_manifest(base_dir)
        _write_model_diag(base_dir, "trend_scan_label", rows_loaded=10)
        _write_model_diag(base_dir, "triple_barrier_label", rows_loaded=10)

        payload = build_authority_health_payload(
            base_dir=base_dir,
            now=datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc),
            max_strategy_age_hours=24,
            historical_min_days=3,
            historical_min_symbols=1,
            model_min_rows=10,
            model_min_symbols=1,
        )

    assert payload["authority_clean"] is True
    assert payload["strategy_memory"]["bar_pattern_forward_outcome_rows"] == 110
    assert payload["historical_bars"]["symbols_ready"] == 1


def test_authority_health_reports_lineage_blockers():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _write_matrix(base_dir)
        _write_strategy_memory(base_dir, "2026-01-01 12:00:00")
        _write_cache_chunk(base_dir)
        _write_manifest(base_dir, errors=["AAPL 2026-01-01..2026-01-05: database is locked"])
        _write_model_diag(base_dir, "trend_scan_label", rows_loaded=10)
        _write_model_diag(
            base_dir,
            "triple_barrier_label",
            rows_loaded=1,
            trained=False,
            accuracy=None,
        )

        payload = build_authority_health_payload(
            base_dir=base_dir,
            now=datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc),
            max_strategy_age_hours=24,
            historical_min_days=3,
            historical_min_symbols=1,
            model_min_rows=10,
            model_min_symbols=1,
        )

    assert payload["authority_clean"] is False
    blockers = "\n".join(payload["blockers"])
    assert "strategy_memory:strategy_memory_stale" in blockers
    assert "historical_bars:latest_manifest_errors:1" in blockers
    assert "historical_models:triple_barrier_label:not_trained" in blockers
    assert "historical_models:triple_barrier_label:rows_loaded:1<10" in blockers


if __name__ == "__main__":
    test_authority_health_clean_fixture()
    print("[OK] test_authority_health_clean_fixture")
    test_authority_health_reports_lineage_blockers()
    print("[OK] test_authority_health_reports_lineage_blockers")
    print("\nAll 2 authority health tests passed.")
