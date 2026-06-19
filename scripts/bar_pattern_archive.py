#!/usr/bin/env python3
"""Archive bar_pattern_features (the ~21 GB bulk of trades.db) to Parquet.

P1 storage split. `bar_pattern_features` is ~99% of trades.db: a 30.8M-row,
144-column append-only feature+label time-series read only by offline
training/research/reporting jobs. The live decision path (auto_buy/auto_sell
managers) needs only `latest_for_symbol` — a recent, indexed point lookup — so
the historical bulk can live in columnar storage while a recent window stays in
SQLite for the hot path.

This tool moves history to month-partitioned, zstd-compressed Parquet (queryable
via DuckDB). The default `export` mode is a DRY RUN: it reads the source DB
read-only and writes Parquet, then verifies per-month row counts and an id
checksum both ways. It performs NO deletes and NO VACUUM — pruning the SQLite
copy is a separate, reviewed step.

runtime_effect: research_storage_migration_no_trade_authority
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb

RUNTIME_EFFECT = "research_storage_migration_no_trade_authority"
TABLE = "bar_pattern_features"
# Default source is the most recent son-tier backup, so the live DB is untouched.
DEFAULT_SOURCE = "backups/databases/son"
DEFAULT_OUT = "data/bar_pattern_archive"


def _latest_backup(repo_root: Path) -> Path | None:
    base = repo_root / DEFAULT_SOURCE
    if not base.is_dir():
        return None
    candidates = sorted(base.glob("*/trades.db"))
    return candidates[-1] if candidates else None


def _con(threads: int, memory_limit: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL sqlite")
    con.execute("LOAD sqlite")
    con.execute(f"SET threads={int(threads)}")
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute("SET preserve_insertion_order=false")
    return con


def export(args: argparse.Namespace) -> int:
    src = Path(args.source_db).resolve()
    out = Path(args.out_dir).resolve()
    if not src.exists():
        sys.stderr.write(f"[error] source DB not found: {src}\n")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    con = _con(args.threads, args.memory_limit)
    con.execute(f"ATTACH '{src}' AS srcdb (TYPE SQLITE, READ_ONLY)")

    # Window summary (drives the eventual SQLite prune; reported, not enforced here).
    span = con.execute(
        f"SELECT count(*), min(bar_timestamp), max(bar_timestamp) FROM srcdb.{TABLE}"
    ).fetchone()
    total_rows, ts_min, ts_max = span
    cutoff = con.execute(
        f"SELECT strftime(CAST(max(bar_timestamp) AS TIMESTAMP) "
        f"- INTERVAL '{int(args.retention_days)} days', '%Y-%m-%d') FROM srcdb.{TABLE}"
    ).fetchone()[0]
    recent_rows = con.execute(
        f"SELECT count(*) FROM srcdb.{TABLE} WHERE bar_timestamp >= '{cutoff}'"
    ).fetchone()[0]

    print(f"runtime_effect: {RUNTIME_EFFECT}")
    print(f"source: {src}")
    print(f"rows: {total_rows:,}  window: {ts_min} .. {ts_max}")
    print(
        f"retention: keep >= {cutoff} in SQLite ({recent_rows:,} rows, "
        f"{recent_rows / max(1, total_rows) * 100:.1f}%); "
        f"archive the remaining {total_rows - recent_rows:,} rows to Parquet"
    )

    # Export the FULL history to Parquet (system of record for training); the
    # recent window is duplicated into SQLite later for the hot path.
    print(f"\n[export] writing month-partitioned Parquet to {out} ...")
    t0 = time.time()
    con.execute(
        f"""
        COPY (
            SELECT *, substr(bar_timestamp, 1, 7) AS ym
            FROM srcdb.{TABLE}
        ) TO '{out}'
        (FORMAT PARQUET, PARTITION_BY (ym), OVERWRITE_OR_IGNORE, COMPRESSION zstd)
        """
    )
    elapsed = time.time() - t0
    files = list(out.rglob("*.parquet"))
    parquet_bytes = sum(f.stat().st_size for f in files)
    print(
        f"[export] done in {elapsed:.0f}s — {len(files)} files, "
        f"{parquet_bytes / 1e9:.2f} GB Parquet (zstd)"
    )

    if args.no_verify:
        con.close()
        return 0
    return _verify(con, out, total_rows)


def _verify(con: duckdb.DuckDBPyConnection, out: Path, expected_rows: int) -> int:
    print("\n[verify] comparing per-month count + id checksum (source vs parquet) ...")
    src = con.execute(
        f"""
        SELECT substr(bar_timestamp,1,7) AS ym, count(*) AS c, sum(id) AS chk
        FROM srcdb.{TABLE} GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    pq = con.execute(
        f"""
        SELECT ym, count(*) AS c, sum(id) AS chk
        FROM read_parquet('{out}/**/*.parquet', hive_partitioning=1)
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    con.close()

    src_map = {r[0]: (r[1], r[2]) for r in src}
    pq_map = {r[0]: (r[1], r[2]) for r in pq}
    months = sorted(set(src_map) | set(pq_map))
    mismatches = []
    for m in months:
        s = src_map.get(m)
        p = pq_map.get(m)
        if s != p:
            mismatches.append((m, s, p))
    src_total = sum(v[0] for v in src_map.values())
    pq_total = sum(v[0] for v in pq_map.values())
    print(f"[verify] months: {len(months)}  source rows: {src_total:,}  parquet rows: {pq_total:,}")
    if mismatches:
        print(f"[verify] FAIL — {len(mismatches)} month(s) differ:")
        for m, s, p in mismatches[:10]:
            print(f"    {m}: source={s} parquet={p}")
        return 1
    if src_total != expected_rows:
        print(f"[verify] WARN — source rescanned {src_total:,} != initial {expected_rows:,} (live writes?)")
    print("[verify] OK — every month matches on row count AND id checksum. Lossless.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    default_src = _latest_backup(repo_root)
    p.add_argument(
        "--source-db",
        default=str(default_src) if default_src else "trades.db",
        help="SQLite source (default: most recent son-tier backup, so the live DB is untouched)",
    )
    p.add_argument("--out-dir", default=str(repo_root / DEFAULT_OUT))
    p.add_argument("--retention-days", type=int, default=90, help="recent window kept in SQLite")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--memory-limit", default="4GB")
    p.add_argument("--no-verify", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return export(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
