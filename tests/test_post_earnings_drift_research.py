#!/usr/bin/env python3
"""Tests for post-earnings drift research tooling."""

from __future__ import annotations

import json
import sqlite3

from scripts.post_earnings_drift_research import (
    _market_date,
    build_post_earnings_drift_payload,
    earnings_payload_to_features,
    main,
    validate_earnings_payloads,
)


def _build_db(path):
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                open REAL,
                close REAL
            )
            """
        )
        rows = [
            ("AAPL", "2026-06-14T20:59:00Z", "1m", 99.0, 100.0),
            ("AAPL", "2026-06-15T13:30:00Z", "1m", 105.0, 106.0),
            ("AAPL", "2026-06-15T20:00:00Z", "1m", 106.0, 107.0),
            ("AAPL", "2026-06-16T13:30:00Z", "1m", 107.0, 108.0),
            ("AAPL", "2026-06-16T20:00:00Z", "1m", 108.0, 109.0),
            ("MSFT", "2026-06-14T20:59:00Z", "1m", 199.0, 200.0),
            ("MSFT", "2026-06-15T13:30:00Z", "1m", 198.0, 197.0),
            ("MSFT", "2026-06-15T20:00:00Z", "1m", 197.0, 196.0),
            ("MSFT", "2026-06-16T13:30:00Z", "1m", 196.0, 195.0),
            ("MSFT", "2026-06-16T20:00:00Z", "1m", 195.0, 194.0),
        ]
        con.executemany("INSERT INTO bar_pattern_features VALUES (?, ?, ?, ?, ?)", rows)


def test_earnings_payload_to_features_expands_scalar_fields():
    features = earnings_payload_to_features(
        {
            "symbol": "aapl",
            "earnings_ts": "2026-06-14T21:00:00Z",
            "available_at": "2026-06-15T12:00:00Z",
            "source": "fixture",
            "report_timing": "before_open",
            "eps_surprise_pct": 8.5,
        }
    )

    names = {feature.feature_name for feature in features}
    assert "event_observed" in names
    assert "report_timing" in names
    assert "eps_surprise_pct" in names
    assert {feature.symbol for feature in features} == {"AAPL"}


def test_validate_earnings_payloads_requires_point_in_time_contract():
    result = validate_earnings_payloads(
        [
            {
                "symbol": "AAPL",
                "earnings_ts": "2026-06-14T21:00:00Z",
                "available_at": "2026-06-14T21:05:00Z",
                "source": "fixture",
                "eps_surprise_pct": 8.5,
            },
            {
                "symbol": "MSFT",
                "earnings_ts": "2026-06-14T21:00:00Z",
                "available_at": "2026-06-14T20:55:00Z",
                "source": "fixture",
            },
        ]
    )

    assert result["valid"] is False
    assert result["rows"] == 2
    assert result["rows_with_surprise_fields"] == 1
    assert result["errors"][0]["errors"] == ["available_at_before_event_timestamp"]


def test_validate_earnings_payloads_requires_canonical_utc_timestamps():
    result = validate_earnings_payloads(
        [
            {
                "symbol": "AAPL",
                "earnings_ts": "2026-06-14T17:00:00-04:00",
                "available_at": "2026-06-14T17:05:00-04:00",
                "source": "fixture",
                "eps_surprise_pct": 8.5,
            }
        ]
    )

    assert result["valid"] is False
    assert result["errors"][0]["errors"] == [
        "non_canonical_available_at_timestamp",
        "non_canonical_event_timestamp",
    ]


def test_market_date_uses_new_york_session_not_utc_date():
    assert _market_date("2026-06-16T00:30:00Z") == "2026-06-15"


def test_validate_jsonl_command_fails_invalid_input(tmp_path):
    input_path = tmp_path / "earnings.jsonl"
    input_path.write_text(json.dumps({"symbol": "AAPL", "source": "fixture"}) + "\n")

    rc = main(["validate-jsonl", "--input", str(input_path)])

    assert rc == 1


def test_post_earnings_drift_scan_labels_forward_sessions(tmp_path):
    db_path = tmp_path / "research.db"
    _build_db(db_path)
    input_path = tmp_path / "earnings.jsonl"
    input_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "symbol": "AAPL",
                        "earnings_ts": "2026-06-14T21:00:00Z",
                        "available_at": "2026-06-15T12:00:00Z",
                        "source": "fixture",
                        "report_timing": "before_open",
                        "eps_surprise_pct": 8.5,
                    }
                ),
                json.dumps(
                    {
                        "symbol": "MSFT",
                        "earnings_ts": "2026-06-14T21:00:00Z",
                        "available_at": "2026-06-15T12:00:00Z",
                        "source": "fixture",
                        "report_timing": "before_open",
                        "eps_surprise_pct": -4.0,
                    }
                ),
            ]
        )
        + "\n"
    )

    assert main(["--db-path", str(db_path), "ingest-jsonl", "--input", str(input_path)]) == 0
    payload, rows = build_post_earnings_drift_payload(
        db_path=db_path,
        start="2026-06-15",
        end="2026-06-16",
        horizon_sessions=2,
        min_rows=2,
        permutations=10,
        spread_pct=0.01,
        slippage_pct=0.01,
        account_equity=1000.0,
        max_position_pct=1.0,
    )

    assert payload["runtime_effect"] == "research_only_no_trade_authority"
    assert payload["events_seen"] == 2
    assert payload["events_labeled"] == 2
    assert len(rows) == 2
    by_symbol = {row.symbol: row for row in rows}
    assert by_symbol["AAPL"].forward_return_pct > 0
    assert by_symbol["MSFT"].forward_return_pct < 0
    assert "earnings.eps_surprise_pct" in by_symbol["AAPL"].numeric_features
    assert payload["ev"]["n"] == 2
    assert payload["symbol_cost_review"]["verdict"] == "provisional_no_symbol_costs"


def test_post_earnings_drift_scan_flags_symbol_level_cost_failures(tmp_path):
    db_path = tmp_path / "research.db"
    _build_db(db_path)
    input_path = tmp_path / "earnings.jsonl"
    input_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "symbol": "AAPL",
                        "earnings_ts": "2026-06-14T21:00:00Z",
                        "available_at": "2026-06-15T12:00:00Z",
                        "source": "fixture",
                        "eps_surprise_pct": 8.5,
                    }
                ),
                json.dumps(
                    {
                        "symbol": "MSFT",
                        "earnings_ts": "2026-06-14T21:00:00Z",
                        "available_at": "2026-06-15T12:00:00Z",
                        "source": "fixture",
                        "eps_surprise_pct": -4.0,
                    }
                ),
            ]
        )
        + "\n"
    )

    assert main(["--db-path", str(db_path), "ingest-jsonl", "--input", str(input_path)]) == 0
    payload, _rows = build_post_earnings_drift_payload(
        db_path=db_path,
        start="2026-06-15",
        end="2026-06-16",
        horizon_sessions=2,
        min_rows=2,
        permutations=10,
        spread_pct=0.01,
        slippage_pct=0.01,
        account_equity=1000.0,
        max_position_pct=1.0,
        symbol_costs={
            "AAPL": {"spread_pct": 0.01, "slippage_pct": 0.01, "reference_price": 100.0},
            "MSFT": {"spread_pct": 0.01, "slippage_pct": 0.01, "reference_price": 2000.0},
        },
    )

    review = payload["symbol_cost_review"]
    assert review["verdict"] == "fail"
    assert review["blocking_symbols"] == ["MSFT"]
    msft = next(item for item in review["symbols"] if item["symbol"] == "MSFT")
    assert msft["ev"]["verdict"] == "cannot_deploy_whole_share"
