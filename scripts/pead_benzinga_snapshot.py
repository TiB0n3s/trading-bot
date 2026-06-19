#!/usr/bin/env python3
"""Build-forward PIT snapshotter for post-earnings drift (PEAD), Polygon-Benzinga source.

Research-only, no trade authority. This closes the ingestion gap surfaced on
2026-06-19: ``external_signal_features`` was empty because the ``ingest-jsonl``
half of the PEAD pipeline was never wired to a real source.

What it does
------------
Each run fetches reported earnings from the Polygon-Benzinga earnings endpoint
(``GET /benzinga/v1/earnings``) over a rolling window, and writes one PEAD event
row per reported name into ``external_signal_features`` (feature_family=earnings),
**reusing the validated ``post_earnings_drift_research.py ingest-jsonl`` writer**
so the leakage checks and the on-disk contract are identical to a hand-built slice.

Point-in-time semantics
-----------------------
* ``feature_ts`` and ``available_at`` are both the **announcement datetime in UTC**
  (date + Benzinga ET ``time`` -> UTC). The surprise (actual vs. consensus) is
  knowable at the announcement, so this is leakage-free; making them equal also
  makes re-runs idempotent (upsert on the UNIQUE key). The PEAD entry anchor is
  the first 1m bar at/after ``available_at`` -- correct for both BMO and AMC.
* ``release_lag_seconds`` records (capture_time - announcement_time) for audit.
* We only write a row once ``actual_eps`` is present (i.e. genuinely reported);
  we never claim to have known a print before it happened. This is *build-forward*,
  not backfill.

Residual caveat (documented, not hidden)
---------------------------------------
``estimated_eps`` is Benzinga's pre-print consensus as carried on the reported
record. If Benzinga ever *restates* that estimate after the print, capturing it
~1 day later (daily cron) could pick up a revised number. Running daily minimises
the window. A future enhancement can additionally snapshot the consensus for
*upcoming* names each day to archive the full pre-print revision history; v1
captures the reported event with its consensus + actual + surprise, which is what
the PEAD scan needs.

This script does not interpret results and grants no authority.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
EARNINGS_TZ = ZoneInfo("America/New_York")  # Benzinga `time` is US/Eastern
BENZINGA_EARNINGS_URL = "https://api.polygon.io/benzinga/v1/earnings"
SOURCE = "polygon_benzinga_pit_snapshot"
REPORT_VERSION = "pead_benzinga_snapshot_v1"
RUNTIME_EFFECT = "research_only_no_trade_authority"

# Market session boundaries in ET for report-timing classification.
_OPEN = (9, 30)
_CLOSE = (16, 0)


def _canonical_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _announcement_dt(date_str: str, time_str: str | None) -> tuple[datetime, str]:
    """Return (announcement_dt_utc, report_timing).

    Benzinga `time` is ET. Missing/"00:00:00" time -> conservatively treat as
    after-close (entry next open) and flag the assumption.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    t = (time_str or "").strip()
    if not t or t == "00:00:00":
        local = datetime(d.year, d.month, d.day, _CLOSE[0], _CLOSE[1], 0, tzinfo=EARNINGS_TZ)
        return local.astimezone(UTC), "unknown_assumed_after_close"
    try:
        hh, mm, *rest = (int(x) for x in t.split(":"))
        ss = rest[0] if rest else 0
    except ValueError:
        local = datetime(d.year, d.month, d.day, _CLOSE[0], _CLOSE[1], 0, tzinfo=EARNINGS_TZ)
        return local.astimezone(UTC), "unknown_assumed_after_close"
    local = datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=EARNINGS_TZ)
    minutes = hh * 60 + mm
    if minutes < _OPEN[0] * 60 + _OPEN[1]:
        timing = "before_open"
    elif minutes >= _CLOSE[0] * 60 + _CLOSE[1]:
        timing = "after_close"
    else:
        timing = "during_session"
    return local.astimezone(UTC), timing


def _fnum(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _fetch_all(api_key: str, gte: str, lte: str, limit: int, max_pages: int) -> list[dict]:
    params = {
        "date.gte": gte,
        "date.lte": lte,
        "limit": str(limit),
        "order": "asc",
        "sort": "date",
        "apiKey": api_key,
    }
    url = f"{BENZINGA_EARNINGS_URL}?{urllib.parse.urlencode(params)}"
    out: list[dict] = []
    for _ in range(max_pages):
        req = urllib.request.Request(url, headers={"User-Agent": "trading-bot-pead-snapshot/1"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (trusted host)
            body = json.loads(resp.read().decode("utf-8"))
        out.extend(body.get("results") or [])
        next_url = body.get("next_url")
        if not next_url:
            break
        sep = "&" if "?" in next_url else "?"
        url = f"{next_url}{sep}apiKey={urllib.parse.quote(api_key)}"
    return out


def _to_payload(rec: dict, now_utc: datetime) -> dict | None:
    ticker = str(rec.get("ticker") or "").strip().upper()
    date_str = str(rec.get("date") or "").strip()
    est_eps = _fnum(rec.get("estimated_eps"))
    act_eps = _fnum(rec.get("actual_eps"))
    # Require a reported print AND a pre-print consensus: both are needed for a
    # clean surprise. This naturally drops illiquid names with no coverage.
    if not ticker or not date_str or est_eps is None or act_eps is None:
        return None

    ann_dt, timing = _announcement_dt(date_str, rec.get("time"))
    ann_ts = _canonical_utc(ann_dt)
    release_lag = max(0.0, (now_utc - ann_dt).total_seconds())

    eps_surprise_percent = _fnum(rec.get("eps_surprise_percent"))
    if eps_surprise_percent is None and est_eps not in (None, 0):
        eps_surprise_percent = (act_eps - est_eps) / abs(est_eps)
    est_rev = _fnum(rec.get("estimated_revenue"))
    act_rev = _fnum(rec.get("actual_revenue"))
    rev_surprise_percent = _fnum(rec.get("revenue_surprise_percent"))
    if rev_surprise_percent is None and est_rev not in (None, 0) and act_rev is not None:
        rev_surprise_percent = (act_rev - est_rev) / abs(est_rev)

    # Top-level keys other than the reserved event fields each become a feature
    # row (via _scalar_items), and all scanned numeric features share one
    # family-wise multiple-testing correction. So keep ONLY genuine drift-signal
    # scalars at top level (the surprises) plus `report_timing` (the regime
    # splitter). Everything else -- raw est/actual levels, capture lag, vendor
    # metadata -- goes into `meta` (a non-scalar dict: ignored by _scalar_items,
    # but preserved in raw_json for audit and clean-surprise recomputation).
    payload: dict[str, object] = {
        "symbol": ticker,
        "earnings_ts": ann_ts,
        "available_at": ann_ts,
        "source": SOURCE,
        "source_url_or_ref": f"benzinga_id:{rec.get('benzinga_id')}",
        "revision_policy": "point_in_time_as_reported",
        "report_timing": timing,
        "eps_surprise_percent": eps_surprise_percent,
        "revenue_surprise_percent": rev_surprise_percent,
        "meta": {
            "estimated_eps": est_eps,
            "actual_eps": act_eps,
            "estimated_revenue": est_rev,
            "actual_revenue": act_rev,
            "release_lag_seconds": release_lag,
            "company_name": rec.get("company_name"),
            "fiscal_period": rec.get("fiscal_period"),
            "fiscal_year": rec.get("fiscal_year"),
            "importance": rec.get("importance"),
            "date_status": rec.get("date_status"),
            "currency": rec.get("currency"),
            "benzinga_time_et": rec.get("time"),
            "benzinga_last_updated": rec.get("last_updated"),
            "captured_at": _canonical_utc(now_utc),
            "snapshot_version": REPORT_VERSION,
        },
    }
    # Drop None signal values so they don't create empty feature rows.
    return {k: v for k, v in payload.items() if v is not None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=5,
                        help="Window start = today - lookback. Catches late prints/updates.")
    parser.add_argument("--start-date", help="Override window start (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Override window end (YYYY-MM-DD).")
    parser.add_argument("--limit", type=int, default=1000, help="Page size (max 50000).")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument(
        "--db-path",
        default=str(ROOT / "data" / "pead_research" / "pead_research.db"),
        help=(
            "PEAD research DB. Deliberately NOT trades.db: the live bot actively "
            "manages trades.db (observed dropping research tables), and bars can't "
            "share the production bar_pattern_features (20+ readers). Self-contained."
        ),
    )
    parser.add_argument("--out-dir", default=str(ROOT / "data" / "earnings_events" / "benzinga_pit"))
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch + write the JSONL artifact, but skip the ingest into the DB.")
    args = parser.parse_args(argv)

    api_key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not api_key:
        print(json.dumps({"report_version": REPORT_VERSION, "runtime_effect": RUNTIME_EFFECT,
                          "error": "POLYGON_API_KEY not configured"}), file=sys.stderr)
        return 2

    now_utc = datetime.now(UTC)
    end = args.end_date or now_utc.date().isoformat()
    start = args.start_date or (now_utc.date() - timedelta(days=args.lookback_days)).isoformat()

    try:
        records = _fetch_all(api_key, start, end, args.limit, args.max_pages)
    except Exception as exc:  # noqa: BLE001 - cron-facing; surface and exit non-zero
        print(json.dumps({"report_version": REPORT_VERSION, "runtime_effect": RUNTIME_EFFECT,
                          "error": f"fetch_failed: {exc}", "window": [start, end]}), file=sys.stderr)
        return 1

    payloads = [p for rec in records if (p := _to_payload(rec, now_utc)) is not None]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"benzinga_pit_{end}_{stamp}.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for p in payloads:
            fh.write(json.dumps(p, sort_keys=True) + "\n")

    summary = {
        "report_version": REPORT_VERSION,
        "runtime_effect": RUNTIME_EFFECT,
        "window": [start, end],
        "records_fetched": len(records),
        "reported_payloads": len(payloads),
        "artifact": str(out_path),
        "dry_run": bool(args.dry_run),
    }

    if args.dry_run or not payloads:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    # Reuse the validated ingest path (validation + leakage check + upsert).
    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "post_earnings_drift_research.py"),
        "--db-path", args.db_path,
        "ingest-jsonl", "--input", str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    summary["ingest_returncode"] = proc.returncode
    try:
        summary["ingest_result"] = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        summary["ingest_stdout"] = proc.stdout[-2000:]
    if proc.returncode != 0:
        summary["ingest_stderr"] = proc.stderr[-2000:]
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
