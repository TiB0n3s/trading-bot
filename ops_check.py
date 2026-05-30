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
  python3 ops_check.py rejected-outcomes
  python3 ops_check.py auto-buy
  python3 ops_check.py auto-buy-outcomes
  python3 ops_check.py decision-snapshots
  python3 ops_check.py policy-artifacts
  python3 ops_check.py retention
  python3 ops_check.py order-health
  python3 ops_check.py migration-status
  python3 ops_check.py strong-days
  python3 ops_check.py strong-days 2026-05-26
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


# Commands that take no date arg (run with no extra args)
# Commands that take a positional date: drawdown, post, adaptive_impact, strategy_intelligence
# Commands that take --date DATE: filters, blocked, event-attribution, intelligence, context,
#   learning, predictions, signal-lessons, trends, prediction-validation, auto-buy-outcomes,
#   strong-days
# Full arg construction is done in main() below.
COMMANDS = {
    "morning": ["morning_check.py"],
    "positions": ["position_review.py"],
    "alignment": ["market_alignment_report.py"],
    "adaptive": ["adaptive_confirmation_report.py"],
    "adaptive_impact": ["adaptive_impact_report.py"],
    "strategy_intelligence": ["strategy_intelligence_report.py"],
    "blocked": ["blocked_signal_outcome_report.py"],
    "session": ["session_momentum.py", "--all"],
    "position-momentum": ["position_momentum_monitor.py"],
    "filters": ["filter_report.py"],
    "drawdown": ["drawdown_report.py"],
    "post": ["post_session_check.py"],
    "events": ["bot_events.py", "--limit", "25"],
    "bot-events": ["bot_events.py", "--limit", "25"],
    "event-attribution": ["event_attribution_report.py"],
    "intelligence": ["intelligence_context_report.py"],
    "context": ["context_trade_join_report.py"],
    "learning": ["intelligence_learning_report.py"],
    "predictions": ["intelligence_prediction_report.py"],
    "signal-lessons": ["signal_timing_lesson_report.py"],
    "trends": ["trend_context_report.py"],
    "prediction-validation": ["prediction_validation_report.py"],
    "auto-buy-outcomes": ["auto_buy_outcome_report.py"],
    "strong-days": ["strong_day_participation_report.py"],
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

    # Intraday refresh staleness check — only meaningful during market hours.
    from datetime import datetime, timezone, timedelta
    intraday_refresh_at = data.get("intraday_refresh_at")
    print(f"intraday_refresh_at : {intraday_refresh_at or 'not present'}")
    now_utc = datetime.now(timezone.utc)
    et_offset = timedelta(hours=-4)  # EDT; close enough for a staleness gate
    now_et = now_utc + et_offset
    market_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    is_market_hours = now_et.weekday() < 5 and market_open_et <= now_et <= market_close_et
    INTRADAY_REFRESH_STALE_MINUTES = 90
    if is_market_hours:
        if not intraday_refresh_at:
            print(f"[WARN] intraday_refresh_at absent during market hours — intraday_context_refresh.py may not have run yet")
        else:
            try:
                refresh_dt = datetime.fromisoformat(intraday_refresh_at).astimezone(timezone.utc)
                age_minutes = (now_utc - refresh_dt).total_seconds() / 60
                if age_minutes > INTRADAY_REFRESH_STALE_MINUTES:
                    print(f"[WARN] intraday_refresh_at is {age_minutes:.0f} min old (>{INTRADAY_REFRESH_STALE_MINUTES} min) — refresh may be silently failing")
                    ok = False
                else:
                    print(f"[OK] intraday_refresh_at is {age_minutes:.0f} min old (within {INTRADAY_REFRESH_STALE_MINUTES} min)")
            except Exception as e:
                print(f"[WARN] could not parse intraday_refresh_at '{intraday_refresh_at}': {e}")
    else:
        if intraday_refresh_at:
            print(f"[OK] intraday_refresh_at present (staleness check skipped outside market hours)")

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
        strong_day_count = 0
        if _table_exists(con, "strong_day_participation"):
            strong_day_count = con.execute(
                """
                SELECT COUNT(*) AS n
                FROM strong_day_participation
                WHERE market_date = ?
                """,
                (target_date,),
            ).fetchone()["n"]

        print(f"context rows    : {context_count}")
        print(f"event rows      : {event_count}")
        print(f"prediction rows : {prediction_count}")
        print(f"strong-day rows : {strong_day_count}")

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
            "strong_day_participation",
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
            ("strong_day_participation", "market_date"),
        ]
        target_counts = {}
        for table, col in dated_tables:
            n = _count_table(con, table, f"{col} = ?", (target_date,))
            target_counts[table] = n
            label = "missing" if n is None else str(n)
            print(f"  {table:<26} {label:>8}")

        print()
        print("Recent intelligence dates")
        for table in ("daily_symbol_context", "daily_symbol_events", "daily_symbol_predictions", "strong_day_participation"):
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


def rejected_outcomes_health(target_date):
    import sqlite3
    from datetime import datetime, time, timedelta

    import pytz

    db_path = BASE_DIR / "trades.db"
    local_tz = pytz.timezone(os.getenv("TRADING_BOT_LOCAL_TZ", "America/Chicago"))
    et = pytz.timezone("America/New_York")

    print()
    print("=" * 72)
    print(f"  Rejected Signal Outcomes - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        if not _table_exists(con, "rejected_signal_outcomes"):
            print("[FAIL] rejected_signal_outcomes table is missing")
            return False

        rejected = con.execute(
            """
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN LOWER(action) = 'buy' THEN 1 ELSE 0 END) AS buy_n,
                SUM(CASE WHEN LOWER(action) = 'sell' THEN 1 ELSE 0 END) AS sell_n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 0
              AND symbol IS NOT NULL
              AND action IS NOT NULL
              AND signal_price IS NOT NULL
              AND LOWER(action) IN ('buy', 'sell')
            """,
            (target_date,),
        ).fetchone()

        outcomes = con.execute(
            """
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN label_status = 'labeled' THEN 1 ELSE 0 END) AS labeled,
                SUM(CASE WHEN label_status = 'partial' THEN 1 ELSE 0 END) AS partial,
                SUM(CASE WHEN label_status = 'pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN label_status = 'no_bars' THEN 1 ELSE 0 END) AS no_bars,
                SUM(CASE WHEN label_status = 'error' THEN 1 ELSE 0 END) AS error
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        ).fetchone()

        covered = int(outcomes["n"] or 0)
        rejected_total = int(rejected["n"] or 0)
        missing = rejected_total - covered
        print(f"  rejected_rows          {rejected_total:>8}")
        print(f"  rejected_buy_rows      {int(rejected['buy_n'] or 0):>8}")
        print(f"  rejected_sell_rows     {int(rejected['sell_n'] or 0):>8}")
        print(f"  outcome_rows           {covered:>8}")
        print(f"  missing_outcomes       {missing:>8}")
        print(f"  labeled                {int(outcomes['labeled'] or 0):>8}")
        print(f"  partial                {int(outcomes['partial'] or 0):>8}")
        print(f"  pending                {int(outcomes['pending'] or 0):>8}")
        print(f"  no_bars                {int(outcomes['no_bars'] or 0):>8}")
        print(f"  error                  {int(outcomes['error'] or 0):>8}")

        cols = {row["name"] for row in con.execute("PRAGMA table_info(rejected_signal_outcomes)").fetchall()}
        if "partial_reason" in cols:
            print()
            print("Partial reasons")
            rows = con.execute(
                """
                SELECT COALESCE(partial_reason, 'unspecified') AS partial_reason,
                       COUNT(*) AS n
                FROM rejected_signal_outcomes
                WHERE substr(timestamp, 1, 10) = ?
                  AND label_status IN ('partial', 'pending', 'no_bars')
                GROUP BY COALESCE(partial_reason, 'unspecified')
                ORDER BY n DESC, partial_reason
                """,
                (target_date,),
            ).fetchall()
            if rows:
                for row in rows:
                    print(f"  {row['partial_reason']:<30} {row['n']:>6}")
            else:
                print("  none")
        elif int(outcomes["partial"] or 0):
            print()
            print("[INFO] partial rows may be near-close structural partials or pending forward bars")

        print()
        print("Horizon completeness")
        horizon_rows = con.execute(
            """
            SELECT
                label_status,
                COUNT(*) AS n,
                SUM(CASE WHEN return_5m IS NOT NULL THEN 1 ELSE 0 END) AS has_5m,
                SUM(CASE WHEN return_15m IS NOT NULL THEN 1 ELSE 0 END) AS has_15m,
                SUM(CASE WHEN return_30m IS NOT NULL THEN 1 ELSE 0 END) AS has_30m,
                SUM(CASE WHEN return_60m IS NOT NULL THEN 1 ELSE 0 END) AS has_60m,
                SUM(CASE WHEN return_eod IS NOT NULL THEN 1 ELSE 0 END) AS has_eod,
                SUM(CASE WHEN max_favorable_60m IS NOT NULL THEN 1 ELSE 0 END) AS has_mfe,
                SUM(CASE WHEN max_adverse_60m IS NOT NULL THEN 1 ELSE 0 END) AS has_mae
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY label_status
            ORDER BY label_status
            """,
            (target_date,),
        ).fetchall()
        if horizon_rows:
            for row in horizon_rows:
                print(
                    f"  {row['label_status']:<10} n={row['n']:>5} "
                    f"5m={row['has_5m']:>5} 15m={row['has_15m']:>5} "
                    f"30m={row['has_30m']:>5} 60m={row['has_60m']:>5} "
                    f"eod={row['has_eod']:>5} mfe={row['has_mfe']:>5} mae={row['has_mae']:>5}"
                )
        else:
            print("  none")

        print()
        print("By action/status")
        rows = con.execute(
            """
            SELECT action, label_status, COUNT(*) AS n,
                   AVG(return_15m) AS avg_return_15m,
                   AVG(return_60m) AS avg_return_60m,
                   AVG(return_eod) AS avg_return_eod
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY action, label_status
            ORDER BY action, label_status
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for row in rows:
                avg15 = row["avg_return_15m"]
                avg60 = row["avg_return_60m"]
                avgeod = row["avg_return_eod"]
                avg15_s = f"{avg15:.3f}%" if avg15 is not None else "-"
                avg60_s = f"{avg60:.3f}%" if avg60 is not None else "-"
                avgeod_s = f"{avgeod:.3f}%" if avgeod is not None else "-"
                print(
                    f"  {row['action']:<5} {row['label_status']:<10} "
                    f"{row['n']:>6} avg15={avg15_s:>9} avg60={avg60_s:>9} avgeod={avgeod_s:>9}"
                )
        else:
            print("  none")

        invalid_labeled = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status = 'labeled'
              AND (
                   return_5m IS NULL
                OR return_15m IS NULL
                OR return_30m IS NULL
                OR return_60m IS NULL
                OR return_eod IS NULL
                OR max_favorable_60m IS NULL
                OR max_adverse_60m IS NULL
              )
            """,
            (target_date,),
        ).fetchone()["n"]

        bad_excursions = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status IN ('labeled', 'partial')
              AND (
                   max_favorable_60m < -0.000001
                OR max_adverse_60m > 0.000001
              )
            """,
            (target_date,),
        ).fetchone()["n"]

        partial_rows = con.execute(
            """
            SELECT trade_id, timestamp, partial_reason, return_60m
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status = 'partial'
            """,
            (target_date,),
        ).fetchall()

        def parse_ts(value):
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is None:
                dt = local_tz.localize(dt)
            return dt.astimezone(et)

        bad_near_close = 0
        bad_partial_60m = 0
        for row in partial_rows:
            try:
                signal_dt = parse_ts(row["timestamp"])
                close_dt = et.localize(datetime.combine(signal_dt.date(), time(16, 0)))
                near_close = signal_dt + timedelta(minutes=60) > close_dt
                if row["partial_reason"] == "near_close_no_60m_window" and not near_close:
                    bad_near_close += 1
                if row["partial_reason"] != "near_close_no_60m_window" and near_close:
                    bad_near_close += 1
                if row["partial_reason"] == "near_close_no_60m_window" and row["return_60m"] is not None:
                    bad_partial_60m += 1
            except Exception:
                bad_near_close += 1

        print()
        print("Validation checks")
        print(f"  labeled_missing_horizons     {int(invalid_labeled or 0):>6}")
        print(f"  bad_action_adjusted_mfe_mae  {int(bad_excursions or 0):>6}")
        print(f"  bad_near_close_partials      {bad_near_close:>6}")
        print(f"  near_close_with_60m_return    {bad_partial_60m:>6}")

        print()
        print("Top rejection categories with outcomes")
        rows = con.execute(
            """
            SELECT
                CASE
                  WHEN instr(rejection_reason, ':') > 0
                    THEN substr(rejection_reason, 1, instr(rejection_reason, ':') - 1)
                  ELSE COALESCE(rejection_reason, 'unknown')
                END AS category,
                COUNT(*) AS n,
                AVG(return_15m) AS avg_return_15m,
                AVG(max_favorable_60m) AS avg_mfe_60m
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY category
            ORDER BY n DESC, category
            LIMIT 12
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for row in rows:
                avg15 = row["avg_return_15m"]
                mfe = row["avg_mfe_60m"]
                avg15_s = f"{avg15:.3f}%" if avg15 is not None else "-"
                mfe_s = f"{mfe:.3f}%" if mfe is not None else "-"
                print(f"  {row['category']:<30} {row['n']:>6} avg15={avg15_s:>9} mfe60={mfe_s:>9}")
        else:
            print("  none")

    failures = []
    if missing > 0:
        failures.append("missing rejected outcome rows")
    if int(outcomes["error"] or 0) > 0:
        failures.append("error rows present")
    if int(invalid_labeled or 0) > 0:
        failures.append("labeled rows missing required horizons")
    if int(bad_excursions or 0) > 0:
        failures.append("action-adjusted MFE/MAE sign check failed")
    if bad_near_close > 0 or bad_partial_60m > 0:
        failures.append("near-close partial attribution failed")

    if failures:
        print()
        print("[WARN] rejected outcome validation needs follow-up:")
        for failure in failures:
            print(f"  - {failure}")
        return False

    print()
    print("[OK] rejected outcome coverage completed")
    return True


def auto_buy_health(target_date):
    import sqlite3

    db_path = BASE_DIR / "trades.db"

    print()
    print("=" * 72)
    print(f"  Auto-Buy Candidates - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        if not _table_exists(con, "auto_buy_candidates"):
            print("[WARN] auto_buy_candidates table is missing; run auto_buy_manager.py first")
            return False

        rows = con.execute(
            """
            SELECT decision, COUNT(*) AS n, AVG(score) AS avg_score, MAX(score) AS max_score
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY decision
            ORDER BY n DESC, decision
            """,
            (target_date,),
        ).fetchall()

        print("Decision distribution")
        if rows:
            for row in rows:
                avg_score = row["avg_score"]
                max_score = row["max_score"]
                avg_s = f"{avg_score:.2f}" if avg_score is not None else "-"
                max_s = f"{max_score:.2f}" if max_score is not None else "-"
                print(f"  {row['decision']:<24} {row['n']:>6} avg={avg_s:>7} max={max_s:>7}")
        else:
            print("  none")

        print()
        cols = {row["name"] for row in con.execute("PRAGMA table_info(auto_buy_candidates)").fetchall()}
        if "hard_block_reason" in cols:
            print("Hard-block reasons")
            rows = con.execute(
                """
                SELECT hard_block_reason, COUNT(*) AS n
                FROM auto_buy_candidates
                WHERE substr(timestamp, 1, 10) = ?
                  AND hard_block_reason IS NOT NULL
                  AND hard_block_reason != ''
                GROUP BY hard_block_reason
                ORDER BY n DESC, hard_block_reason
                LIMIT 10
                """,
                (target_date,),
            ).fetchall()
            if rows:
                for row in rows:
                    print(f"  {row['hard_block_reason']:<55} {row['n']:>6}")
            else:
                print("  none")
            print()

        print("Top candidates")
        rows = con.execute(
            """
            SELECT timestamp, symbol, signal_source, decision, score,
                   session_trend_label, session_trend_score,
                   setup_label, reason, order_submitted, order_id
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
            ORDER BY score DESC, id DESC
            LIMIT 15
            """,
            (target_date,),
        ).fetchall()
        if rows:
            for row in rows:
                print(
                    f"  {row['timestamp']} {row['symbol']:<6} "
                    f"{row['decision']:<22} score={row['score']:<5} "
                    f"source={row['signal_source'] or '-':<18} "
                    f"session={row['session_trend_label']}/{row['session_trend_score']} "
                    f"setup={row['setup_label'] or '-'} "
                    f"order={row['order_id'] or '-'}"
                )
        else:
            print("  none")

        print()
        print("Auto-buy audit snapshots")
        if _table_exists(con, "auto_buy_decision_snapshots"):
            row = con.execute(
                """
                SELECT COUNT(*) AS n,
                       SUM(CASE WHEN order_submitted = 1 THEN 1 ELSE 0 END) AS submitted,
                       SUM(CASE WHEN live_block_reason IS NOT NULL AND live_block_reason != '' THEN 1 ELSE 0 END) AS blocked
                FROM auto_buy_decision_snapshots
                WHERE substr(candidate_timestamp, 1, 10) = ?
                """,
                (target_date,),
            ).fetchone()
            print(f"  snapshots             {int(row['n'] or 0):>8}")
            print(f"  submitted             {int(row['submitted'] or 0):>8}")
            print(f"  live_blocked          {int(row['blocked'] or 0):>8}")
        else:
            print("  [WARN] auto_buy_decision_snapshots table missing")

    print()
    print("[OK] auto-buy candidate check completed")
    return True


def decision_snapshot_health(target_date):
    import sqlite3

    from decision_snapshots import summarize_snapshots

    db_path = BASE_DIR / "trades.db"

    print()
    print("=" * 72)
    print(f"  Decision Snapshots - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    ok = True
    summary = summarize_snapshots(target_date, db_path)
    print(f"  snapshots              {summary['total']:>8}")
    print(f"  symbols                {summary['symbols']:>8}")
    print(f"  missing_context_hash   {summary['missing_context_hash']:>8}")
    print(f"  missing_git_sha        {summary['missing_git_sha']:>8}")

    print()
    print("Decision distribution")
    if summary["by_decision"]:
        for row in summary["by_decision"]:
            print(
                f"  {row['final_decision'] or '-':<24} approved={row['approved']} n={row['n']}"
            )
    else:
        print("  none")

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        if not _table_exists(con, "decision_snapshots"):
            print("[FAIL] decision_snapshots table is missing")
            return False
        if _table_exists(con, "trades"):
            trade_count = con.execute(
                "SELECT COUNT(*) AS n FROM trades WHERE substr(timestamp, 1, 10) = ?",
                (target_date,),
            ).fetchone()["n"]
            snapshot_trade_count = con.execute(
                """
                SELECT COUNT(DISTINCT trade_id) AS n
                FROM decision_snapshots
                WHERE substr(decision_time, 1, 10) = ?
                  AND trade_id IS NOT NULL
                """,
                (target_date,),
            ).fetchone()["n"]
            print()
            print("Trade coverage")
            print(f"  trades_today           {int(trade_count or 0):>8}")
            print(f"  snapshots_with_trade   {int(snapshot_trade_count or 0):>8}")
            if trade_count and snapshot_trade_count < trade_count:
                print("[WARN] older trades may predate decision snapshot logging")

    if summary["total"] and summary["missing_context_hash"]:
        ok = False
        print("[WARN] some snapshots are missing market_context_hash")

    print()
    print("[OK] decision snapshot check completed" if ok else "[WARN] decision snapshot check found issues")
    return ok


def policy_artifact_health():
    from datetime import datetime, timezone

    from policy_artifacts import policy_artifact_status

    print()
    print("=" * 72)
    print("  Policy Artifact Health")
    print("=" * 72)

    status = policy_artifact_status(BASE_DIR)
    print(f"enabled     : {status.get('enabled')}")
    print(f"effect      : {status.get('runtime_effect')}")
    print(f"state_hash  : {status.get('state_hash')}")
    registry = status.get("registry") or {}
    known_good = registry.get("known_good") or {}
    print(f"registry    : entries={registry.get('entry_count', 0)} path={registry.get('registry_path')}")
    print(f"known_good  : {known_good.get('artifact_set_id') or '-'}")

    ok = True
    now = datetime.now(timezone.utc)
    for name, item in status.get("files", {}).items():
        exists = item.get("exists")
        mtime = item.get("mtime")
        age_hours = None
        if mtime:
            try:
                age_hours = (now - datetime.fromisoformat(mtime)).total_seconds() / 3600
            except Exception:
                age_hours = None
        age_s = f"{age_hours:.1f}h" if age_hours is not None else "-"
        print(
            f"  {name:<36} exists={str(exists):<5} age={age_s:>8} "
            f"generated_at={item.get('generated_at') or '-'} sha={str(item.get('sha256') or '-')[:12]}"
        )
        if name == "policy_backtest_summary.json":
            rec = item.get("recommendation")
            if rec:
                print(f"    policy_backtest_recommendation={rec} reason={item.get('reason') or '-'}")
                if rec == "policy_too_loose":
                    print("    [WARN] decision policy remains too loose; keep under review and do not promote")
        if not exists:
            ok = False
            print(f"    [WARN] missing policy artifact: {name}")
        elif age_hours is not None and age_hours > 72:
            print(f"    [WARN] artifact older than 72h: {name}")

    if not registry.get("entry_count"):
        ok = False
        print("[WARN] no policy artifact registry entries found")
    if not known_good.get("artifact_set_id"):
        ok = False
        print("[WARN] no known-good policy artifact pointer found")

    print()
    print("[OK] policy artifact check completed" if ok else "[WARN] policy artifact check found issues")
    return ok


def retention_health():
    from ml_platform.retention import retention_policy

    print()
    print("=" * 72)
    print("  ML/Audit Retention Policy")
    print("=" * 72)

    policy = retention_policy()
    print(f"version       : {policy['version']}")
    print(f"destructive   : {policy['destructive_compaction_enabled']}")
    print(f"rule          : {policy['rule']}")
    print()
    for row in policy["rules"]:
        window = row["default_window_days"] if row["default_window_days"] is not None else "preserve"
        print(
            f"  {row['name']:<30} tier={row['tier']:<5} window={str(window):<8} storage={row['storage']}"
        )

    print()
    print("[OK] retention policy is classified; no destructive compaction is enabled")
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


def setup_breakdown(target_date: str) -> bool:
    """Daily breakdown of setup classification quality for a given date.

    Shows:
      - Signal counts and approval rates by setup_policy_action
      - Error/unknown breakdown by symbol and hour-of-day
      - Matched-trade P&L bucketed by setup_policy_action
    """
    import sqlite3

    db_path = BASE_DIR / "trades.db"
    if not db_path.exists():
        print("[WARN] trades.db not found")
        return False

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        print(f"\n=== Setup Classification Breakdown: {target_date} ===\n")

        # --- Overview by setup_policy_action (BUY signals only) ---
        rows = con.execute("""
            SELECT
                COALESCE(setup_policy_action, 'NULL') AS action,
                COUNT(*) AS signals,
                SUM(approved) AS approved,
                SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            GROUP BY setup_policy_action
            ORDER BY signals DESC
        """, (target_date,)).fetchall()

        if not rows:
            print(f"  No BUY signals found for {target_date}.")
        else:
            print(f"  {'setup_policy_action':<28} {'signals':>7} {'approved':>8} {'rejected':>8}")
            print(f"  {'-'*28} {'-'*7} {'-'*8} {'-'*8}")
            for r in rows:
                print(
                    f"  {r['action']:<28} {r['signals']:>7} "
                    f"{r['approved']:>8} {r['rejected']:>8}"
                )

        # --- Error / unknown by symbol ---
        print()
        err_rows = con.execute("""
            SELECT
                symbol,
                COUNT(*) AS signals,
                SUM(approved) AS approved,
                COALESCE(setup_unknown_reason, setup_policy_reason, 'no_reason') AS reason
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND (
                  setup_policy_action = 'error'
                  OR setup_unknown_reason IS NOT NULL
              )
            GROUP BY symbol, setup_unknown_reason, setup_policy_reason
            ORDER BY signals DESC
            LIMIT 20
        """, (target_date,)).fetchall()

        if err_rows:
            print(f"  Error/unknown by symbol (top 20):")
            print(f"  {'symbol':<8} {'signals':>7} {'approved':>8}  reason")
            print(f"  {'-'*8} {'-'*7} {'-'*8}  {'-'*40}")
            for r in err_rows:
                reason = (r["reason"] or "")[:60]
                print(
                    f"  {r['symbol']:<8} {r['signals']:>7} {r['approved']:>8}  {reason}"
                )
        else:
            print("  No error/unknown signals for this date.")

        # --- Error / unknown by hour ---
        print()
        hour_rows = con.execute("""
            SELECT
                CAST(strftime('%H', timestamp) AS INTEGER) AS hour_et,
                COUNT(*) AS signals,
                SUM(approved) AS approved
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND (
                  setup_policy_action = 'error'
                  OR setup_unknown_reason IS NOT NULL
              )
            GROUP BY hour_et
            ORDER BY hour_et
        """, (target_date,)).fetchall()

        if hour_rows:
            print(f"  Error/unknown by hour (ET):")
            print(f"  {'hour':>5} {'signals':>7} {'approved':>8}")
            print(f"  {'-'*5} {'-'*7} {'-'*8}")
            for r in hour_rows:
                print(f"  {r['hour_et']:>5} {r['signals']:>7} {r['approved']:>8}")

        # --- SIP/IEX feed failure breakdown ---
        # Counts setup errors whose unknown_reason contains "subscription" — the
        # signature of the SIP data-subscription failure that plagued 2026-05-29.
        # After the IEX fallback is in place this count should drop to ~0.
        print()
        feed_rows = con.execute("""
            SELECT
                CASE
                    WHEN setup_unknown_reason LIKE '%subscription%'
                      OR setup_policy_reason LIKE '%subscription%'
                        THEN 'sip_subscription_failure'
                    WHEN setup_policy_action = 'error' THEN 'other_snapshot_error'
                    WHEN setup_unknown_reason IS NOT NULL THEN 'label_unknown'
                    ELSE 'no_error'
                END AS error_category,
                COUNT(*) AS signals,
                SUM(approved) AS approved
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            GROUP BY error_category
            ORDER BY signals DESC
        """, (target_date,)).fetchall()

        if feed_rows:
            print(f"  Feed/setup error breakdown:")
            print(f"  {'error_category':<30} {'signals':>7} {'approved':>8}")
            print(f"  {'-'*30} {'-'*7} {'-'*8}")
            for r in feed_rows:
                print(f"  {r['error_category']:<30} {r['signals']:>7} {r['approved']:>8}")

        # --- Matched-trade P&L by setup_policy_action ---
        print()
        pnl_rows = con.execute("""
            SELECT
                COALESCE(setup_policy_action, 'NULL') AS spa,
                COUNT(*) AS trades,
                SUM(won) AS wins,
                ROUND(AVG(realized_pnl_pct), 3) AS avg_pnl_pct,
                ROUND(SUM(realized_pnl_pct), 2) AS total_pnl_pct
            FROM matched_trades
            WHERE date(entry_timestamp) = ?
            GROUP BY setup_policy_action
            ORDER BY trades DESC
        """, (target_date,)).fetchall()

        if pnl_rows:
            print(f"  Matched-trade P&L by setup_policy_action:")
            print(
                f"  {'action':<28} {'trades':>6} {'wins':>5} "
                f"{'avg_pnl%':>9} {'total_pnl%':>10}"
            )
            print(f"  {'-'*28} {'-'*6} {'-'*5} {'-'*9} {'-'*10}")
            for r in pnl_rows:
                print(
                    f"  {r['spa']:<28} {r['trades']:>6} {r['wins']:>5} "
                    f"{r['avg_pnl_pct']:>9} {r['total_pnl_pct']:>10}"
                )
        else:
            print("  No matched trades for this date.")

        # --- Approved BUY trades where setup was error/unknown, with P&L ---
        print()
        approved_unknown = con.execute("""
            SELECT
                mt.symbol,
                mt.setup_policy_action,
                COALESCE(mt.setup_unknown_reason, mt.setup_policy_reason, '') AS unknown_reason,
                ROUND(mt.realized_pnl_pct, 3) AS pnl_pct,
                mt.won,
                mt.holding_minutes
            FROM matched_trades mt
            WHERE date(mt.entry_timestamp) = ?
              AND (
                  mt.setup_policy_action = 'error'
                  OR mt.setup_unknown_reason IS NOT NULL
              )
            ORDER BY mt.entry_timestamp
        """, (target_date,)).fetchall()

        if approved_unknown:
            print(f"  Approved buys with unknown/error setup (P&L detail):")
            print(
                f"  {'symbol':<8} {'action':<8} {'pnl%':>7} {'won':>4} "
                f"{'hold_min':>9}  reason"
            )
            print(f"  {'-'*8} {'-'*8} {'-'*7} {'-'*4} {'-'*9}  {'-'*35}")
            for r in approved_unknown:
                reason = (r["unknown_reason"] or "")[:50]
                print(
                    f"  {r['symbol']:<8} {r['setup_policy_action']:<8} "
                    f"{r['pnl_pct']:>7} {r['won']:>4} "
                    f"{(r['holding_minutes'] or 0):>9.0f}  {reason}"
                )
        else:
            print("  No matched trades with unknown/error setup for this date.")

        # ── Prediction bucket breakdown (Step 8, Phase 2) ─────────────────
        # Shows approved count, approval rate, and realized P&L by ML prediction
        # bucket so we can track whether the weak-prediction gate is doing work.
        #
        # Reads from trades.ml_prediction_bucket (populated from
        # daily_symbol_predictions cache at signal time).  Joins matched_trades
        # for realized P&L.  Mid and low buckets are observe-only; only
        # weak_below_45 has an active gate (size cap when setup is also degraded).

        print()
        print(f"  Prediction bucket breakdown (BUY signals):")

        bucket_signal_rows = con.execute("""
            SELECT
                COALESCE(ml_prediction_bucket, 'unknown') AS bucket,
                COUNT(*) AS signals,
                SUM(approved) AS approved,
                ROUND(100.0 * SUM(approved) / COUNT(*), 1) AS approval_rate_pct
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            GROUP BY bucket
            ORDER BY
                CASE bucket
                    WHEN 'high_55_plus'  THEN 1
                    WHEN 'mid_50_55'     THEN 2
                    WHEN 'low_45_50'     THEN 3
                    WHEN 'weak_below_45' THEN 4
                    ELSE 5
                END
        """, (target_date,)).fetchall()

        bucket_pnl_rows = con.execute("""
            SELECT
                COALESCE(mt.ml_prediction_bucket, 'unknown') AS bucket,
                COUNT(*) AS trades,
                SUM(mt.won) AS wins,
                ROUND(AVG(mt.realized_pnl_pct), 3) AS avg_pnl_pct,
                ROUND(SUM(mt.realized_pnl_pct), 2) AS total_pnl_pct
            FROM matched_trades mt
            WHERE date(mt.entry_timestamp) = ?
            GROUP BY bucket
            ORDER BY
                CASE bucket
                    WHEN 'high_55_plus'  THEN 1
                    WHEN 'mid_50_55'     THEN 2
                    WHEN 'low_45_50'     THEN 3
                    WHEN 'weak_below_45' THEN 4
                    ELSE 5
                END
        """, (target_date,)).fetchall()

        pnl_by_bucket = {r["bucket"]: r for r in bucket_pnl_rows}

        if bucket_signal_rows:
            print(
                f"  {'bucket':<16} {'signals':>7} {'appr':>5} {'appr%':>6} "
                f"{'trades':>6} {'wins':>5} {'avg_pnl%':>9} {'note'}"
            )
            print(
                f"  {'-'*16} {'-'*7} {'-'*5} {'-'*6} "
                f"{'-'*6} {'-'*5} {'-'*9} {'-'*20}"
            )
            for r in bucket_signal_rows:
                bucket = r["bucket"]
                pnl = pnl_by_bucket.get(bucket)
                trades = pnl["trades"] if pnl else 0
                wins = pnl["wins"] if pnl else 0
                avg_pnl = pnl["avg_pnl_pct"] if pnl else None
                avg_str = f"{avg_pnl:>9.3f}" if avg_pnl is not None else f"{'—':>9}"
                note = (
                    "ACTIVE gate" if bucket == "weak_below_45" else
                    "observe only" if bucket in ("low_45_50", "mid_50_55") else
                    "tie-breaker" if bucket == "high_55_plus" else ""
                )
                print(
                    f"  {bucket:<16} {r['signals']:>7} {r['approved']:>5} "
                    f"{r['approval_rate_pct']:>6} "
                    f"{trades:>6} {wins:>5} {avg_str} {note}"
                )
        else:
            print(f"  No BUY signals with ml_prediction_bucket data for {target_date}.")
            print(f"  (Column added 2026-05-29; prior records will show 'unknown'.)")

        # --- Capture ratio by exit type ---
        # Shows how much of the maximum favorable excursion (MFE) was captured
        # for each exit category.  MFE is sourced from position_momentum_checks
        # at rebuild time.  'winners_became_losers' counts trades where MFE >=
        # 0.40% but the position still closed negative.
        print()
        print(f"  Capture ratio by exit type:")

        capture_rows = con.execute("""
            SELECT
                CASE
                    WHEN exit_reason LIKE 'position_manager_full%'    THEN 'pm_full_exit'
                    WHEN exit_reason LIKE 'position_manager_partial%'  THEN 'pm_partial_exit'
                    WHEN exit_reason LIKE 'synthetic_bracket%'         THEN 'bracket_exit'
                    ELSE COALESCE(SUBSTR(exit_reason, 1, 22), 'unknown')
                END AS exit_type,
                COUNT(*) AS n,
                SUM(CASE WHEN mfe_pct IS NOT NULL THEN 1 ELSE 0 END) AS has_mfe,
                ROUND(AVG(mfe_pct), 3) AS avg_mfe,
                ROUND(AVG(realized_pnl_pct), 3) AS avg_pnl,
                ROUND(AVG(capture_ratio), 3) AS avg_capture,
                SUM(CASE WHEN mfe_pct >= 0.40 AND realized_pnl_pct <= 0 THEN 1 ELSE 0 END)
                    AS winners_became_losers
            FROM matched_trades
            WHERE exit_timestamp IS NOT NULL
              AND DATE(exit_timestamp) = ?
            GROUP BY exit_type
            ORDER BY n DESC
        """, (target_date,)).fetchall()

        if capture_rows:
            print(
                f"  {'exit_type':<22} {'n':>4} {'mfe_n':>5} "
                f"{'avg_mfe%':>9} {'avg_pnl%':>9} {'avg_cap':>8} {'wbl':>4}"
            )
            print(f"  {'-'*22} {'-'*4} {'-'*5} {'-'*9} {'-'*9} {'-'*8} {'-'*4}")
            for r in capture_rows:
                avg_mfe_s = f"{r['avg_mfe']:>9.3f}" if r["avg_mfe"] is not None else f"{'—':>9}"
                avg_pnl_s = f"{r['avg_pnl']:>9.3f}" if r["avg_pnl"] is not None else f"{'—':>9}"
                avg_cap_s = f"{r['avg_capture']:>8.3f}" if r["avg_capture"] is not None else f"{'—':>8}"
                print(
                    f"  {r['exit_type']:<22} {r['n']:>4} {r['has_mfe']:>5} "
                    f"{avg_mfe_s} {avg_pnl_s} {avg_cap_s} {r['winners_became_losers']:>4}"
                )
        else:
            print(f"  No matched trades for {target_date}.")

        print()
        return True


def peak_bucket_report(target_date: str | None = None) -> bool:
    """Realized P&L broken down by MFE (peak profit) bucket.

    Buckets: <0.30%, 0.30-0.60%, 0.60-1.00%, 1.00%+
    Provides a before/after read on how well peak profit is being captured.
    Run with no date for all-time history; run with a date for a single session.
    Requires mfe_pct to be populated (python3 trade_matcher.py).
    """
    import sqlite3

    db_path = BASE_DIR / "trades.db"
    if not db_path.exists():
        print("[WARN] trades.db not found")
        return False

    where_clause = "WHERE mfe_pct IS NOT NULL"
    params: tuple = ()
    label = "all sessions"

    if target_date:
        where_clause += " AND DATE(exit_timestamp) = ?"
        params = (target_date,)
        label = target_date

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        print(f"\n=== Peak Bucket → Realized P&L Report ({label}) ===\n")

        rows = con.execute(f"""
            SELECT
                CASE
                    WHEN mfe_pct >= 1.00 THEN '1.00%+'
                    WHEN mfe_pct >= 0.60 THEN '0.60-1.00%'
                    WHEN mfe_pct >= 0.30 THEN '0.30-0.60%'
                    ELSE '<0.30%'
                END AS peak_bucket,
                COUNT(*) AS trades,
                ROUND(AVG(realized_pnl_pct), 3) AS avg_pnl,
                ROUND(100.0 * SUM(won) / COUNT(*), 1) AS win_rate,
                ROUND(AVG(mfe_pct), 3) AS avg_mfe,
                ROUND(AVG(capture_ratio), 3) AS avg_capture,
                SUM(CASE WHEN realized_pnl_pct < 0 THEN 1 ELSE 0 END) AS exits_below_zero,
                SUM(CASE WHEN mfe_pct >= 0.30 AND realized_pnl_pct <= 0
                         THEN 1 ELSE 0 END) AS winner_became_loser
            FROM matched_trades
            {where_clause}
            GROUP BY peak_bucket
            ORDER BY
                CASE peak_bucket
                    WHEN '1.00%+'     THEN 1
                    WHEN '0.60-1.00%' THEN 2
                    WHEN '0.30-0.60%' THEN 3
                    ELSE 4
                END
        """, params).fetchall()

        if not rows:
            print(f"  No matched trades with MFE data for {label}.")
            print("  Run: python3 trade_matcher.py")
            return True

        print(
            f"  {'peak_bucket':<12} {'trades':>6} {'avg_mfe%':>9} {'avg_pnl%':>9} "
            f"{'win%':>6} {'avg_cap':>8} {'<0':>4} {'wbl':>4}"
        )
        print(
            f"  {'-'*12} {'-'*6} {'-'*9} {'-'*9} {'-'*6} {'-'*8} {'-'*4} {'-'*4}"
        )
        for r in rows:
            avg_mfe_s = f"{r['avg_mfe']:>9.3f}" if r["avg_mfe"] is not None else f"{'—':>9}"
            avg_pnl_s = f"{r['avg_pnl']:>9.3f}" if r["avg_pnl"] is not None else f"{'—':>9}"
            avg_cap_s = f"{r['avg_capture']:>8.3f}" if r["avg_capture"] is not None else f"{'—':>8}"
            print(
                f"  {r['peak_bucket']:<12} {r['trades']:>6} {avg_mfe_s} {avg_pnl_s} "
                f"{r['win_rate']:>6.1f} {avg_cap_s} {r['exits_below_zero']:>4} "
                f"{r['winner_became_loser']:>4}"
            )

        total = con.execute(f"""
            SELECT COUNT(*) AS n, SUM(CASE WHEN mfe_pct IS NOT NULL THEN 1 ELSE 0 END) AS with_mfe
            FROM matched_trades
            {where_clause.replace('WHERE mfe_pct IS NOT NULL', 'WHERE 1=1')}
        """, params).fetchone()

        if total:
            print(f"\n  Total matched trades: {total['n']}  |  With MFE data: {total['with_mfe']}")
        print()
        return True


def winner_became_loser(target_date: str) -> bool:
    """Report closed trades where MFE >= 0.40% but realized P&L ended negative.

    Also shows 'poor capture' trades (MFE >= 0.40%, realized > 0, capture < 0.50)
    so you can see where green positions faded before the exit fired.

    MFE is derived from position_momentum_checks (stored in matched_trades after
    trade_matcher.py rebuild).  Run `python3 trade_matcher.py` first.
    """
    import sqlite3

    db_path = BASE_DIR / "trades.db"
    if not db_path.exists():
        print("[WARN] trades.db not found")
        return False

    MFE_THRESHOLD = 0.40

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        print(f"\n=== Winner-Became-Loser Report: {target_date} ===\n")

        # --- Summary stats for the day ---
        summary = con.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN mfe_pct IS NOT NULL THEN 1 ELSE 0 END) AS has_mfe,
                SUM(CASE WHEN mfe_pct >= ? AND realized_pnl_pct <= 0 THEN 1 ELSE 0 END)
                    AS true_wbl,
                SUM(CASE WHEN mfe_pct >= ? AND realized_pnl_pct > 0
                          AND (capture_ratio IS NULL OR capture_ratio < 0.50)
                          THEN 1 ELSE 0 END) AS poor_capture
            FROM matched_trades
            WHERE DATE(exit_timestamp) = ?
        """, (MFE_THRESHOLD, MFE_THRESHOLD, target_date)).fetchone()

        if not summary or summary["total"] == 0:
            print(f"  No matched trades for {target_date}. Run: python3 trade_matcher.py")
            return True

        print(
            f"  Matched trades : {summary['total']}\n"
            f"  With MFE data  : {summary['has_mfe']}\n"
            f"  Winner→loser   : {summary['true_wbl']}  (MFE >= {MFE_THRESHOLD}%, realized <= 0)\n"
            f"  Poor capture   : {summary['poor_capture']}  (MFE >= {MFE_THRESHOLD}%, capture < 0.50)\n"
        )

        # --- Winner-became-loser trades ---
        wbl_rows = con.execute("""
            SELECT
                symbol, entry_timestamp, exit_timestamp,
                holding_minutes, realized_pnl_pct, mfe_pct, capture_ratio,
                setup_policy_action, exit_reason
            FROM matched_trades
            WHERE DATE(exit_timestamp) = ?
              AND mfe_pct >= ?
              AND realized_pnl_pct <= 0
            ORDER BY realized_pnl_pct ASC
        """, (target_date, MFE_THRESHOLD)).fetchall()

        if wbl_rows:
            print(f"  Winner-became-loser (MFE >= {MFE_THRESHOLD}%, realized <= 0):")
            print(
                f"  {'sym':<6} {'mfe%':>6} {'pnl%':>7} {'ratio':>7} "
                f"{'hold':>7} {'setup':<12} exit_reason"
            )
            print(f"  {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*12} {'-'*40}")
            for r in wbl_rows:
                ratio_s = f"{r['capture_ratio']:>7.3f}" if r["capture_ratio"] is not None else f"{'—':>7}"
                exit_s = (r["exit_reason"] or "")[:50]
                print(
                    f"  {r['symbol']:<6} {r['mfe_pct']:>6.3f} {r['realized_pnl_pct']:>7.3f} "
                    f"{ratio_s} {(r['holding_minutes'] or 0):>7.1f} "
                    f"{(r['setup_policy_action'] or 'none'):<12} {exit_s}"
                )
        else:
            print(f"  No winner-became-loser trades for {target_date}.")

        # --- Poor capture trades ---
        print()
        poor_rows = con.execute("""
            SELECT
                symbol, holding_minutes, realized_pnl_pct, mfe_pct, capture_ratio,
                setup_policy_action, exit_reason
            FROM matched_trades
            WHERE DATE(exit_timestamp) = ?
              AND mfe_pct >= ?
              AND realized_pnl_pct > 0
              AND (capture_ratio IS NULL OR capture_ratio < 0.50)
            ORDER BY capture_ratio ASC NULLS LAST
        """, (target_date, MFE_THRESHOLD)).fetchall()

        if poor_rows:
            print(f"  Poor capture (MFE >= {MFE_THRESHOLD}%, realized > 0, capture < 0.50):")
            print(
                f"  {'sym':<6} {'mfe%':>6} {'pnl%':>7} {'ratio':>7} "
                f"{'hold':>7} {'setup':<12} exit_reason"
            )
            print(f"  {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*12} {'-'*40}")
            for r in poor_rows:
                ratio_s = f"{r['capture_ratio']:>7.3f}" if r["capture_ratio"] is not None else f"{'—':>7}"
                exit_s = (r["exit_reason"] or "")[:50]
                print(
                    f"  {r['symbol']:<6} {r['mfe_pct']:>6.3f} {r['realized_pnl_pct']:>7.3f} "
                    f"{ratio_s} {(r['holding_minutes'] or 0):>7.1f} "
                    f"{(r['setup_policy_action'] or 'none'):<12} {exit_s}"
                )
        else:
            print(f"  No poor-capture trades for {target_date}.")

        # --- All matched trades today sorted by capture_ratio ---
        print()
        all_rows = con.execute("""
            SELECT
                symbol, realized_pnl_pct, mfe_pct, capture_ratio,
                setup_policy_action
            FROM matched_trades
            WHERE DATE(exit_timestamp) = ?
              AND mfe_pct IS NOT NULL
            ORDER BY capture_ratio ASC NULLS FIRST
        """, (target_date,)).fetchall()

        if all_rows:
            print(f"  All trades with MFE (sorted by capture ratio, worst first):")
            print(f"  {'sym':<6} {'mfe%':>6} {'pnl%':>7} {'ratio':>7}  setup")
            print(f"  {'-'*6} {'-'*6} {'-'*7} {'-'*7}  {'-'*14}")
            for r in all_rows:
                ratio_s = f"{r['capture_ratio']:>7.3f}" if r["capture_ratio"] is not None else f"{'—':>7}"
                print(
                    f"  {r['symbol']:<6} {r['mfe_pct']:>6.3f} {r['realized_pnl_pct']:>7.3f} "
                    f"{ratio_s}  {r['setup_policy_action'] or 'none'}"
                )

        print()
        return True


def conviction_stack_report(target_date: str) -> bool:
    """Show how conviction stack caps distributed and which source dominated on a given date."""
    db_path = BASE_DIR / "trades.db"
    if not db_path.exists():
        print("[WARN] trades.db not found")
        return False

    import sqlite3
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        print(f"\n=== Conviction Stack Report: {target_date} ===\n")

        rows = con.execute("""
            SELECT
                effective_size_cap_pct,
                dominant_limiter,
                buy_opportunity_recommendation,
                setup_policy_action,
                session_momentum_severity,
                trader_brain_score,
                ml_prediction_bucket,
                approved
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            ORDER BY timestamp
        """, (target_date,)).fetchall()

        if not rows:
            print(f"  No BUY signals for {target_date}.")
            return True

        total = len(rows)
        approved = sum(1 for r in rows if r["approved"])
        capped = sum(1 for r in rows if r["effective_size_cap_pct"] is not None)
        uncapped = total - capped

        print(f"  BUY signals: {total}  approved: {approved}  capped: {capped}  uncapped: {uncapped}\n")

        # Section 1: Cap distribution
        print("  Cap Distribution (max_position_size_pct_override before execution):")
        print(f"  {'Cap Level':<20} {'Count':>6} {'Appr':>5} {'Appr%':>6}")
        print(f"  {'-'*20} {'-'*6} {'-'*5} {'-'*6}")

        cap_buckets = [
            ("uncapped (None)", lambda r: r["effective_size_cap_pct"] is None),
            ("1.25%+",          lambda r: r["effective_size_cap_pct"] is not None and float(r["effective_size_cap_pct"]) >= 1.25),
            ("0.90–1.25%",      lambda r: r["effective_size_cap_pct"] is not None and 0.90 <= float(r["effective_size_cap_pct"]) < 1.25),
            ("0.80–0.90%",      lambda r: r["effective_size_cap_pct"] is not None and 0.80 <= float(r["effective_size_cap_pct"]) < 0.90),
            ("0.75–0.80%",      lambda r: r["effective_size_cap_pct"] is not None and 0.75 <= float(r["effective_size_cap_pct"]) < 0.80),
            ("0.65–0.75%",      lambda r: r["effective_size_cap_pct"] is not None and 0.65 <= float(r["effective_size_cap_pct"]) < 0.75),
            ("0.50–0.65%",      lambda r: r["effective_size_cap_pct"] is not None and 0.50 <= float(r["effective_size_cap_pct"]) < 0.65),
            ("below 0.50%",     lambda r: r["effective_size_cap_pct"] is not None and float(r["effective_size_cap_pct"]) < 0.50),
        ]

        for label, pred in cap_buckets:
            bucket_rows = [r for r in rows if pred(r)]
            if not bucket_rows:
                continue
            n = len(bucket_rows)
            appr = sum(1 for r in bucket_rows if r["approved"])
            pct = f"{appr/n*100:.0f}%" if n else "—"
            print(f"  {label:<20} {n:>6} {appr:>5} {pct:>6}")

        # Section 2: Dominant limiter breakdown
        print(f"\n  Dominant Limiter Breakdown (which source set the tightest pre-execution cap):")
        print(f"  {'Limiter':<28} {'Count':>6} {'Appr':>5} {'Appr%':>6}")
        print(f"  {'-'*28} {'-'*6} {'-'*5} {'-'*6}")

        from collections import Counter
        limiter_counts: Counter = Counter()
        limiter_approved: Counter = Counter()
        for r in rows:
            lim = r["dominant_limiter"] or "unknown"
            limiter_counts[lim] += 1
            if r["approved"]:
                limiter_approved[lim] += 1

        for lim, n in limiter_counts.most_common():
            appr = limiter_approved[lim]
            pct = f"{appr/n*100:.0f}%" if n else "—"
            flag = " ← dominant" if capped > 0 and n / max(capped, 1) > 0.40 and lim != "uncapped" else ""
            print(f"  {lim:<28} {n:>6} {appr:>5} {pct:>6}{flag}")

        # Section 3: Stacking analysis — top combos for capped trades
        capped_rows = [r for r in rows if r["effective_size_cap_pct"] is not None]
        if capped_rows:
            print(f"\n  Cap Stacking: top combos among {len(capped_rows)} capped signals")
            print(f"  {'dominant_limiter':<26} {'buy_opp':<20} {'setup_action':<12} {'N':>4} {'Appr':>5}")
            print(f"  {'-'*26} {'-'*20} {'-'*12} {'-'*4} {'-'*5}")

            combo_counts: Counter = Counter()
            combo_approved: Counter = Counter()
            for r in capped_rows:
                key = (
                    (r["dominant_limiter"] or "unknown")[:25],
                    (r["buy_opportunity_recommendation"] or "—")[:19],
                    (r["setup_policy_action"] or "—")[:11],
                )
                combo_counts[key] += 1
                if r["approved"]:
                    combo_approved[key] += 1

            for combo, n in combo_counts.most_common(5):
                appr = combo_approved[combo]
                print(f"  {combo[0]:<26} {combo[1]:<20} {combo[2]:<12} {n:>4} {appr:>5}")

        print()
        return True


def buy_opportunity_report(target_date: str) -> bool:
    """Validate buy-opportunity sizing: bucket distribution, P&L correlation, cap dominance."""
    db_path = BASE_DIR / "trades.db"
    if not db_path.exists():
        print("[WARN] trades.db not found")
        return False

    import sqlite3
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        print(f"\n=== Buy-Opportunity Sizing Report: {target_date} ===\n")

        # Section 1: Signal counts and approval rate by bucket
        rows = con.execute("""
            SELECT
                buy_opportunity_recommendation AS rec,
                COUNT(*) AS signals,
                SUM(approved) AS approved,
                AVG(CAST(approved AS REAL)) * 100 AS appr_pct,
                MIN(buy_opportunity_score) AS min_score,
                MAX(buy_opportunity_score) AS max_score,
                AVG(buy_opportunity_score) AS avg_score
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND buy_opportunity_recommendation IS NOT NULL
            GROUP BY buy_opportunity_recommendation
            ORDER BY AVG(buy_opportunity_score) DESC
        """, (target_date,)).fetchall()

        if not rows:
            print(f"  No scored BUY signals for {target_date}.")
            return True

        print("  Signal Counts by Buy-Opportunity Bucket:")
        print(f"  {'Bucket':<22} {'Signals':>8} {'Appr':>5} {'Appr%':>6} {'AvgScore':>9}")
        print(f"  {'-'*22} {'-'*8} {'-'*5} {'-'*6} {'-'*9}")
        for r in rows:
            pct = f"{r['appr_pct']:.0f}%" if r["appr_pct"] is not None else "—"
            avg_s = f"{r['avg_score']:.1f}" if r["avg_score"] is not None else "—"
            print(f"  {(r['rec'] or '—'):<22} {r['signals']:>8} {(r['approved'] or 0):>5} {pct:>6} {avg_s:>9}")

        # Section 2: Realized P&L correlation by bucket
        pnl_rows = con.execute("""
            SELECT
                t.buy_opportunity_recommendation AS rec,
                COUNT(mt.id) AS exits,
                AVG(mt.realized_pnl_pct) AS avg_pnl,
                SUM(CASE WHEN mt.realized_pnl_pct > 0 THEN 1 ELSE 0 END) AS wins,
                AVG(mt.capture_ratio) AS avg_capture
            FROM trades t
            JOIN matched_trades mt
              ON mt.symbol = t.symbol
             AND ABS(julianday(mt.entry_timestamp) - julianday(t.timestamp)) < 0.01
            WHERE date(t.timestamp) = ?
              AND t.action = 'buy'
              AND t.approved = 1
              AND t.buy_opportunity_recommendation IS NOT NULL
            GROUP BY t.buy_opportunity_recommendation
            ORDER BY AVG(mt.realized_pnl_pct) DESC
        """, (target_date,)).fetchall()

        if pnl_rows:
            print(f"\n  Realized P&L by Bucket (from matched_trades):")
            print(f"  {'Bucket':<22} {'Exits':>6} {'AvgPnL':>8} {'WinRate':>8} {'AvgCap':>8}")
            print(f"  {'-'*22} {'-'*6} {'-'*8} {'-'*8} {'-'*8}")
            for r in pnl_rows:
                avg_pnl_s = f"{r['avg_pnl']:+.3f}%" if r["avg_pnl"] is not None else "—"
                win_rate_s = f"{r['wins']/r['exits']*100:.0f}%" if r["exits"] else "—"
                cap_s = f"{r['avg_capture']:.3f}" if r["avg_capture"] is not None else "—"
                print(f"  {(r['rec'] or '—'):<22} {r['exits']:>6} {avg_pnl_s:>8} {win_rate_s:>8} {cap_s:>8}")
        else:
            print(f"\n  No matched exit data yet for {target_date}.")

        # Section 3: Cap dominance check
        cap_rows = con.execute("""
            SELECT
                buy_opportunity_recommendation AS rec,
                dominant_limiter,
                COUNT(*) AS n
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND buy_opportunity_recommendation IS NOT NULL
            GROUP BY buy_opportunity_recommendation, dominant_limiter
            ORDER BY rec, n DESC
        """, (target_date,)).fetchall()

        if cap_rows:
            print(f"\n  Cap Dominance (buy_opportunity bucket vs actual dominant limiter):")
            print(f"  {'Bucket':<22} {'Dominant Limiter':<28} {'Count':>6}")
            print(f"  {'-'*22} {'-'*28} {'-'*6}")
            for r in cap_rows:
                print(f"  {(r['rec'] or '—'):<22} {(r['dominant_limiter'] or 'uncapped'):<28} {r['n']:>6}")

        # Section 4: Double-counting flag
        dc_rows = con.execute("""
            SELECT COUNT(*) AS n
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND setup_policy_action IN ('block', 'error')
              AND buy_opportunity_recommendation = 'avoid'
        """, (target_date,)).fetchone()
        if dc_rows and dc_rows["n"]:
            print(f"\n  ⚠ Double-penalized signals (setup block/error AND buy_opp avoid): {dc_rows['n']}")
            print("    These trades are penalized by both setup_policy and buy_opportunity.")
            print("    No action required — both signals are independently valid — but note the overlap.")

        print()
        return True


def claude_context_audit(target_date: str) -> bool:
    """Approval rate trend, rejection mix, and Claude confidence distribution around context changes."""
    db_path = BASE_DIR / "trades.db"
    if not db_path.exists():
        print("[WARN] trades.db not found")
        return False

    import sqlite3
    baseline_date = "2026-05-29"  # date before market_context_summary was added

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        print(f"\n=== Claude Context Audit: {target_date} ===\n")
        print(f"  Baseline: {baseline_date} (pre-market_context_summary). Target: {target_date}\n")

        # Section 1: Approval rate by date (recent N sessions)
        daily_rows = con.execute("""
            SELECT
                date(timestamp) AS day,
                COUNT(*) AS total,
                SUM(approved) AS approved,
                AVG(CAST(approved AS REAL)) * 100 AS appr_pct
            FROM trades
            WHERE action = 'buy'
              AND date(timestamp) >= date(?, '-14 days')
            GROUP BY date(timestamp)
            ORDER BY date(timestamp)
        """, (target_date,)).fetchall()

        if daily_rows:
            print("  Daily BUY Approval Rate (last 14 days):")
            print(f"  {'Date':<12} {'Total':>6} {'Appr':>5} {'Rate':>6}  Note")
            print(f"  {'-'*12} {'-'*6} {'-'*5} {'-'*6}  {'-'*20}")
            for r in daily_rows:
                pct = f"{r['appr_pct']:.0f}%" if r["appr_pct"] is not None else "—"
                note = ""
                if r["day"] == baseline_date:
                    note = "← pre-context-summary"
                elif r["day"] > baseline_date:
                    note = "post-context-summary"
                print(f"  {r['day']:<12} {r['total']:>6} {(r['approved'] or 0):>5} {pct:>6}  {note}")

        # Section 2: Rejection category mix for target_date
        rej_rows = con.execute("""
            SELECT
                rejection_reason,
                COUNT(*) AS n
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND approved = 0
              AND rejection_reason IS NOT NULL
            ORDER BY n DESC
            LIMIT 12
        """, (target_date,)).fetchall()

        if rej_rows:
            print(f"\n  Top Rejection Reasons for {target_date}:")
            print(f"  {'Reason (prefix)':<40} {'Count':>6}")
            print(f"  {'-'*40} {'-'*6}")
            for r in rej_rows:
                reason = (r["rejection_reason"] or "")[:39]
                print(f"  {reason:<40} {r['n']:>6}")

        # Section 3: Claude confidence distribution for approved trades
        conf_rows = con.execute("""
            SELECT
                confidence,
                COUNT(*) AS n,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
            FROM trades
            WHERE action = 'buy'
              AND approved = 1
              AND confidence IS NOT NULL
              AND date(timestamp) >= date(?, '-30 days')
            GROUP BY confidence
            ORDER BY n DESC
        """, (target_date,)).fetchall()

        if conf_rows:
            print(f"\n  Claude Confidence Distribution (approved BUYs, last 30 days):")
            print(f"  {'Confidence':<14} {'Count':>6} {'Pct':>6}")
            print(f"  {'-'*14} {'-'*6} {'-'*6}")
            for r in conf_rows:
                print(f"  {(r['confidence'] or '—'):<14} {r['n']:>6} {r['pct']:>5.1f}%")

        print(
            "\n  NOTE: Meaningful before/after comparison requires 5+ post-change sessions."
            "\n  Check again after 2026-06-06 for statistically meaningful patterns."
        )
        print()
        return True


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

    if command == "rejected-outcomes":
        return 0 if rejected_outcomes_health(target_date) else 1

    if command == "auto-buy":
        return 0 if auto_buy_health(target_date) else 1

    if command == "decision-snapshots":
        return 0 if decision_snapshot_health(target_date) else 1

    if command == "policy-artifacts":
        return 0 if policy_artifact_health() else 1

    if command == "retention":
        return 0 if retention_health() else 1

    if command == "order-health":
        return 0 if order_health(target_date) else 1

    if command == "migration-status":
        return 0 if migration_status_check() else 1

    if command == "setup-breakdown":
        return 0 if setup_breakdown(target_date) else 1

    if command == "winner-became-loser":
        return 0 if winner_became_loser(target_date) else 1

    if command == "peak-bucket-report":
        date_arg = sys.argv[2] if len(sys.argv) > 2 else None
        return 0 if peak_bucket_report(date_arg) else 1

    if command == "conviction-stack-report":
        return 0 if conviction_stack_report(target_date) else 1

    if command == "buy-opportunity-report":
        return 0 if buy_opportunity_report(target_date) else 1

    if command == "claude-context-audit":
        return 0 if claude_context_audit(target_date) else 1

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
        checks.append(run("Strong-Day Participation", ["strong_day_participation_report.py", "--date", target_date, "--write-db"]))
        checks.append(run("Rejected Outcomes", ["ops_check.py", "rejected-outcomes", target_date]))
        checks.append(run("Auto-Buy Candidates", ["ops_check.py", "auto-buy", target_date]))
        checks.append(run("Auto-Buy Outcomes", ["auto_buy_outcome_report.py", "--date", target_date]))
        checks.append(run("Decision Snapshots", ["ops_check.py", "decision-snapshots", target_date]))
        checks.append(run("Policy Artifacts", ["ops_check.py", "policy-artifacts"]))
        checks.append(run("Retention Policy", ["ops_check.py", "retention"]))
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

    script = COMMANDS[command][0]
    extra = COMMANDS[command][1:]

    if command in ("filters", "blocked", "event-attribution", "intelligence", "context",
                   "learning", "predictions", "signal-lessons", "trends",
                   "prediction-validation", "auto-buy-outcomes", "strong-days"):
        args = [script] + extra + ["--date", target_date]
    elif command in ("drawdown", "post", "adaptive_impact", "strategy_intelligence"):
        args = [script] + extra + [target_date]
    else:
        args = [script] + extra

    ok = run(command.title(), args)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
