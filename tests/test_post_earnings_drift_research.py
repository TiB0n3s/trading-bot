#!/usr/bin/env python3
"""Tests for post-earnings drift research tooling."""

from __future__ import annotations

import json
import sqlite3

from scripts.post_earnings_drift_research import (
    DECILE_MIN_ROWS_DEFAULT,
    REGIME_MIN_ROWS_DEFAULT,
    _bootstrap_lift_ci,
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


# --- Amendment A1: power floors + bootstrap intervals for conditions 3 and 6 -------


def _build_multi_event_db(db_path, jsonl_path, *, n=40):
    """Generate ``n`` labeled earnings events whose forward return is monotonic in
    ``eps_surprise_pct``, alternating ``report_timing`` to create two regime buckets."""
    bars = []
    events = []
    for idx in range(n):
        symbol = f"SYM{idx:02d}"
        surprise = idx - (n - 1) / 2.0  # spans negative..positive, never zero for even n
        exit_close = 100.0 + surprise  # forward return sign == surprise sign
        timing = "before_open" if idx % 2 == 0 else "after_close"
        bars.extend(
            [
                (symbol, "2026-06-14T20:59:00Z", "1m", 99.0, 100.0),  # prior close
                (symbol, "2026-06-15T13:30:00Z", "1m", 100.0, 100.5),  # entry session
                (symbol, "2026-06-16T13:30:00Z", "1m", 100.0, exit_close),  # exit session
            ]
        )
        events.append(
            json.dumps(
                {
                    "symbol": symbol,
                    "earnings_ts": "2026-06-14T21:00:00Z",
                    "available_at": "2026-06-15T12:00:00Z",
                    "source": "fixture",
                    "report_timing": timing,
                    "eps_surprise_pct": surprise,
                }
            )
        )
    with sqlite3.connect(db_path) as con:
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
        con.executemany("INSERT INTO bar_pattern_features VALUES (?, ?, ?, ?, ?)", bars)
    jsonl_path.write_text("\n".join(events) + "\n")
    assert main(["--db-path", str(db_path), "ingest-jsonl", "--input", str(jsonl_path)]) == 0


def test_bootstrap_lift_ci_requires_interval_to_clear_bar():
    # Return is monotonic in the feature value -> top decile all wins, bottom all losses.
    strong = [(float(v), float(v)) for v in range(-30, 30)]
    strong_ci = _bootstrap_lift_ci(strong, n_buckets=10, resamples=300, seed=1)
    assert strong_ci is not None
    assert strong_ci["point_lift_pct"] >= 8.0
    assert strong_ci["ci_low_pct"] >= 8.0
    assert strong_ci["ci_clears_bar"] is True
    assert strong_ci["direction_stable"] is True

    # Sign of the return is independent of feature order -> lift hugs zero.
    flat = [(float(v), 1.0 if v % 2 == 0 else -1.0) for v in range(60)]
    flat_ci = _bootstrap_lift_ci(flat, n_buckets=10, resamples=300, seed=1)
    assert flat_ci is not None
    assert flat_ci["ci_low_pct"] < 0.0 < flat_ci["ci_high_pct"]  # interval straddles zero
    assert flat_ci["ci_clears_bar"] is False
    assert flat_ci["direction_stable"] is False


def test_bootstrap_lift_ci_returns_none_below_decile_floor():
    # Fewer than n_buckets * 3 rows: no interval can be formed (same floor the scan uses).
    too_few = [(float(v), float(v)) for v in range(20)]
    assert _bootstrap_lift_ci(too_few, n_buckets=10, resamples=300, seed=1) is None
    assert _bootstrap_lift_ci(too_few, n_buckets=10, resamples=0, seed=1) is None


def test_power_floors_are_clamped_up_to_aggregate_floor(tmp_path):
    db_path = tmp_path / "research.db"
    _build_db(db_path)  # tiny fixture; scans will report too few rows, that is fine
    # Sub-floors below the aggregate floor must be clamped UP, never applied as-is.
    payload, _rows = build_post_earnings_drift_payload(
        db_path=db_path,
        start="2026-06-15",
        end="2026-06-16",
        horizon_sessions=2,
        min_rows=50,
        permutations=10,
        spread_pct=0.01,
        slippage_pct=0.01,
        account_equity=1000.0,
        max_position_pct=1.0,
        decile_min_rows=5,
        regime_min_rows=5,
    )
    floors = payload["power_floors"]
    assert floors["aggregate_min_rows"] == 50
    assert floors["decile_min_rows"] == 50  # clamped up from 5
    assert floors["regime_min_rows"] == 50  # clamped up from 5
    assert floors["lift_bar_pct"] == 8.0


def test_decile_floor_blocks_thin_decile_lift_then_passes_when_lowered(tmp_path):
    db_path = tmp_path / "research.db"
    jsonl_path = tmp_path / "earnings.jsonl"
    _build_multi_event_db(db_path, jsonl_path, n=40)

    common = dict(
        db_path=db_path,
        start="2026-06-15",
        end="2026-06-16",
        horizon_sessions=2,
        permutations=50,
        spread_pct=0.01,
        slippage_pct=0.01,
        account_equity=1_000_000.0,
        max_position_pct=1.0,
        bootstrap_resamples=200,
    )

    # 40 events < default decile floor (100): condition-3 magnitude cannot be read.
    high, _ = build_post_earnings_drift_payload(min_rows=30, **common)
    assert high["events_labeled"] == 40
    assert high["power_floors"]["decile_min_rows"] == DECILE_MIN_ROWS_DEFAULT
    assert all(item["lift_pct"] is None for item in high["feature_scan"])
    assert high["decile_lift_ci"] is None

    # Lower the decile floor below the sample: the monotonic signal now clears the bar,
    # and the bootstrap interval (not just the point estimate) clears it too.
    low, _ = build_post_earnings_drift_payload(min_rows=30, decile_min_rows=30, **common)
    assert low["power_floors"]["decile_min_rows"] == 30
    top = low["feature_scan"][0]
    assert top["feature"] == "earnings.eps_surprise_pct"
    assert abs(top["lift_pct"]) >= 8.0
    ci = low["decile_lift_ci"]
    assert ci is not None
    assert ci["feature"] == "earnings.eps_surprise_pct"
    assert ci["ci_clears_bar"] is True


def test_regime_floor_gates_directional_coherence(tmp_path):
    db_path = tmp_path / "research.db"
    jsonl_path = tmp_path / "earnings.jsonl"
    _build_multi_event_db(db_path, jsonl_path, n=120)  # 60 rows per regime bucket

    common = dict(
        db_path=db_path,
        start="2026-06-15",
        end="2026-06-16",
        horizon_sessions=2,
        min_rows=30,
        permutations=50,
        spread_pct=0.01,
        slippage_pct=0.01,
        account_equity=1_000_000.0,
        max_position_pct=1.0,
        decile_min_rows=30,
        bootstrap_resamples=200,
    )

    # Default regime floor (60): both 60-row buckets qualify and each direction is
    # CI-stable (the interval does not straddle zero).
    ok, _ = build_post_earnings_drift_payload(**common)
    assert ok["power_floors"]["regime_min_rows"] == REGIME_MIN_ROWS_DEFAULT
    assert {item["regime"] for item in ok["regime_scan"]} == {"before_open", "after_close"}
    ci = ok["regime_direction_ci"]
    assert len(ci) == 2
    assert all(item["direction_stable"] is True for item in ci)

    # Raise the regime floor above the bucket size: no bucket qualifies, so condition 6
    # can only pass vacuously ("no qualifying regime bucket"), never on a thin bucket.
    gated, _ = build_post_earnings_drift_payload(regime_min_rows=80, **common)
    assert gated["power_floors"]["regime_min_rows"] == 80
    assert gated["regime_scan"] == []
    assert gated["regime_direction_ci"] == []
