#!/usr/bin/env python3
"""
Tests for ml_platform/dataset_builder.py

Coverage:
  1. PIT contract validation            (4 tests)
  2. Row filtering                      (4 tests)
  3. Manifest field correctness         (5 tests)
  4. PIT archive injection              (3 tests)
  5. Label / result aggregates          (3 tests)
  6. Empty result handling              (1 test)
  7. Date range filter                  (1 test)
  Total: 21 tests
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_platform.dataset_builder import (
    FIXED_HORIZON_TARGETS,
    LABEL_VERSION,
    QUERY_VERSION,
    DatasetBuildConfig,
    build_training_dataset,
    validate_pit_contract,
)
from ml_platform.config import FEATURE_VERSION
from symbols_config import SYMBOL_UNIVERSE_VERSION


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_equal(actual, expected, label=""):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label=""):
    if not value:
        raise AssertionError(f"{label}: expected truthy, got {value!r}")


def assert_false(value, label=""):
    if value:
        raise AssertionError(f"{label}: expected falsy, got {value!r}")


def assert_in(value, container, label=""):
    if value not in container:
        raise AssertionError(f"{label}: {value!r} not in {container!r}")


def assert_ge(actual, minimum, label=""):
    if actual < minimum:
        raise AssertionError(f"{label}: expected >= {minimum}, got {actual!r}")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_FS_DDL = """
CREATE TABLE feature_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    last_price          REAL,
    ret_1m              REAL, ret_5m REAL, ret_15m REAL,
    range_pos_15m       REAL,
    distance_from_5m_high REAL, distance_from_5m_low REAL,
    distance_from_vwap  REAL,
    volume_ratio_5m     REAL,
    benchmark_symbol    TEXT, benchmark_ret_5m REAL,
    relative_strength_5m REAL, spread_pct REAL,
    market_session      TEXT, macro_regime TEXT,
    market_bias         TEXT, trend_direction TEXT, trend_strength TEXT,
    feature_available_at TEXT,
    feature_generated_at TEXT,
    feature_age_seconds  REAL,
    source               TEXT,
    is_stale             INTEGER DEFAULT 0,
    staleness_reason     TEXT,
    bar_timeframe       TEXT, bar_count INTEGER,
    setup_label         TEXT, setup_recommendation TEXT,
    setup_score         REAL, setup_confidence TEXT, setup_key TEXT
)
"""

_LS_DDL = """
CREATE TABLE labeled_setups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL,
    future_price_5m  REAL, future_price_15m REAL, future_price_30m REAL,
    ret_fwd_5m      REAL, ret_fwd_15m REAL, ret_fwd_30m REAL,
    max_up_15m      REAL, max_down_15m REAL,
    outcome_label   TEXT
)
"""

_CONTEXT_DDL = """
CREATE TABLE daily_symbol_context (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    market_date              TEXT NOT NULL,
    symbol                   TEXT NOT NULL,
    bias                     TEXT,
    confidence               TEXT,
    risk_level               TEXT,
    entry_quality            TEXT,
    catalyst_score           REAL,
    relative_strength_score  REAL,
    sector_alignment         TEXT,
    index_alignment          TEXT
)
"""

_PREDICTIONS_DDL = """
CREATE TABLE daily_symbol_predictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    market_date     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    prediction_score REAL,
    probability_of_profit REAL,
    probability_of_order  REAL,
    expected_pnl    REAL,
    confidence      TEXT,
    sample_size     INTEGER
)
"""

_BAR_PATTERN_DDL = """
CREATE TABLE bar_pattern_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    bar_timestamp TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    feature_version TEXT,
    candle_body_pct REAL,
    close_location REAL,
    range_atr_ratio REAL,
    volume_weighted_pressure_3 REAL,
    pattern_label TEXT,
    pattern_score REAL,
    opportunity_action TEXT,
    opportunity_quality TEXT,
    long_opportunity_score REAL,
    sell_opportunity_score REAL,
    triple_barrier_label INTEGER,
    triple_barrier_reason TEXT,
    triple_barrier_bars_to_event INTEGER,
    triple_barrier_profit_pct REAL,
    triple_barrier_stop_pct REAL
)
"""


def _create_tables(con: sqlite3.Connection) -> None:
    for ddl in (_FS_DDL, _LS_DDL, _CONTEXT_DDL, _PREDICTIONS_DDL, _BAR_PATTERN_DDL):
        con.execute(ddl)


def _insert_fs(con, *, ts, symbol, is_stale=0, staleness_reason=None,
               feature_available_at=None, last_price=100.0):
    """Insert one feature_snapshots row; return its rowid."""
    fa = feature_available_at or ts
    cur = con.execute(
        """
        INSERT INTO feature_snapshots
            (timestamp, symbol, last_price,
             feature_available_at, feature_generated_at,
             feature_age_seconds, source, is_stale, staleness_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ts, symbol, last_price, fa, fa, 0.0, "test", is_stale, staleness_reason),
    )
    return cur.lastrowid


def _insert_ls(con, *, snapshot_id, complete=True, outcome_label="win"):
    """Insert one labeled_setups row. complete=False → partial (ret_fwd_30m NULL)."""
    con.execute(
        """
        INSERT INTO labeled_setups
            (snapshot_id, future_price_5m, future_price_15m, future_price_30m,
             ret_fwd_5m, ret_fwd_15m, ret_fwd_30m,
             max_up_15m, max_down_15m, outcome_label)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            101.0, 102.0, 103.0 if complete else None,
            0.5,   1.0,   1.5 if complete else None,
            1.8,  -0.3,
            outcome_label,
        ),
    )


def _insert_bar_pattern(con, *, ts, symbol, label=1):
    con.execute(
        """
        INSERT INTO bar_pattern_features (
            symbol, bar_timestamp, timeframe, feature_version,
            candle_body_pct, close_location, range_atr_ratio,
            volume_weighted_pressure_3, pattern_label, pattern_score,
            opportunity_action, opportunity_quality,
            long_opportunity_score, sell_opportunity_score,
            triple_barrier_label, triple_barrier_reason,
            triple_barrier_bars_to_event, triple_barrier_profit_pct,
            triple_barrier_stop_pct
        ) VALUES (
            ?, ?, '1m', 'efi_pvt_candle_physics_bar_pattern_v2',
            0.6, 0.82, 1.25,
            0.33, 'constructive_candle_pressure', 72,
            'long_candidate', 'good_buy_window',
            80, 20,
            ?, 'profit_target_first',
            4, 0.5, 0.3
        )
        """,
        (symbol, ts, label),
    )


def _make_archive(base_dir: Path, date_str: str, archived_at: str) -> str:
    """Write a minimal PIT archive file; return archive_id (relative path stem)."""
    archive_dir = base_dir / "data_archive" / "point_in_time" / date_str
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts_safe = archived_at.replace(":", "").replace("-", "")[:15] + "Z"
    fname = f"context_state_{ts_safe}.json"
    payload = {
        "archived_at": archived_at,
        "archive_reason": "pre_session",
        "state_hash": "abc123",
        "symbol_universe_version": "test_v1",
        "runtime_files": {},
        "policy_artifacts": {},
        "policy_artifacts_full": {},
    }
    (archive_dir / fname).write_text(json.dumps(payload))
    return f"{date_str}/context_state_{ts_safe}"


# ---------------------------------------------------------------------------
# 1. PIT contract validation
# ---------------------------------------------------------------------------

def test_pit_contract_table_missing():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        result = validate_pit_contract(db_path)
    assert_false(result["table_exists"], "table_exists must be False")
    assert_false(result["ok"], "ok must be False when table absent")


def test_pit_contract_missing_audit_columns():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                "CREATE TABLE feature_snapshots (id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT)"
            )
        result = validate_pit_contract(db_path)
    assert_true(result["table_exists"], "table_exists")
    assert_false(result["ok"], "ok must be False when audit columns absent")
    assert_in("feature_available_at", result["missing_feature_audit_fields"], "missing field")
    assert_in("is_stale", result["missing_feature_audit_fields"], "missing is_stale")
    assert_in("staleness_reason", result["missing_feature_audit_fields"], "missing staleness_reason")


def test_pit_contract_clean_rows_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(_FS_DDL)
            _insert_fs(con, ts="2026-05-26T10:00:00", symbol="AAPL", is_stale=0)
        result = validate_pit_contract(db_path)
    assert_true(result["ok"], "ok must be True when all audit fields present")
    assert_equal(result["missing_feature_audit_fields"], [], "no missing fields")
    assert_equal(result["stale_feature_snapshot_count"], 0, "stale count")


def test_pit_contract_counts_stale_rows():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(_FS_DDL)
            _insert_fs(con, ts="2026-05-26T10:00:00", symbol="AAPL", is_stale=0)
            _insert_fs(con, ts="2026-05-26T10:01:00", symbol="NVDA", is_stale=1,
                       staleness_reason="feature_available_at > signal_time")
        result = validate_pit_contract(db_path)
    assert_true(result["ok"], "ok — audit columns present")
    assert_equal(result["stale_feature_snapshot_count"], 1, "stale_feature_snapshot_count")


# ---------------------------------------------------------------------------
# 2. Row filtering
# ---------------------------------------------------------------------------

def _filter_fixture(tmp_dir: Path) -> Path:
    """Seed: 1 complete, 1 partial_near_close, 1 unlabeled row."""
    db_path = tmp_dir / "test.db"
    with sqlite3.connect(db_path) as con:
        _create_tables(con)
        # Row 1 — complete
        ts1 = "2026-05-26T10:00:00"
        sid1 = _insert_fs(con, ts=ts1, symbol="AAPL")
        _insert_ls(con, snapshot_id=sid1, complete=True, outcome_label="win")
        _insert_bar_pattern(con, ts=ts1, symbol="AAPL")
        # Row 2 — partial_near_close (ret_fwd_30m NULL)
        sid2 = _insert_fs(con, ts="2026-05-26T10:30:00", symbol="NVDA")
        _insert_ls(con, snapshot_id=sid2, complete=False, outcome_label=None)
        # Row 3 — unlabeled (no labeled_setups row at all)
        _insert_fs(con, ts="2026-05-26T11:00:00", symbol="TSLA")
    return db_path


def test_complete_only_excludes_non_complete_rows():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _filter_fixture(Path(tmp))
        cfg = DatasetBuildConfig(
            start_date="2026-05-26", end_date="2026-05-26", db_path=db_path
        )
        result = build_training_dataset(cfg)
    symbols_out = {r["symbol"] for r in result.rows}
    assert_equal(symbols_out, {"AAPL"}, "only complete row exported")
    row = result.rows[0]
    assert_equal(row["candle_body_pct"], 0.6, "candle body exported")
    assert_equal(row["triple_barrier_label"], 1, "triple barrier target exported")
    assert_equal(
        row["bar_pattern_feature_version"],
        "efi_pvt_candle_physics_bar_pattern_v2",
        "bar pattern version exported",
    )


def test_complete_only_exclusion_reason_counts():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _filter_fixture(Path(tmp))
        cfg = DatasetBuildConfig(
            start_date="2026-05-26", end_date="2026-05-26", db_path=db_path
        )
        result = build_training_dataset(cfg)
    counts = result.excluded_reason_counts
    assert_equal(counts.get("partial_near_close", 0), 1, "partial_near_close count")
    assert_equal(counts.get("unlabeled", 0), 1, "unlabeled count")
    assert_false("complete" in counts, "complete rows are not in exclusion counts")


def test_include_incomplete_keeps_all_rows():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _filter_fixture(Path(tmp))
        cfg = DatasetBuildConfig(
            start_date="2026-05-26", end_date="2026-05-26", db_path=db_path,
            include_incomplete_labels=True,
        )
        result = build_training_dataset(cfg)
    assert_equal(len(result.rows), 3, "all rows kept in audit mode")


def test_export_row_count_invariant():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _filter_fixture(Path(tmp))
        for include in (False, True):
            cfg = DatasetBuildConfig(
                start_date="2026-05-26", end_date="2026-05-26", db_path=db_path,
                include_incomplete_labels=include,
            )
            result = build_training_dataset(cfg)
            assert_equal(
                result.export_row_count, len(result.rows),
                f"export_row_count == len(rows) [include_incomplete={include}]",
            )


# ---------------------------------------------------------------------------
# 3. Manifest field correctness
# ---------------------------------------------------------------------------

_REQUIRED_MANIFEST_FIELDS = [
    "dataset_id", "created_at", "source_db_hash",
    "query_version", "label_version", "feature_version",
    "row_count", "symbol_count", "date_range",
    "excluded_rows_reason_counts", "git_sha",
    "override_state_hash", "override_tracking_status",
    # Fields added by build_training_dataset
    "export_row_count", "source_row_count",
    "safe_training_targets", "pit_contract_ok",
    "symbol_universe_version",
]

_VALID_OVERRIDE_STATUSES = {
    "hashed_current_files_only",
    "no_override_files_present",
    "not_tracked",
}


def _manifest_fixture(tmp_dir: Path) -> tuple[Path, object]:
    db_path = _filter_fixture(tmp_dir)
    cfg = DatasetBuildConfig(
        start_date="2026-05-26", end_date="2026-05-26", db_path=db_path
    )
    return db_path, build_training_dataset(cfg)


def test_manifest_required_fields_present():
    with tempfile.TemporaryDirectory() as tmp:
        _, result = _manifest_fixture(Path(tmp))
    for field in _REQUIRED_MANIFEST_FIELDS:
        assert_in(field, result.manifest, f"manifest[{field!r}] present")
    assert_in("triple_barrier_label", result.manifest["safe_training_targets"], "triple target")
    assert_true(result.manifest["triple_barrier_target_included"], "triple target flag")


def test_manifest_export_row_count_matches_rows():
    with tempfile.TemporaryDirectory() as tmp:
        _, result = _manifest_fixture(Path(tmp))
    assert_equal(result.manifest["export_row_count"], len(result.rows),
                 "manifest.export_row_count == len(result.rows)")


def test_manifest_version_constants():
    with tempfile.TemporaryDirectory() as tmp:
        _, result = _manifest_fixture(Path(tmp))
    assert_equal(result.manifest["query_version"], QUERY_VERSION, "query_version")
    assert_equal(result.manifest["label_version"], LABEL_VERSION, "label_version")
    assert_equal(result.manifest["feature_version"], FEATURE_VERSION, "feature_version")


def test_manifest_symbol_universe_version():
    with tempfile.TemporaryDirectory() as tmp:
        _, result = _manifest_fixture(Path(tmp))
    assert_equal(result.manifest["symbol_universe_version"], SYMBOL_UNIVERSE_VERSION,
                 "symbol_universe_version matches symbols_config constant")


def test_manifest_override_tracking_status_never_unknown():
    with tempfile.TemporaryDirectory() as tmp:
        _, result = _manifest_fixture(Path(tmp))
    status = result.manifest.get("override_tracking_status")
    assert_true(status, "override_tracking_status must be non-empty")
    assert_in(status, _VALID_OVERRIDE_STATUSES,
              f"override_tracking_status is a known valid value (got {status!r})")


# ---------------------------------------------------------------------------
# 4. PIT archive injection
# ---------------------------------------------------------------------------

def _pit_db(tmp_dir: Path) -> Path:
    """Seed rows spanning three dates for archive injection tests."""
    db_path = tmp_dir / "test.db"
    with sqlite3.connect(db_path) as con:
        _create_tables(con)
        for ts, sym in [
            ("2026-05-26T10:00:00", "AAPL"),   # exact archive
            ("2026-05-27T10:00:00", "NVDA"),   # fallback from prior day
            ("2026-05-28T10:00:00", "TSLA"),   # no archive
        ]:
            sid = _insert_fs(con, ts=ts, symbol=sym)
            _insert_ls(con, snapshot_id=sid, complete=True, outcome_label="win")
    return db_path


def test_pit_injection_exact_archive():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = _pit_db(tmp_path)
        _make_archive(tmp_path, "2026-05-26", "2026-05-26T08:00:00Z")
        cfg = DatasetBuildConfig(
            start_date="2026-05-26", end_date="2026-05-26", db_path=db_path
        )
        result = build_training_dataset(cfg)
    assert_equal(len(result.rows), 1, "one complete row")
    row = result.rows[0]
    assert_true(row["pit_archive_id"] is not None, "pit_archive_id set for exact date")
    assert_equal(row["pit_coverage_status"], "exact", "pit_coverage_status=exact")


def test_pit_injection_missing_archive():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = _pit_db(tmp_path)
        # No archive created for 2026-05-28 and no prior dates either
        cfg = DatasetBuildConfig(
            start_date="2026-05-28", end_date="2026-05-28", db_path=db_path
        )
        result = build_training_dataset(cfg)
    assert_equal(len(result.rows), 1, "one complete row")
    row = result.rows[0]
    assert_true(row["pit_archive_id"] is None, "pit_archive_id is None when no archive")
    assert_equal(row["pit_coverage_status"], "missing", "pit_coverage_status=missing")


def test_pit_injection_fallback_archive():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = _pit_db(tmp_path)
        # Archive only for 2026-05-26; 2026-05-27 should fall back to it
        _make_archive(tmp_path, "2026-05-26", "2026-05-26T08:00:00Z")
        cfg = DatasetBuildConfig(
            start_date="2026-05-27", end_date="2026-05-27", db_path=db_path
        )
        result = build_training_dataset(cfg)
    assert_equal(len(result.rows), 1, "one complete row")
    row = result.rows[0]
    assert_true(row["pit_archive_id"] is not None,
                "pit_archive_id set even for fallback")
    assert_equal(row["pit_coverage_status"], "prior_date_fallback",
                 "pit_coverage_status=prior_date_fallback")


# ---------------------------------------------------------------------------
# 5. Label / result aggregates
# ---------------------------------------------------------------------------

def _aggregate_fixture(tmp_dir: Path) -> Path:
    """Seed: 2 AAPL wins + 1 AAPL loss + 1 NVDA win (all complete); 1 TSLA unlabeled."""
    db_path = tmp_dir / "test.db"
    with sqlite3.connect(db_path) as con:
        _create_tables(con)
        for i, (sym, label) in enumerate([
            ("AAPL", "win"), ("AAPL", "win"), ("AAPL", "loss"), ("NVDA", "win")
        ]):
            ts = f"2026-05-26T{10 + i:02d}:00:00"
            sid = _insert_fs(con, ts=ts, symbol=sym)
            _insert_ls(con, snapshot_id=sid, complete=True, outcome_label=label)
        # One unlabeled row
        _insert_fs(con, ts="2026-05-26T15:00:00", symbol="TSLA")
    return db_path


def test_labeled_rows_count():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _aggregate_fixture(Path(tmp))
        cfg = DatasetBuildConfig(
            start_date="2026-05-26", end_date="2026-05-26", db_path=db_path
        )
        result = build_training_dataset(cfg)
    # Only complete rows are exported by default; all 4 complete rows have outcome_label
    assert_equal(result.labeled_rows, 4, "labeled_rows counts rows with outcome_label")


def test_symbols_set_matches_exported_rows():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _aggregate_fixture(Path(tmp))
        cfg = DatasetBuildConfig(
            start_date="2026-05-26", end_date="2026-05-26", db_path=db_path
        )
        result = build_training_dataset(cfg)
    expected_symbols = {r["symbol"] for r in result.rows}
    assert_equal(result.symbols, expected_symbols, "result.symbols == exported row symbols")


def test_source_row_count_includes_all_label_statuses():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _aggregate_fixture(Path(tmp))
        cfg = DatasetBuildConfig(
            start_date="2026-05-26", end_date="2026-05-26", db_path=db_path
        )
        result = build_training_dataset(cfg)
    # 4 complete + 1 unlabeled = 5 source rows; only 4 exported in default mode
    assert_equal(result.source_row_count, 5, "source_row_count includes unlabeled rows")
    assert_equal(result.export_row_count, 4, "export_row_count is complete-only")
    assert_true(result.source_row_count > result.export_row_count,
                "source count > export count when unlabeled rows exist")


# ---------------------------------------------------------------------------
# 6. Empty result handling
# ---------------------------------------------------------------------------

def test_empty_date_range_never_raises():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            _create_tables(con)
        cfg = DatasetBuildConfig(
            start_date="2026-01-01", end_date="2026-01-31", db_path=db_path
        )
        result = build_training_dataset(cfg)
    assert_equal(result.rows, [], "rows is empty list")
    assert_equal(result.export_row_count, 0, "export_row_count is 0")
    assert_equal(result.source_row_count, 0, "source_row_count is 0")
    assert_equal(result.labeled_rows, 0, "labeled_rows is 0")
    assert_equal(result.symbols, set(), "symbols is empty set")
    assert_true(isinstance(result.manifest, dict), "manifest is still a dict")
    assert_in("dataset_id", result.manifest, "manifest has dataset_id even for empty result")


# ---------------------------------------------------------------------------
# 7. Date range filter
# ---------------------------------------------------------------------------

def test_date_range_excludes_out_of_range_rows():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            _create_tables(con)
            # Row inside range
            sid = _insert_fs(con, ts="2026-05-26T10:00:00", symbol="AAPL")
            _insert_ls(con, snapshot_id=sid, complete=True, outcome_label="win")
            # Row before range
            sid2 = _insert_fs(con, ts="2026-05-24T10:00:00", symbol="NVDA")
            _insert_ls(con, snapshot_id=sid2, complete=True, outcome_label="win")
            # Row after range
            sid3 = _insert_fs(con, ts="2026-05-28T10:00:00", symbol="TSLA")
            _insert_ls(con, snapshot_id=sid3, complete=True, outcome_label="win")
        cfg = DatasetBuildConfig(
            start_date="2026-05-26", end_date="2026-05-26", db_path=db_path
        )
        result = build_training_dataset(cfg)
    assert_equal(len(result.rows), 1, "only in-range row returned")
    assert_equal(result.rows[0]["symbol"], "AAPL", "in-range symbol")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main():
    tests = [
        # PIT contract validation
        test_pit_contract_table_missing,
        test_pit_contract_missing_audit_columns,
        test_pit_contract_clean_rows_accepted,
        test_pit_contract_counts_stale_rows,
        # Row filtering
        test_complete_only_excludes_non_complete_rows,
        test_complete_only_exclusion_reason_counts,
        test_include_incomplete_keeps_all_rows,
        test_export_row_count_invariant,
        # Manifest field correctness
        test_manifest_required_fields_present,
        test_manifest_export_row_count_matches_rows,
        test_manifest_version_constants,
        test_manifest_symbol_universe_version,
        test_manifest_override_tracking_status_never_unknown,
        # PIT archive injection
        test_pit_injection_exact_archive,
        test_pit_injection_missing_archive,
        test_pit_injection_fallback_archive,
        # Label / result aggregates
        test_labeled_rows_count,
        test_symbols_set_matches_exported_rows,
        test_source_row_count_includes_all_label_statuses,
        # Empty result
        test_empty_date_range_never_raises,
        # Date range filter
        test_date_range_excludes_out_of_range_rows,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"[OK] {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1

    print()
    if failed:
        print(f"{passed} passed, {failed} FAILED.")
        sys.exit(1)
    else:
        print(f"All {passed} dataset builder tests passed.")


if __name__ == "__main__":
    main()
