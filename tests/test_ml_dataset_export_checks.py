#!/usr/bin/env python3
"""Tests for canonical ML dataset export operator report."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trading_bot.ops_checks.commands.ml_dataset_checks import (
    run_ml_dataset_export_check,  # noqa: E402
)

_DATASET_BUILDER_TEST_PATH = ROOT / "tests" / "test_dataset_builder.py"
_spec = importlib.util.spec_from_file_location(
    "_dataset_builder_test_helpers",
    _DATASET_BUILDER_TEST_PATH,
)
_helpers = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_helpers)
_create_tables = _helpers._create_tables
_insert_fs = _helpers._insert_fs
_insert_ls = _helpers._insert_ls
_insert_bar_pattern = _helpers._insert_bar_pattern


def _build_dataset_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        _create_tables(con)
        ts = "2026-05-26T10:00:00"
        sid = _insert_fs(con, ts=ts, symbol="AAPL")
        _insert_ls(con, snapshot_id=sid, complete=True, outcome_label="win")
        _insert_bar_pattern(con, ts=ts, symbol="AAPL")


def test_ml_dataset_export_report_writes_csv_and_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _build_dataset_db(base_dir / "trades.db")
        output_path = base_dir / "exports" / "dataset.csv"
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = run_ml_dataset_export_check(
                "2026-05-26",
                end_date="2026-05-26",
                base_dir=base_dir,
                output_path=output_path,
                output_format="csv",
                min_rows=1,
                min_symbols=1,
            )
        with output_path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        manifest = json.loads(
            output_path.with_suffix(output_path.suffix + ".manifest.json").read_text()
        )

    out = buf.getvalue()
    assert ok is True
    assert "ml_dataset_export_check_v1" in out
    assert "export_rows             : 1" in out
    assert "training_dataset_ready  : True" in out
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["triple_barrier_label"] == "1"
    assert manifest["export_row_count"] == 1


def test_ml_dataset_export_warns_when_below_floor():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _build_dataset_db(base_dir / "trades.db")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = run_ml_dataset_export_check(
                "2026-05-26",
                end_date="2026-05-26",
                base_dir=base_dir,
                min_rows=2,
                min_symbols=2,
            )

    out = buf.getvalue()
    assert ok is False
    assert "training_dataset_ready  : False" in out
    assert "does not yet meet configured export floor" in out


if __name__ == "__main__":
    test_ml_dataset_export_report_writes_csv_and_manifest()
    print("[OK] test_ml_dataset_export_report_writes_csv_and_manifest")
    test_ml_dataset_export_warns_when_below_floor()
    print("[OK] test_ml_dataset_export_warns_when_below_floor")
    print("\nAll 2 ML dataset export check tests passed.")
