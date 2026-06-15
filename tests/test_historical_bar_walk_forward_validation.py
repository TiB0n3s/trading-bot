#!/usr/bin/env python3
"""Tests for purged/embargoed historical-bar walk-forward validation."""

from __future__ import annotations

from pathlib import Path

from trading_bot.ops_checks.commands import historical_bar_paper_validation_checks as checks


def _row(idx: int) -> dict:
    return {
        "symbol": "AAPL",
        "bar_timestamp": f"2026-06-01T10:{idx:02d}:00",
        "triple_barrier_label": 1 if idx % 2 == 0 else -1,
        "long_opportunity_score": 70.0 if idx % 3 == 0 else 50.0,
        "pattern_score": 68.0,
        "minute_of_day": 600 + idx,
    }


def test_walk_forward_reports_purged_embargoed_folds(monkeypatch):
    rows = [_row(idx) for idx in range(30)]

    def fake_fetch_historical_bar_training_rows(**_kwargs):
        return rows

    monkeypatch.setattr(
        checks,
        "fetch_historical_bar_training_rows",
        fake_fetch_historical_bar_training_rows,
    )

    payload = checks.build_historical_bar_walk_forward_payload(
        base_dir=Path("/tmp"),
        start_date="2026-06-01",
        end_date="2026-06-01",
        label_target="triple_barrier_label",
        rows_per_symbol=250,
        limit=1000,
        threshold=65.0,
        folds=3,
        purge_bars=2,
        embargo_bars=2,
    )

    assert payload["validation_method"] == checks.PURGED_WALK_FORWARD_METHOD
    assert payload["report_version"] == "historical_bar_purged_embargoed_walk_forward_v2"
    assert payload["purge_bars"] == 2
    assert payload["embargo_bars"] == 2
    assert len(payload["folds"]) == 3
    for fold in payload["folds"]:
        assert fold["validation_method"] == checks.PURGED_WALK_FORWARD_METHOD
        assert fold["test_rows"] == 10
        assert fold["train_rows"] > 0
        assert fold["purged_rows"] >= 0
        assert fold["embargoed_rows"] >= 0
