#!/usr/bin/env python3
"""Archive cold ML learning rows into separate SQLite stores.

This command is intentionally conservative:

* actual trade/fill tables are never archived or deleted;
* cold historical-bar features require historical-bar training evidence unless
  explicitly bypassed;
* all moves are chunked and recorded in a manifest;
* dry-run is the default.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import default_market_date  # noqa: E402
from ml_platform.config import DEFAULT_DB_PATH, MODEL_ROOT  # noqa: E402

ARCHIVE_ROOT = BASE_DIR / "data_archive" / "sqlite"
MANIFEST_ROOT = BASE_DIR / "data_archive" / "manifests"
TRAINING_HOOK_STATE = BASE_DIR / "runtime_state" / "historical_bar_training_hook_state.json"


@dataclass(frozen=True)
class ArchivePlan:
    table: str
    date_column: str
    archive_name: str
    retention_days: int
    reason: str
    requires_historical_bar_training: bool = False
    # Safety valve: when training-evidence gating would block archival, still archive
    # rows older than this ceiling (None disables). Archived rows stay model-consumable
    # from the archive, so this only bounds growth -- it never deprives a (lagging)
    # training run of recent data. Must be >= retention_days.
    force_archive_after_days: int | None = None


# Hard ceiling for bar_pattern_features when the historical-bar training hook is not
# ready (e.g. it is observe-only/unpromoted or a transient backfill error left it
# not_ready). Without this, eligible rows are blocked indefinitely and trades.db
# grows unbounded. Env-tunable for ops.
try:
    BAR_PATTERN_FORCE_ARCHIVE_DAYS = int(
        os.environ.get("OPS_BAR_PATTERN_FORCE_ARCHIVE_DAYS", "30")
    )
except (TypeError, ValueError):
    BAR_PATTERN_FORCE_ARCHIVE_DAYS = 30


ARCHIVE_PLANS: tuple[ArchivePlan, ...] = (
    ArchivePlan(
        table="bar_pattern_features",
        date_column="bar_timestamp",
        archive_name="historical_bars.db",
        retention_days=5,
        reason="cold historical bar features stay model-consumable from archive",
        requires_historical_bar_training=True,
        force_archive_after_days=BAR_PATTERN_FORCE_ARCHIVE_DAYS,
    ),
    ArchivePlan(
        table="feature_snapshots",
        date_column="timestamp",
        archive_name="features.db",
        retention_days=10,
        reason="keep 10 days of hot feature snapshots in trades.db",
    ),
    ArchivePlan(
        table="decision_snapshots",
        date_column="decision_time",
        archive_name="learning_archive.db",
        retention_days=30,
        reason="keep 30 days of hot decision snapshots in trades.db",
    ),
    ArchivePlan(
        table="auto_buy_decision_snapshots",
        date_column="candidate_timestamp",
        archive_name="learning_archive.db",
        retention_days=30,
        reason="keep 30 days of hot auto-buy decision telemetry in trades.db",
    ),
    ArchivePlan(
        table="auto_sell_decision_snapshots",
        date_column="candidate_timestamp",
        archive_name="learning_archive.db",
        retention_days=30,
        reason="keep 30 days of hot auto-sell decision telemetry in trades.db",
    ),
    ArchivePlan(
        table="candidate_universe",
        date_column="candidate_ts",
        archive_name="learning_archive.db",
        retention_days=30,
        reason="keep 30 days of hot candidate-discovery telemetry in trades.db",
    ),
)

PROTECTED_TABLES = {
    "trades",
    "matched_trades",
    "fill_events",
    "trade_fills",
    "orders",
    "positions",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _quote_identifier(name: str) -> str:
    if not name or "\x00" in name:
        raise ValueError(f"invalid SQLite identifier: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def _cutoff(target_date: date, retention_days: int) -> str:
    return (target_date - timedelta(days=retention_days)).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA foreign_keys=OFF")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _columns(con: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(con.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall())


def _date_column_exists(con: sqlite3.Connection, table: str, date_column: str) -> bool:
    return any(str(row["name"]) == date_column for row in _columns(con, table))


def _ensure_archive_table(
    con: sqlite3.Connection,
    *,
    table: str,
    archive_schema: str = "archive",
) -> None:
    source_columns = _columns(con, table)
    if not source_columns:
        raise RuntimeError(f"source table has no columns: {table}")
    col_defs = [
        "_source_rowid INTEGER NOT NULL",
        "_archived_at TEXT NOT NULL",
        "_archive_run_id TEXT NOT NULL",
    ]
    for row in source_columns:
        name = _quote_identifier(str(row["name"]))
        col_type = str(row["type"] or "TEXT")
        col_defs.append(f"{name} {col_type}")
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_quote_identifier(archive_schema)}.{_quote_identifier(table)}
        ({", ".join(col_defs)})
        """
    )


def _eligible_count(con: sqlite3.Connection, plan: ArchivePlan, cutoff: str) -> int:
    if not _table_exists(con, plan.table):
        return 0
    if not _date_column_exists(con, plan.table, plan.date_column):
        return 0
    row = con.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM {_quote_identifier(plan.table)}
        WHERE {_quote_identifier(plan.date_column)} < ?
        """,
        (cutoff,),
    ).fetchone()
    return int(row["n"] if row else 0)


def _archive_chunk(
    *,
    con: sqlite3.Connection,
    plan: ArchivePlan,
    cutoff: str,
    chunk_size: int,
    archived_at: str,
    run_id: str,
    archive_schema: str = "archive",
) -> int:
    source_columns = [str(row["name"]) for row in _columns(con, plan.table)]
    quoted_columns = ", ".join(_quote_identifier(col) for col in source_columns)
    archive_columns = ", ".join(
        ["_source_rowid", "_archived_at", "_archive_run_id"]
        + [_quote_identifier(col) for col in source_columns]
    )
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _cold_archive_rowids(rowid INTEGER PRIMARY KEY)"
        )
        con.execute("DELETE FROM _cold_archive_rowids")
        con.execute(
            f"""
            INSERT INTO _cold_archive_rowids(rowid)
            SELECT rowid
            FROM {_quote_identifier(plan.table)}
            WHERE {_quote_identifier(plan.date_column)} < ?
            ORDER BY {_quote_identifier(plan.date_column)} ASC, rowid ASC
            LIMIT ?
            """,
            (cutoff, chunk_size),
        )
        selected = int(con.execute("SELECT COUNT(*) FROM _cold_archive_rowids").fetchone()[0])
        if selected:
            con.execute(
                f"""
                INSERT INTO {_quote_identifier(archive_schema)}.{_quote_identifier(plan.table)}
                ({archive_columns})
                SELECT rowid, ?, ?, {quoted_columns}
                FROM {_quote_identifier(plan.table)}
                WHERE rowid IN (SELECT rowid FROM _cold_archive_rowids)
                ORDER BY rowid ASC
                """,
                (archived_at, run_id),
            )
            con.execute(
                f"""
                DELETE FROM {_quote_identifier(plan.table)}
                WHERE rowid IN (SELECT rowid FROM _cold_archive_rowids)
                """
            )
        con.commit()
        return selected
    except Exception:
        con.rollback()
        raise


def _diagnostic_is_trained(payload: dict[str, Any]) -> bool:
    training = payload.get("training") or {}
    return training.get("trained") is True and int(training.get("sample_size") or 0) > 0


def _latest_diagnostic(
    label_target: str, *, require_trained: bool = False
) -> dict[str, Any] | None:
    root = MODEL_ROOT / "historical_bar_patterns_v1" / "candidates"
    if not root.exists():
        return None
    paths = sorted(root.glob(f"historical_bar_{label_target}_*.diagnostic.json"))
    for path in reversed(paths):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if require_trained and not _diagnostic_is_trained(payload):
            continue
        payload["_path"] = str(path)
        return payload
    return None


def _training_evidence() -> dict[str, Any]:
    hook: dict[str, Any] = {}
    if TRAINING_HOOK_STATE.exists():
        try:
            hook = json.loads(TRAINING_HOOK_STATE.read_text(encoding="utf-8"))
        except Exception as exc:
            hook = {"error": str(exc)}
    diagnostics = {
        label: _latest_diagnostic(label, require_trained=True)
        for label in ("triple_barrier_label", "trend_scan_label")
    }
    ready = hook.get("last_status") == "trained" and hook.get("last_retrain_exit_code") == 0
    diagnostic_ready = True
    for payload in diagnostics.values():
        if not payload:
            diagnostic_ready = False
            continue
        training = payload.get("training") or {}
        if training.get("trained") is not True or int(training.get("sample_size") or 0) <= 0:
            diagnostic_ready = False
    return {
        "ready": bool(ready and diagnostic_ready),
        "hook_state_path": str(TRAINING_HOOK_STATE),
        "hook_status": hook.get("last_status"),
        "hook_exit_code": hook.get("last_retrain_exit_code"),
        "hook_updated_at": hook.get("updated_at"),
        "diagnostics": {
            label: {
                "path": payload.get("_path") if payload else None,
                "generated_at": payload.get("generated_at") if payload else None,
                "rows_loaded": payload.get("rows_loaded") if payload else None,
                "trained": (payload.get("training") or {}).get("trained") if payload else None,
                "sample_size": (payload.get("training") or {}).get("sample_size")
                if payload
                else None,
            }
            for label, payload in diagnostics.items()
        },
    }


def run_archive(
    *,
    db_path: Path,
    archive_root: Path,
    target_date: date,
    execute: bool,
    chunk_size: int,
    max_chunks: int,
    skip_training_evidence: bool,
    selected_tables: set[str] | None,
) -> dict[str, Any]:
    run_id = _utc_now().strftime("cold_learning_archive_%Y%m%dT%H%M%SZ")
    archived_at = _utc_now().isoformat()
    archive_root.mkdir(parents=True, exist_ok=True)
    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
    evidence = _training_evidence()

    manifest: dict[str, Any] = {
        "version": "cold_learning_archive_v1",
        "run_id": run_id,
        "db_path": str(db_path),
        "archive_root": str(archive_root),
        "target_date": target_date.isoformat(),
        "execute": execute,
        "chunk_size": chunk_size,
        "max_chunks": max_chunks,
        "protected_tables": sorted(PROTECTED_TABLES),
        "training_evidence": evidence,
        "tables": [],
        "started_at": archived_at,
    }

    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    with _connect(db_path) as con:
        for plan in ARCHIVE_PLANS:
            if selected_tables and plan.table not in selected_tables:
                continue
            if plan.table in PROTECTED_TABLES:
                raise RuntimeError(f"protected table cannot be archived: {plan.table}")
            cutoff = _cutoff(target_date, plan.retention_days)
            table_result: dict[str, Any] = {
                **asdict(plan),
                "cutoff_exclusive": cutoff,
                "archive_path": str(archive_root / plan.archive_name),
                "eligible_before": 0,
                "archived_rows": 0,
                "status": "pending",
            }
            if not _table_exists(con, plan.table):
                table_result["status"] = "missing_table"
                manifest["tables"].append(table_result)
                continue
            if not _date_column_exists(con, plan.table, plan.date_column):
                table_result["status"] = "missing_date_column"
                manifest["tables"].append(table_result)
                continue
            if (
                plan.requires_historical_bar_training
                and not skip_training_evidence
                and not evidence["ready"]
            ):
                # Training evidence is not ready. Rather than block ALL eligible rows
                # indefinitely (unbounded trades.db growth), fall back to the
                # force-archive ceiling: keep the recent window hot in case training
                # catches up, but still archive rows older than the ceiling (they stay
                # model-consumable from the archive). If no ceiling is configured,
                # preserve the original hard block.
                if not plan.force_archive_after_days:
                    table_result["status"] = "blocked_missing_training_evidence"
                    table_result["eligible_before"] = _eligible_count(con, plan, cutoff)
                    manifest["tables"].append(table_result)
                    continue
                force_days = max(int(plan.force_archive_after_days), plan.retention_days)
                cutoff = _cutoff(target_date, force_days)
                table_result["training_evidence_not_ready"] = True
                table_result["force_archive_after_days"] = force_days
                table_result["cutoff_exclusive"] = cutoff
            eligible = _eligible_count(con, plan, cutoff)
            table_result["eligible_before"] = eligible
            if not execute:
                table_result["status"] = "dry_run"
                manifest["tables"].append(table_result)
                continue
            if eligible <= 0:
                table_result["status"] = "no_eligible_rows"
                manifest["tables"].append(table_result)
                continue
            archive_path = archive_root / plan.archive_name
            con.execute("ATTACH DATABASE ? AS archive", (str(archive_path),))
            try:
                _ensure_archive_table(con, table=plan.table)
                con.commit()
                chunks = 0
                while True:
                    if max_chunks and chunks >= max_chunks:
                        table_result["status"] = "max_chunks_reached"
                        break
                    moved = _archive_chunk(
                        con=con,
                        plan=plan,
                        cutoff=cutoff,
                        chunk_size=chunk_size,
                        archived_at=archived_at,
                        run_id=run_id,
                    )
                    if moved <= 0:
                        table_result["status"] = "archived"
                        break
                    chunks += 1
                    table_result["archived_rows"] += moved
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS archive.archive_runs (
                        run_id TEXT PRIMARY KEY,
                        archived_at TEXT NOT NULL,
                        manifest_json TEXT NOT NULL
                    )
                    """
                )
                con.commit()
            finally:
                con.execute("DETACH DATABASE archive")
            manifest["tables"].append(table_result)

    manifest["finished_at"] = _utc_now().isoformat()
    manifest_path = MANIFEST_ROOT / f"{run_id}.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    parser.add_argument("--target-date", default=default_market_date())
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--max-chunks", type=int, default=0, help="0 means no chunk cap")
    parser.add_argument("--execute", action="store_true", help="Move and delete eligible rows")
    parser.add_argument(
        "--skip-training-evidence",
        action="store_true",
        help="Allow historical-bar archival without current training evidence",
    )
    parser.add_argument(
        "--table",
        action="append",
        dest="tables",
        help="Archive only this table; may be repeated",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    target_date = date.fromisoformat(str(args.target_date))
    manifest = run_archive(
        db_path=Path(args.db_path),
        archive_root=Path(args.archive_root),
        target_date=target_date,
        execute=bool(args.execute),
        chunk_size=max(1, int(args.chunk_size)),
        max_chunks=max(0, int(args.max_chunks)),
        skip_training_evidence=bool(args.skip_training_evidence),
        selected_tables=set(args.tables) if args.tables else None,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    blocked = [
        row for row in manifest["tables"] if str(row.get("status") or "").startswith("blocked_")
    ]
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
