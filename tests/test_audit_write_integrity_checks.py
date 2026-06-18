#!/usr/bin/env python3
"""End-to-end test for the audit-write-integrity ops_check command."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

from services import audit_write_integrity as awi  # noqa: E402
from trading_bot.ops_checks.commands.audit_write_integrity_checks import (  # noqa: E402
    run_audit_write_integrity,
)


def _make_db(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE auto_buy_candidates (id INTEGER PRIMARY KEY, timestamp TEXT)")
    con.execute("CREATE TABLE candidate_universe (id INTEGER PRIMARY KEY, candidate_ts TEXT)")
    con.execute(
        "CREATE TABLE bot_events (id INTEGER PRIMARY KEY, timestamp TEXT, event_type TEXT)"
    )
    con.executemany(
        "INSERT INTO auto_buy_candidates (timestamp) VALUES (?)",
        [("2026-06-18T10:00:00-04:00",), ("2026-06-18T10:01:00-04:00",)],
    )
    con.execute(
        "INSERT INTO candidate_universe (candidate_ts) VALUES ('2026-06-18T10:00:00-04:00')"
    )
    con.execute(
        "INSERT INTO bot_events (timestamp, event_type) "
        "VALUES ('2026-06-18 10:00:00', 'AUTO_BUY_CANDIDATE')"
    )
    con.commit()
    con.close()


def test_audit_write_integrity_command_reports_lossy(tmp_path, capsys):
    base_dir = tmp_path
    _make_db(base_dir / "trades.db")

    sidecar = awi.default_sidecar_path(base_dir)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    with sidecar.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "session", "date": "2026-06-18", "git_sha": "shaZ"}) + "\n")
        fh.write(
            json.dumps(
                {
                    "kind": "drop",
                    "date": "2026-06-18",
                    "stream": awi.STREAM_AUTO_BUY_SNAPSHOT,
                    "git_sha": "shaZ",
                }
            )
            + "\n"
        )

    ok = run_audit_write_integrity("2026-06-18", base_dir=base_dir)
    out = capsys.readouterr().out

    assert ok is True  # reportable, but fail-open pipeline stays "passing"
    assert "data_integrity: lossy" in out
    assert "dropped_audit_writes: 1" in out
    assert "frozen_logic_commit: shaZ" in out
    # written count for snapshots came from the DB (2 rows), expected = 2 + 1
    assert "auto_buy_snapshot" in out


def test_audit_write_integrity_command_missing_db_fails(tmp_path):
    ok = run_audit_write_integrity("2026-06-18", base_dir=tmp_path)
    assert ok is False


def main():
    import tempfile

    # Minimal smoke run without pytest fixtures.
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _make_db(base / "trades.db")
        ok = run_audit_write_integrity("2026-06-18", base_dir=base)
        assert ok is True
        print("[OK] test_audit_write_integrity_command smoke")
    print("\nAudit-write integrity command smoke test passed.")


if __name__ == "__main__":
    main()
