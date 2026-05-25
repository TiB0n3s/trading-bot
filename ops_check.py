#!/usr/bin/env python3
"""
Operator check wrapper.

Usage:
  python3 ops_check.py morning
  python3 ops_check.py positions
  python3 ops_check.py alignment
  python3 ops_check.py adaptive
  python3 ops_check.py filters
  python3 ops_check.py drawdown
  python3 ops_check.py post
  python3 ops_check.py intelligence
  python3 ops_check.py events
  python3 ops_check.py context
  python3 ops_check.py learning
  python3 ops_check.py predictions
  python3 ops_check.py signal-lessons
  python3 ops_check.py trends
  python3 ops_check.py prediction-validation
  python3 ops_check.py bot-events
  python3 ops_check.py event-attribution
  python3 ops_check.py premarket
  python3 ops_check.py market-context-check
  python3 ops_check.py intelligence-summary
  python3 ops_check.py dataset-health
  python3 ops_check.py feature-health
  python3 ops_check.py feature-watch
  python3 ops_check.py rejection-summary
  python3 ops_check.py order-health
  python3 ops_check.py migration-status
  python3 ops_check.py all
  python3 ops_check.py filters 2026-05-08
"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")


def reexec_under_venv_if_available():
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


reexec_under_venv_if_available()


def load_env_file(path=ENV_FILE):
    if not path.exists():
        return False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value

    return True


COMMANDS = {
    "morning": ["morning_check.py"],
    "positions": ["position_review.py"],
    "alignment": ["market_alignment_report.py"],
    "adaptive": ["adaptive_confirmation_report.py"],
    "adaptive_impact": ["adaptive_impact_report.py"],
    "strategy_intelligence": ["strategy_intelligence_report.py"],
    "blocked": ["blocked_signal_outcome_report.py", "--date"],
    "session": ["session_momentum.py", "--all"],
    "position-momentum": ["position_momentum_monitor.py"],
    "filters": ["filter_report.py", "--date"],
    "drawdown": ["drawdown_report.py"],
    "post": ["post_session_check.py"],
    "events": ["bot_events.py", "--limit", "25"],
    "bot-events": ["bot_events.py", "--limit", "25"],
    "event-attribution": ["event_attribution_report.py", "--date"],
    "intelligence": ["intelligence_context_report.py", "--date"],
    "context": ["context_trade_join_report.py", "--date"],
    "learning": ["intelligence_learning_report.py", "--date"],
    "predictions": ["intelligence_prediction_report.py", "--date"],
    "signal-lessons": ["signal_timing_lesson_report.py", "--date"],
    "trends": ["trend_context_report.py", "--date"],
    "prediction-validation": ["prediction_validation_report.py", "--date"],
}


def run(label, args):
    print()
    print("=" * 72)
    print(f"  {label}")
    print("=" * 72)

    try:
        r = subprocess.run(
            [sys.executable] + args,
            cwd=BASE_DIR,
            text=True,
            timeout=180,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"[FAIL] {label} failed: {e}")
        return False


def check_market_context_file():
    import json

    path = BASE_DIR / "market_context.json"

    print()
    print("=" * 72)
    print("  Market Context Check")
    print("=" * 72)

    if not path.exists():
        print(f"[FAIL] missing {path}")
        return False

    try:
        data = json.loads(path.read_text())
    except Exception as e:
        print(f"[FAIL] could not parse {path}: {e}")
        return False

    required_top = {
        "market_date",
        "macro_sentiment",
        "macro_summary",
        "symbols",
    }

    required_symbol = {
        "bias",
        "reason",
        "confidence",
        "fundamental_score",
        "risk_level",
        "entry_quality",
        "avoid_type",
    }

    ok = True

    missing_top = sorted(required_top - set(data.keys()))
    if missing_top:
        print(f"[FAIL] missing top-level fields: {missing_top}")
        ok = False

    market_date = data.get("market_date")
    source = data.get("source")
    fmt = data.get("format")
    symbols = data.get("symbols") or {}

    print(f"market_date : {market_date}")
    print(f"source      : {source}")
    print(f"format      : {fmt}")
    print(f"symbols     : {len(symbols)}")
    print(f"macro       : {data.get('macro_sentiment')}")
    print(f"regime      : {data.get('macro_regime')}")
    print(f"risk_mult   : {data.get('risk_multiplier')}")
    print(f"max_pos     : {data.get('max_new_positions')}")
    print(f"block_buys  : {data.get('block_new_buys')}")

    if not isinstance(symbols, dict) or not symbols:
        print("[FAIL] symbols is empty or not an object")
        return False

    bad_symbols = []
    avoid_type_errors = []
    bias_counts = {}

    for sym, entry in symbols.items():
        entry = entry or {}
        bias = entry.get("bias", "missing")
        bias_counts[bias] = bias_counts.get(bias, 0) + 1

        missing = sorted(required_symbol - set(entry.keys()))
        if missing:
            bad_symbols.append((sym, missing))

        avoid_type = entry.get("avoid_type")
        if bias != "avoid" and avoid_type is not None:
            avoid_type_errors.append((sym, bias, avoid_type))

    print(f"bias_counts : {bias_counts}")

    if bad_symbols:
        print("[FAIL] symbols missing required fields:")
        for sym, missing in bad_symbols[:25]:
            print(f"  {sym}: {missing}")
        ok = False
    else:
        print("[OK] required per-symbol fields present")

    if avoid_type_errors:
        print("[FAIL] avoid_type set on non-avoid symbols:")
        for sym, bias, avoid_type in avoid_type_errors[:25]:
            print(f"  {sym}: bias={bias} avoid_type={avoid_type}")
        ok = False
    else:
        print("[OK] avoid_type only set for avoid symbols")

    if source != "market_brief_builder":
        print(f"[WARN] source is not market_brief_builder: {source}")

    if fmt != "rich_market_brief_v1":
        print(f"[WARN] format is not rich_market_brief_v1: {fmt}")

    if ok:
        print("[OK] market_context.json schema check passed")
    else:
        print("[FAIL] market_context.json schema check failed")

    return ok


def intelligence_summary(target_date):
    import sqlite3

    db_path = BASE_DIR / "trades.db"

    print()
    print("=" * 72)
    print(f"  Intelligence Summary — {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    ok = True

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        context_count = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM daily_symbol_context
            WHERE market_date = ?
            """,
            (target_date,),
        ).fetchone()["n"]

        event_count = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM daily_symbol_events
            WHERE market_date = ?
            """,
            (target_date,),
        ).fetchone()["n"]

        prediction_count = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM daily_symbol_predictions
            WHERE market_date = ?
            """,
            (target_date,),
        ).fetchone()["n"]

        print(f"context rows    : {context_count}")
        print(f"event rows      : {event_count}")
        print(f"prediction rows : {prediction_count}")

        freshness = con.execute(
            """
            SELECT
              (SELECT MAX(created_at)
               FROM daily_symbol_events
               WHERE market_date = ?) AS latest_event_at,
              (SELECT MAX(updated_at)
               FROM daily_symbol_context
               WHERE market_date = ?) AS latest_context_at,
              (SELECT MAX(updated_at)
               FROM daily_symbol_predictions
               WHERE market_date = ?) AS latest_prediction_at
            """,
            (target_date, target_date, target_date),
        ).fetchone()

        print()
        print("Freshness")
        print(f"  latest event      : {freshness['latest_event_at'] or '-'}")
        print(f"  latest context    : {freshness['latest_context_at'] or '-'}")
        print(f"  latest prediction : {freshness['latest_prediction_at'] or '-'}")

        print()
        print("Bias counts")
        rows = con.execute(
            """
            SELECT COALESCE(bias, 'missing') AS bias, COUNT(*) AS n
            FROM daily_symbol_context
            WHERE market_date = ?
            GROUP BY COALESCE(bias, 'missing')
            ORDER BY bias
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  {r['bias']:<10} {r['n']}")
        else:
            print("  none")

        print()
        print("Prediction confidence")
        rows = con.execute(
            """
            SELECT COALESCE(confidence, 'missing') AS confidence, COUNT(*) AS n
            FROM daily_symbol_predictions
            WHERE market_date = ?
            GROUP BY COALESCE(confidence, 'missing')
            ORDER BY confidence
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  {r['confidence']:<10} {r['n']}")
        else:
            print("  none")

        print()
        print("Avoid rows")
        rows = con.execute(
            """
            SELECT symbol, bias, risk_level, entry_quality, avoid_type, reason
            FROM daily_symbol_context
            WHERE market_date = ?
              AND bias = 'avoid'
            ORDER BY symbol
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(
                    f"  {r['symbol']:<6} "
                    f"risk={r['risk_level']} "
                    f"entry={r['entry_quality']} "
                    f"avoid_type={r['avoid_type']} "
                    f"reason={r['reason']}"
                )
        else:
            print("  none")

        print()
        print("Latest context updates")
        rows = con.execute(
            """
            SELECT symbol, updated_at
            FROM daily_symbol_context
            WHERE market_date = ?
            ORDER BY updated_at DESC, symbol
            LIMIT 10
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  {r['symbol']:<6} {r['updated_at']}")
        else:
            print("  none")

    if context_count <= 0:
        print("[FAIL] no daily_symbol_context rows found")
        ok = False

    if prediction_count not in (0, context_count):
        print("[WARN] prediction row count does not match context row count")

    if (
        freshness["latest_event_at"]
        and freshness["latest_context_at"]
        and freshness["latest_event_at"] > freshness["latest_context_at"]
    ):
        print("[WARN] latest event row is newer than daily_symbol_context; run apply_event_scores.py")

    if (
        freshness["latest_context_at"]
        and freshness["latest_prediction_at"]
        and freshness["latest_context_at"] > freshness["latest_prediction_at"]
    ):
        print("[WARN] latest context row is newer than daily_symbol_predictions; run predict_symbol_outcomes.py")

    if ok:
        print()
        print("[OK] intelligence summary completed")

    return ok


def _table_exists(con, table_name):
    row = con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _count_table(con, table_name, where_sql="", params=()):
    if not _table_exists(con, table_name):
        return None

    sql = f"SELECT COUNT(*) AS n FROM {table_name}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    return con.execute(sql, params).fetchone()["n"]


def dataset_health(target_date):
    import sqlite3

    db_path = BASE_DIR / "trades.db"

    print()
    print("=" * 72)
    print(f"  Dataset Health - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    ok = True

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        print("Core table counts")
        core_tables = [
            "trades",
            "matched_trades",
            "feature_snapshots",
            "labeled_setups",
            "daily_symbol_context",
            "daily_symbol_events",
            "daily_symbol_predictions",
            "bot_events",
        ]
        for table in core_tables:
            n = _count_table(con, table)
            label = "missing" if n is None else str(n)
            print(f"  {table:<26} {label:>8}")

        print()
        print(f"Target-date rows ({target_date})")
        dated_tables = [
            ("daily_symbol_context", "market_date"),
            ("daily_symbol_events", "market_date"),
            ("daily_symbol_predictions", "market_date"),
        ]
        target_counts = {}
        for table, col in dated_tables:
            n = _count_table(con, table, f"{col} = ?", (target_date,))
            target_counts[table] = n
            label = "missing" if n is None else str(n)
            print(f"  {table:<26} {label:>8}")

        print()
        print("Recent intelligence dates")
        for table in ("daily_symbol_context", "daily_symbol_events", "daily_symbol_predictions"):
            if not _table_exists(con, table):
                print(f"  {table}: missing")
                continue

            rows = con.execute(
                f"""
                SELECT market_date, COUNT(*) AS n
                FROM {table}
                GROUP BY market_date
                ORDER BY market_date DESC
                LIMIT 7
                """
            ).fetchall()

            if not rows:
                print(f"  {table}: none")
                continue

            print(f"  {table}:")
            for r in rows:
                print(f"    {r['market_date']:<12} {r['n']:>5}")

        print()
        print("Feature/label coverage")
        snapshots = _count_table(con, "feature_snapshots") or 0
        labels = _count_table(con, "labeled_setups") or 0
        matched = _count_table(con, "matched_trades") or 0
        trades = _count_table(con, "trades") or 0

        label_coverage = (labels / snapshots * 100.0) if snapshots else 0.0
        match_coverage = (matched / trades * 100.0) if trades else 0.0

        print(f"  feature_snapshots       {snapshots:>8}")
        print(f"  labeled_setups          {labels:>8}")
        print(f"  label_coverage_pct      {label_coverage:>7.1f}%")
        print(f"  trades                  {trades:>8}")
        print(f"  matched_trades          {matched:>8}")
        print(f"  match_coverage_pct      {match_coverage:>7.1f}%")

        if snapshots == 0:
            print("[WARN] no feature_snapshots yet; intraday ML dataset is not collecting samples")
        if labels == 0:
            print("[WARN] no labeled_setups yet; no supervised setup dataset is available")
        if matched == 0:
            print("[WARN] no matched_trades yet; strategy learning has no closed-trade outcomes")

        print()
        print("Prediction confidence")
        if _table_exists(con, "daily_symbol_predictions"):
            rows = con.execute(
                """
                SELECT COALESCE(confidence, 'missing') AS confidence, COUNT(*) AS n
                FROM daily_symbol_predictions
                WHERE market_date = ?
                GROUP BY COALESCE(confidence, 'missing')
                ORDER BY confidence
                """,
                (target_date,),
            ).fetchall()
            if rows:
                for r in rows:
                    print(f"  {r['confidence']:<10} {r['n']}")
            else:
                print("  none")
        else:
            print("  daily_symbol_predictions table missing")

        context_count = target_counts.get("daily_symbol_context") or 0
        prediction_count = target_counts.get("daily_symbol_predictions") or 0

        freshness = {}
        if all(
            _table_exists(con, table)
            for table in ("daily_symbol_events", "daily_symbol_context", "daily_symbol_predictions")
        ):
            freshness = con.execute(
                """
                SELECT
                  (SELECT MAX(created_at)
                   FROM daily_symbol_events
                   WHERE market_date = ?) AS latest_event_at,
                  (SELECT MAX(updated_at)
                   FROM daily_symbol_context
                   WHERE market_date = ?) AS latest_context_at,
                  (SELECT MAX(updated_at)
                   FROM daily_symbol_predictions
                   WHERE market_date = ?) AS latest_prediction_at
                """,
                (target_date, target_date, target_date),
            ).fetchone()

            print()
            print("Intelligence freshness")
            print(f"  latest event      : {freshness['latest_event_at'] or '-'}")
            print(f"  latest context    : {freshness['latest_context_at'] or '-'}")
            print(f"  latest prediction : {freshness['latest_prediction_at'] or '-'}")

        if context_count <= 0:
            print("[FAIL] no target-date daily_symbol_context rows found")
            ok = False
        if prediction_count not in (0, context_count):
            print("[WARN] target-date prediction count does not match context count")
        if freshness:
            if (
                freshness["latest_event_at"]
                and freshness["latest_context_at"]
                and freshness["latest_event_at"] > freshness["latest_context_at"]
            ):
                print("[WARN] latest event row is newer than daily_symbol_context")
            if (
                freshness["latest_context_at"]
                and freshness["latest_prediction_at"]
                and freshness["latest_context_at"] > freshness["latest_prediction_at"]
            ):
                print("[WARN] latest context row is newer than daily_symbol_predictions")

    print()
    if ok:
        print("[OK] dataset health check completed")
    else:
        print("[FAIL] dataset health check found issues")

    return ok


def _log_stats(path, patterns):
    import re

    stats = {key: 0 for key in patterns}
    first_ts = None
    last_ts = None
    last_matches = {key: None for key in patterns}

    path = BASE_DIR / path
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "lines": 0,
            "first_ts": None,
            "last_ts": None,
            "stats": stats,
            "last_matches": last_matches,
        }

    lines = path.read_text(errors="replace").splitlines()
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

    for line in lines:
        m = ts_re.match(line)
        if m:
            first_ts = first_ts or m.group(1)
            last_ts = m.group(1)

        for key, pattern in patterns.items():
            if pattern in line:
                stats[key] += 1
                last_matches[key] = line

    return {
        "exists": True,
        "path": str(path),
        "lines": len(lines),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "stats": stats,
        "last_matches": last_matches,
    }


def feature_health(target_date):
    import sqlite3

    db_path = BASE_DIR / "trades.db"

    print()
    print("=" * 72)
    print(f"  Feature Pipeline Health - {target_date}")
    print("=" * 72)

    ok = True

    print("Scripts")
    for script in ("run_live_features.sh", "run_label_features.sh", "live_features.py", "label_features.py"):
        path = BASE_DIR / script
        print(f"  {script:<24} {'present' if path.exists() else 'missing'}")
        if not path.exists():
            ok = False

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        print()
        print("Schema")
        expected = {
            "feature_snapshots": [
                "timestamp",
                "symbol",
                "last_price",
                "ret_1m",
                "ret_5m",
                "ret_15m",
                "setup_label",
                "setup_recommendation",
                "setup_score",
                "setup_key",
            ],
            "labeled_setups": [
                "snapshot_id",
                "symbol",
                "timestamp",
                "price_at_snapshot",
                "future_price_5m",
                "future_price_15m",
                "future_price_30m",
                "ret_fwd_15m",
                "outcome_label",
            ],
        }

        for table, cols in expected.items():
            if not _table_exists(con, table):
                print(f"  {table:<20} missing")
                ok = False
                continue

            actual = {r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
            missing = [c for c in cols if c not in actual]
            if missing:
                print(f"  {table:<20} missing columns: {missing}")
                ok = False
            else:
                print(f"  {table:<20} ok ({len(actual)} columns)")

        print()
        print("Current DB rows")
        rows = con.execute(
            """
            SELECT COUNT(*) AS n, MIN(timestamp) AS min_ts, MAX(timestamp) AS max_ts
            FROM feature_snapshots
            """
        ).fetchone()
        print(f"  feature_snapshots       {rows['n']:>8}  {rows['min_ts'] or '-'} -> {rows['max_ts'] or '-'}")

        label_rows = con.execute(
            """
            SELECT COUNT(*) AS n, MIN(timestamp) AS min_ts, MAX(timestamp) AS max_ts
            FROM labeled_setups
            """
        ).fetchone()
        print(f"  labeled_setups          {label_rows['n']:>8}  {label_rows['min_ts'] or '-'} -> {label_rows['max_ts'] or '-'}")

        unlabeled = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM feature_snapshots fs
            LEFT JOIN labeled_setups ls
              ON ls.snapshot_id = fs.id
            WHERE ls.snapshot_id IS NULL
              AND fs.last_price IS NOT NULL
            """
        ).fetchone()["n"]
        print(f"  unlabeled_snapshots     {unlabeled:>8}")

        if rows["n"] == 0:
            print("[WARN] current DB has no feature_snapshots")
        if label_rows["n"] == 0:
            print("[WARN] current DB has no labeled_setups")

    print()
    print("Log evidence")
    live_patterns = {
        "snapshot_collected": "snapshot collected",
        "snapshot_failed": "snapshot failed",
        "traceback": "Traceback",
    }
    label_patterns = {
        "labeled": "labeled ret15=",
        "labeling_complete": "Labeling complete",
        "no_forward_bars": "no forward bars yet",
        "failed": "failed:",
        "traceback": "Traceback",
    }

    for log_name, patterns in (
        ("live_features.log", live_patterns),
        ("live_features.log.1", live_patterns),
        ("label_features.log", label_patterns),
        ("label_features.log.1", label_patterns),
    ):
        stats = _log_stats(log_name, patterns)
        if not stats["exists"]:
            print(f"  {log_name:<22} missing")
            continue

        print(
            f"  {log_name:<22} lines={stats['lines']} "
            f"range={stats['first_ts'] or '-'} -> {stats['last_ts'] or '-'}"
        )
        for key, n in stats["stats"].items():
            print(f"    {key:<20} {n}")

        for key, line in stats["last_matches"].items():
            if line:
                print(f"    last_{key}: {line[:180]}")

    print()
    print("Interpretation")
    print("  DB rows show what survived the rebuild.")
    print("  Rotated logs can prove the jobs worked before the rebuild, but they cannot restore rows by themselves.")
    print("  A fresh Tuesday session should create feature_snapshots first, then labeled_setups after the 35-minute label delay.")

    print()
    if ok:
        print("[OK] feature pipeline health check completed")
    else:
        print("[FAIL] feature pipeline health check found issues")

    return ok


def _parse_iso_datetime(value):
    from datetime import datetime

    if not value:
        return None

    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        pass

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def feature_watch(target_date):
    import sqlite3
    from datetime import datetime, timedelta

    db_path = BASE_DIR / "trades.db"

    print()
    print("=" * 72)
    print(f"  Feature Session Watch - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    try:
        from symbols_config import APPROVED_SYMBOLS_LIST
        approved_symbols = sorted(set(APPROVED_SYMBOLS_LIST))
    except Exception:
        approved_symbols = []

    ok = True

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        if not _table_exists(con, "feature_snapshots") or not _table_exists(con, "labeled_setups"):
            print("[FAIL] feature_snapshots or labeled_setups table is missing")
            return False

        snapshot_count = con.execute(
            """
            SELECT COUNT(*) AS n,
                   MIN(timestamp) AS first_ts,
                   MAX(timestamp) AS last_ts,
                   COUNT(DISTINCT symbol) AS symbols_seen
            FROM feature_snapshots
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        ).fetchone()

        label_count = con.execute(
            """
            SELECT COUNT(*) AS n,
                   MIN(timestamp) AS first_ts,
                   MAX(timestamp) AS last_ts,
                   COUNT(DISTINCT symbol) AS symbols_seen
            FROM labeled_setups
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        ).fetchone()

        print("Session totals")
        print(f"  snapshots              {snapshot_count['n']:>8}")
        print(f"  snapshot_symbols       {snapshot_count['symbols_seen']:>8}")
        print(f"  first_snapshot         {snapshot_count['first_ts'] or '-'}")
        print(f"  latest_snapshot        {snapshot_count['last_ts'] or '-'}")
        print(f"  labels                 {label_count['n']:>8}")
        print(f"  label_symbols          {label_count['symbols_seen']:>8}")
        print(f"  first_label            {label_count['first_ts'] or '-'}")
        print(f"  latest_label           {label_count['last_ts'] or '-'}")

        print()
        print("Snapshots by hour")
        rows = con.execute(
            """
            SELECT substr(timestamp, 12, 2) AS hour, COUNT(*) AS n, COUNT(DISTINCT symbol) AS symbols_seen
            FROM feature_snapshots
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY substr(timestamp, 12, 2)
            ORDER BY hour
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  {r['hour']}:00  rows={r['n']:>5}  symbols={r['symbols_seen']:>3}")
        else:
            print("  none")

        print()
        print("Labels by outcome")
        rows = con.execute(
            """
            SELECT COALESCE(outcome_label, 'missing') AS outcome_label, COUNT(*) AS n
            FROM labeled_setups
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY COALESCE(outcome_label, 'missing')
            ORDER BY outcome_label
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  {r['outcome_label']:<14} {r['n']}")
        else:
            print("  none")

        seen_rows = con.execute(
            """
            SELECT symbol, COUNT(*) AS n, MAX(timestamp) AS latest_ts
            FROM feature_snapshots
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY symbol
            ORDER BY symbol
            """,
            (target_date,),
        ).fetchall()
        seen = {r["symbol"]: r for r in seen_rows}
        missing = [s for s in approved_symbols if s not in seen]

        print()
        print("Symbol coverage")
        if approved_symbols:
            print(f"  approved_symbols       {len(approved_symbols):>8}")
            print(f"  seen_symbols           {len(seen):>8}")
            print(f"  missing_symbols        {len(missing):>8}")
            if missing:
                print("  missing:", ", ".join(missing[:30]) + (" ..." if len(missing) > 30 else ""))
        else:
            print(f"  seen_symbols           {len(seen):>8}")
            print("  approved symbol list unavailable")

        print()
        print("Unlabeled backlog")
        unlabeled_rows = con.execute(
            """
            SELECT fs.id, fs.symbol, fs.timestamp
            FROM feature_snapshots fs
            LEFT JOIN labeled_setups ls
              ON ls.snapshot_id = fs.id
            WHERE substr(fs.timestamp, 1, 10) = ?
              AND fs.last_price IS NOT NULL
              AND ls.snapshot_id IS NULL
            ORDER BY fs.timestamp ASC
            """,
            (target_date,),
        ).fetchall()

        now = datetime.now().astimezone()
        eligible = []
        waiting = []
        for r in unlabeled_rows:
            ts = _parse_iso_datetime(r["timestamp"])
            if ts is None:
                waiting.append(r)
                continue
            if ts.tzinfo is None:
                age_ready = datetime.now() - ts >= timedelta(minutes=35)
            else:
                age_ready = now - ts.astimezone() >= timedelta(minutes=35)
            if age_ready:
                eligible.append(r)
            else:
                waiting.append(r)

        print(f"  total_unlabeled        {len(unlabeled_rows):>8}")
        print(f"  eligible_35m_plus      {len(eligible):>8}")
        print(f"  still_waiting          {len(waiting):>8}")

        if eligible:
            print("  oldest eligible:")
            for r in eligible[:10]:
                print(f"    id={r['id']:<6} {r['symbol']:<6} {r['timestamp']}")

        print()
        print("Recent snapshots")
        rows = con.execute(
            """
            SELECT id, symbol, timestamp, last_price, setup_label, setup_recommendation, setup_score
            FROM feature_snapshots
            WHERE substr(timestamp, 1, 10) = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 10
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(
                    f"  id={r['id']:<6} {r['symbol']:<6} {r['timestamp']} "
                    f"price={r['last_price']} setup={r['setup_label']} "
                    f"rec={r['setup_recommendation']} score={r['setup_score']}"
                )
        else:
            print("  none")

        if snapshot_count["n"] == 0:
            print("[WARN] no target-date feature_snapshots yet")
        if approved_symbols and snapshot_count["n"] > 0 and missing:
            print("[WARN] target-date feature snapshots are missing approved symbols")
        if eligible:
            print("[WARN] unlabeled snapshots are older than 35 minutes; label job may need attention")

    print()
    if ok:
        print("[OK] feature session watch completed")
    else:
        print("[FAIL] feature session watch found issues")

    return ok


def _reason_category(reason):
    from rejection_categories import reason_category

    category = reason_category(reason)
    return "missing" if category == "unknown_error" and not (reason or "").strip() else category


def rejection_summary(target_date):
    import sqlite3

    db_path = BASE_DIR / "trades.db"

    print()
    print("=" * 72)
    print(f"  Rejection Summary - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        if not _table_exists(con, "trades"):
            print("[FAIL] trades table is missing")
            return False

        total = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        ).fetchone()["n"]

        approved = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
            """,
            (target_date,),
        ).fetchone()["n"]

        rejected = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            """,
            (target_date,),
        ).fetchone()["n"]

        print("Totals")
        print(f"  trades                 {total:>8}")
        print(f"  approved               {approved:>8}")
        print(f"  rejected               {rejected:>8}")

        print()
        print("By action / approval")
        rows = con.execute(
            """
            SELECT COALESCE(action, 'missing') AS action,
                   COALESCE(approved, 0) AS approved,
                   COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY COALESCE(action, 'missing'), COALESCE(approved, 0)
            ORDER BY action, approved DESC
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                decision = "approved" if int(r["approved"] or 0) == 1 else "rejected"
                print(f"  {r['action']:<8} {decision:<10} {r['n']}")
        else:
            print("  none")

        print()
        print("Rejection categories")
        rows = con.execute(
            """
            SELECT rejection_reason, COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            GROUP BY rejection_reason
            ORDER BY n DESC, rejection_reason
            """,
            (target_date,),
        ).fetchall()
        if rows:
            buckets = {}
            examples = {}
            for r in rows:
                category = _reason_category(r["rejection_reason"])
                buckets[category] = buckets.get(category, 0) + int(r["n"] or 0)
                examples.setdefault(category, r["rejection_reason"] or "")
            for category, n in sorted(buckets.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {category:<28} {n:>5}  example={examples[category]}")
            unknown_count = buckets.get("unknown_error", 0)
            if unknown_count:
                print(f"[WARN] unknown_error rejection category count={unknown_count}; check for log_rejection bypasses")
        else:
            print("  none")

        print()
        print("Top rejected symbols")
        rows = con.execute(
            """
            SELECT COALESCE(symbol, 'missing') AS symbol, COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            GROUP BY COALESCE(symbol, 'missing')
            ORDER BY n DESC, symbol
            LIMIT 15
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  {r['symbol']:<8} {r['n']}")
        else:
            print("  none")

        print()
        print("Recent rejected rows")
        rows = con.execute(
            """
            SELECT timestamp, symbol, action, rejection_reason, confidence,
                   prediction_score, prediction_decision, setup_label,
                   buy_opportunity_score, buy_opportunity_recommendation
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            ORDER BY timestamp DESC, id DESC
            LIMIT 12
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(
                    f"  {r['timestamp']} {r['symbol'] or '-':<6} {r['action'] or '-':<4} "
                    f"reason={r['rejection_reason'] or '-'} "
                    f"conf={r['confidence'] or '-'} pred={r['prediction_score']}/{r['prediction_decision']} "
                    f"setup={r['setup_label'] or '-'} opp={r['buy_opportunity_score']}/{r['buy_opportunity_recommendation']}"
                )
        else:
            print("  none")

    print()
    print("[OK] rejection summary completed")
    return True


def migration_status_check():
    from db_migrations import status as migration_status

    print()
    print("=" * 72)
    print("  DB Migration Status")
    print("=" * 72)

    try:
        rows = migration_status(BASE_DIR / "trades.db")
    except Exception as e:
        print(f"[FAIL] migration status check failed: {e}")
        return False

    pending = [row for row in rows if not row["applied"]]
    for row in rows:
        marker = "applied" if row["applied"] else "pending"
        print(f"{marker:>8}  {row['migration_id']}  {row['description']}")

    if pending:
        print(f"[FAIL] {len(pending)} pending DB migration(s)")
        return False

    print("[OK] all DB migrations applied")
    return True


def order_health(target_date):
    import sqlite3

    db_path = BASE_DIR / "trades.db"

    print()
    print("=" * 72)
    print(f"  Order Health - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    ok = True

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        if not _table_exists(con, "trades"):
            print("[FAIL] trades table is missing")
            return False

        print("Trade order fields")
        rows = con.execute(
            """
            SELECT
                COUNT(*) AS approved_rows,
                SUM(CASE WHEN order_id IS NOT NULL AND order_id != '' THEN 1 ELSE 0 END) AS with_order_id,
                SUM(CASE WHEN order_id IS NULL OR order_id = '' THEN 1 ELSE 0 END) AS missing_order_id,
                SUM(CASE WHEN order_status IS NULL OR order_status = '' THEN 1 ELSE 0 END) AS missing_order_status
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
            """,
            (target_date,),
        ).fetchone()
        approved_rows = int(rows["approved_rows"] or 0)
        missing_order_id = int(rows["missing_order_id"] or 0)
        print(f"  approved_rows          {approved_rows:>8}")
        print(f"  with_order_id          {int(rows['with_order_id'] or 0):>8}")
        print(f"  missing_order_id       {missing_order_id:>8}")
        print(f"  missing_order_status   {int(rows['missing_order_status'] or 0):>8}")
        if missing_order_id:
            print("[WARN] approved rows without order_id found")

        print()
        print("Order status distribution")
        rows = con.execute(
            """
            SELECT COALESCE(order_status, 'missing') AS order_status, COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
            GROUP BY COALESCE(order_status, 'missing')
            ORDER BY n DESC, order_status
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  {r['order_status']:<22} {r['n']}")
        else:
            print("  none")

        print()
        print("Recent approved rows")
        rows = con.execute(
            """
            SELECT timestamp, symbol, action, order_id, order_status, qty, fill_price,
                   position_size_pct, stop_loss_pct, take_profit_pct
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
            ORDER BY timestamp DESC, id DESC
            LIMIT 12
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for r in rows:
                print(
                    f"  {r['timestamp']} {r['symbol'] or '-':<6} {r['action'] or '-':<4} "
                    f"status={r['order_status'] or '-'} order_id={r['order_id'] or '-'} "
                    f"qty={r['qty']} fill={r['fill_price']} size={r['position_size_pct']} "
                    f"stop={r['stop_loss_pct']} target={r['take_profit_pct']}"
                )
        else:
            print("  none")

        print()
        print("Fill events")
        if _table_exists(con, "fill_events"):
            rows = con.execute(
                """
                SELECT COALESCE(event, 'missing') AS event,
                       COALESCE(status, 'missing') AS status,
                       COUNT(*) AS n
                FROM fill_events
                WHERE substr(timestamp, 1, 10) = ?
                GROUP BY COALESCE(event, 'missing'), COALESCE(status, 'missing')
                ORDER BY n DESC, event, status
                """,
                (target_date,),
            ).fetchall()
            if rows:
                for r in rows:
                    print(f"  event={r['event']:<18} status={r['status']:<18} {r['n']}")
            else:
                print("  none")
        else:
            print("  fill_events table missing")

        print()
        print("External Alpaca orders")
        if _table_exists(con, "external_alpaca_orders"):
            rows = con.execute(
                """
                SELECT COALESCE(status, 'missing') AS status,
                       COALESCE(side, 'missing') AS side,
                       COUNT(*) AS n
                FROM external_alpaca_orders
                WHERE substr(COALESCE(submitted_at, imported_at), 1, 10) = ?
                GROUP BY COALESCE(status, 'missing'), COALESCE(side, 'missing')
                ORDER BY n DESC, status, side
                """,
                (target_date,),
            ).fetchall()
            if rows:
                for r in rows:
                    print(f"  status={r['status']:<18} side={r['side']:<8} {r['n']}")
            else:
                print("  none")
        else:
            print("  external_alpaca_orders table missing")

        if approved_rows and missing_order_id:
            ok = False

    print()
    if ok:
        print("[OK] order health completed")
    else:
        print("[WARN] order health found issues")
    return ok


def main():
    env_loaded = load_env_file()
    print(f"env_file_loaded={env_loaded}")

    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2

    command = sys.argv[1].lower()
    target_date = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()

    if command == "market-context-check":
        return 0 if check_market_context_file() else 1

    if command == "intelligence-summary":
        return 0 if intelligence_summary(target_date) else 1

    if command == "dataset-health":
        return 0 if dataset_health(target_date) else 1

    if command == "feature-health":
        return 0 if feature_health(target_date) else 1

    if command == "feature-watch":
        return 0 if feature_watch(target_date) else 1

    if command == "rejection-summary":
        return 0 if rejection_summary(target_date) else 1

    if command == "order-health":
        return 0 if order_health(target_date) else 1

    if command == "migration-status":
        return 0 if migration_status_check() else 1

    if command == "premarket":
        checks = []
        checks.append(run("DB Migration Status", ["ops_check.py", "migration-status"]))
        checks.append(run("Morning Check", ["morning_check.py"]))
        checks.append(run("Position Review", ["position_review.py"]))
        checks.append(run("Market Alignment Report", ["market_alignment_report.py"]))
        checks.append(run("Session Momentum Refresh", ["session_momentum.py", "--all"]))
        checks.append(run("Position Momentum Monitor", ["position_momentum_monitor.py"]))
        checks.append(run("Bot Events", ["bot_events.py", "--limit", "25"]))

        print()
        print("=" * 72)
        if all(checks):
            print("[OK] premarket checks completed successfully")
            return 0

        print("[WARN] one or more premarket checks reported issues")
        return 1

    if command == "all":
        checks = []
        checks.append(run("DB Migration Status", ["ops_check.py", "migration-status"]))
        checks.append(run("Morning Check", ["morning_check.py"]))
        checks.append(run("Position Review", ["position_review.py"]))
        checks.append(run("Market Alignment Report", ["market_alignment_report.py"]))
        checks.append(run("Session Momentum Refresh", ["session_momentum.py", "--all"]))
        checks.append(run("Position Momentum Monitor", ["position_momentum_monitor.py"]))
        checks.append(run("Adaptive Confirmation Report", ["adaptive_confirmation_report.py"]))
        checks.append(run("Adaptive Impact Report", ["adaptive_impact_report.py", target_date]))
        checks.append(run("Filter Report", ["filter_report.py", "--date", target_date]))
        checks.append(run("Blocked Signal Outcome Report", ["blocked_signal_outcome_report.py", "--date", target_date]))
        checks.append(run("Drawdown Report", ["drawdown_report.py", target_date]))
        checks.append(run("Post-Session Check", ["post_session_check.py", target_date]))

        print()
        print("=" * 72)
        if all(checks):
            print("[OK] all requested checks completed successfully")
            return 0

        print("[WARN] one or more checks reported issues")
        return 1

    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print()
        print(__doc__.strip())
        return 2

    args = COMMANDS[command]

    if command == "filters":
        args = ["filter_report.py", "--date", target_date]
    elif command == "blocked":
        args = ["blocked_signal_outcome_report.py", "--date", target_date]
    elif command in ("drawdown", "post", "adaptive_impact", "strategy_intelligence"):
        args = args + [target_date]
    elif command in (
        "intelligence",
        "context",
        "learning",
        "predictions",
        "signal-lessons",
        "trends",
        "prediction-validation",
        "event-attribution",
    ):
        args = [args[0], "--date", target_date]

    ok = run(command.title(), args)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
