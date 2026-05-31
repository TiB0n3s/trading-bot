from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from repositories.label_features_repo import LabelFeaturesRepository
from repositories.live_features_repo import LiveFeaturesRepository


def _log_stats(base_dir: Path, path: str, patterns: dict[str, str]) -> dict:
    stats = {key: 0 for key in patterns}
    first_ts = None
    last_ts = None
    last_matches = {key: None for key in patterns}

    log_path = base_dir / path
    if not log_path.exists():
        return {
            "exists": False,
            "path": str(log_path),
            "lines": 0,
            "first_ts": None,
            "last_ts": None,
            "stats": stats,
            "last_matches": last_matches,
        }

    lines = log_path.read_text(errors="replace").splitlines()
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
        "path": str(log_path),
        "lines": len(lines),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "stats": stats,
        "last_matches": last_matches,
    }


def _parse_iso_datetime(value):
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


def run_feature_health(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"
    live_repo = LiveFeaturesRepository(db_path)
    label_repo = LabelFeaturesRepository(db_path)

    print()
    print("=" * 72)
    print(f"  Feature Pipeline Health - {target_date}")
    print("=" * 72)

    ok = True

    print("Scripts")
    for script in ("run_live_features.sh", "run_label_features.sh", "live_features.py", "label_features.py"):
        path = base_dir / script
        print(f"  {script:<24} {'present' if path.exists() else 'missing'}")
        if not path.exists():
            ok = False

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

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
        repo = live_repo if table == "feature_snapshots" else label_repo
        if not repo.table_exists(table):
            print(f"  {table:<20} missing")
            ok = False
            continue

        actual = repo.table_columns(table)
        missing = [c for c in cols if c not in actual]
        if missing:
            print(f"  {table:<20} missing columns: {missing}")
            ok = False
        else:
            print(f"  {table:<20} ok ({len(actual)} columns)")

    print()
    print("Current DB rows")
    rows = live_repo.snapshot_summary()
    print(f"  feature_snapshots       {rows['n']:>8}  {rows['min_ts'] or '-'} -> {rows['max_ts'] or '-'}")

    label_rows = label_repo.label_summary()
    print(f"  labeled_setups          {label_rows['n']:>8}  {label_rows['min_ts'] or '-'} -> {label_rows['max_ts'] or '-'}")

    unlabeled = live_repo.unlabeled_snapshot_count()
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
        stats = _log_stats(base_dir, log_name, patterns)
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


def run_feature_watch(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"
    live_repo = LiveFeaturesRepository(db_path)
    label_repo = LabelFeaturesRepository(db_path)

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

    if not live_repo.table_exists("feature_snapshots") or not label_repo.table_exists("labeled_setups"):
        print("[FAIL] feature_snapshots or labeled_setups table is missing")
        return False

    snapshot_count = live_repo.session_snapshot_summary(target_date)
    label_count = label_repo.session_label_summary(target_date)

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
    rows = live_repo.snapshot_hour_rows(target_date)
    if rows:
        for r in rows:
            print(f"  {r['hour']}:00  rows={r['n']:>5}  symbols={r['symbols_seen']:>3}")
    else:
        print("  none")

    print()
    print("Labels by outcome")
    rows = label_repo.outcome_rows(target_date)
    if rows:
        for r in rows:
            print(f"  {r['outcome_label']:<14} {r['n']}")
    else:
        print("  none")

    seen_rows = live_repo.seen_symbol_rows(target_date)
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
    unlabeled_rows = live_repo.unlabeled_snapshot_rows(target_date)

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
    rows = live_repo.recent_snapshot_rows(target_date)
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
