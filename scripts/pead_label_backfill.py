#!/usr/bin/env python3
"""Backfill the 1m bars needed to label PEAD earnings events, into the research DB.

Research-only, no trade authority. Resolves the bar-universe-overlap bottleneck:
the production ``bar_pattern_features`` table (and the CSV archive) only cover the
bot's ~77-symbol trading universe, so PEAD earnings events for any other name can
never be labelled against it.

This writes into the **self-contained PEAD research DB** (the same DB the daily
snapshotter ingests earnings events into), NOT trades.db. trades.db is owned and
actively managed by the live bot (observed dropping research tables), and the
production ``bar_pattern_features`` has 20+ live readers + archival jobs, so
arbitrary earnings tickers must never go there.

Pipeline
--------
1. Ensure a minimal ``bar_pattern_features`` table exists (persistent bar cache)
   alongside the ``external_signal_features`` the snapshotter already wrote here.
2. For each earnings event symbol (optionally filtered by Benzinga importance),
   fetch the 1m RTH bars spanning [event - pre, event + post] from the Polygon
   aggregates API and insert them (INSERT OR IGNORE -> idempotent).

The Sat PEAD scan then runs with ``--db-path <research-db>`` and can label any
event whose forward sessions have elapsed and whose bars we fetched.

Point-in-time note: bars are objective post-hoc prices; fetching them later is not
look-ahead. The PIT discipline lives in the *event* row (available_at), which the
scan uses as the entry anchor. We keep only Regular Trading Hours bars so the
"session close" the scan reads is the 16:00 ET close, not an after-hours print.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MARKET_TZ = ZoneInfo("America/New_York")
AGGS_URL = "https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{frm}/{to}"
FEATURE_VERSION = "pead_label_backfill_v1"
RUNTIME_EFFECT = "research_only_no_trade_authority"
REPORT_VERSION = "pead_label_backfill_v1"
_RTH_OPEN_MIN = 9 * 60 + 30
_RTH_CLOSE_MIN = 16 * 60

BAR_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bar_pattern_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    bar_timestamp TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    feature_version TEXT NOT NULL DEFAULT 'pead_label_backfill_v1',
    runtime_effect TEXT NOT NULL DEFAULT 'research_only_no_trade_authority',
    feature_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(symbol, bar_timestamp, timeframe, feature_version)
)
"""


def _events(research: sqlite3.Connection, min_importance: int) -> list[tuple[str, str, int | None]]:
    """Return distinct (symbol, available_at, importance) earnings events."""
    rows = research.execute(
        """
        SELECT symbol, available_at, raw_json
        FROM external_signal_features
        WHERE feature_family = 'earnings' AND feature_name = 'event_observed'
        """
    ).fetchall()
    out: list[tuple[str, str, int | None]] = []
    for symbol, available_at, raw in rows:
        importance = None
        try:
            meta = (json.loads(raw) if raw else {}).get("meta", {})
            importance = meta.get("importance")
        except (json.JSONDecodeError, AttributeError):
            pass
        if min_importance and (importance is None or int(importance) < min_importance):
            continue
        out.append((str(symbol).upper(), str(available_at), importance))
    return out


def _windows_by_symbol(
    events: list[tuple[str, str, int | None]], pre_days: int, post_days: int
) -> dict[str, tuple[str, str]]:
    spans: dict[str, tuple[str, str]] = {}
    for symbol, available_at, _imp in events:
        try:
            d = datetime.fromisoformat(available_at.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        frm = (d - timedelta(days=pre_days)).isoformat()
        to = (d + timedelta(days=post_days)).isoformat()
        if symbol not in spans:
            spans[symbol] = (frm, to)
        else:
            cur = spans[symbol]
            spans[symbol] = (min(cur[0], frm), max(cur[1], to))
    return spans


def _existing_max_date(research: sqlite3.Connection, symbol: str) -> str | None:
    row = research.execute(
        "SELECT MAX(substr(bar_timestamp,1,10)) FROM bar_pattern_features "
        "WHERE symbol = ? AND timeframe = '1m'",
        (symbol,),
    ).fetchone()
    return row[0] if row and row[0] else None


def _urlopen_json(url: str, retry_attempts: int, retry_sleep: float) -> dict:
    """GET JSON with 429-aware retry (mirrors the bot's polygon service: ~5 req/min)."""
    attempts = retry_attempts + 1
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers={"User-Agent": "trading-bot-pead-backfill/1"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 (trusted host)
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= attempts - 1:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                wait = float(retry_after) if retry_after else retry_sleep
            except (TypeError, ValueError):
                wait = retry_sleep
            time.sleep(max(retry_sleep, wait))
    raise RuntimeError("unreachable polygon retry state")


def _fetch_rth_bars(api_key: str, ticker: str, frm: str, to: str, max_pages: int,
                    retry_attempts: int, retry_sleep: float) -> list[tuple]:
    url = AGGS_URL.format(ticker=urllib.parse.quote(ticker), frm=frm, to=to)
    params = {"adjusted": "true", "sort": "asc", "limit": "50000", "apiKey": api_key}
    url = f"{url}?{urllib.parse.urlencode(params)}"
    rows: list[tuple] = []
    for _ in range(max_pages):
        body = _urlopen_json(url, retry_attempts, retry_sleep)
        for r in body.get("results") or []:
            ts_ms = r.get("t")
            if ts_ms is None:
                continue
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)
            local = dt.astimezone(MARKET_TZ)
            minute = local.hour * 60 + local.minute
            if minute < _RTH_OPEN_MIN or minute >= _RTH_CLOSE_MIN:
                continue  # keep RTH only so the session "close" is the 16:00 close
            rows.append((
                ticker, dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "1m",
                r.get("o"), r.get("h"), r.get("l"), r.get("c"), r.get("v"),
            ))
        next_url = body.get("next_url")
        if not next_url:
            break
        sep = "&" if "?" in next_url else "?"
        url = f"{next_url}{sep}apiKey={urllib.parse.quote(api_key)}"
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-db",
                        default=str(ROOT / "data" / "pead_research" / "pead_research.db"),
                        help="Self-contained PEAD research DB (same DB the snapshotter writes events to).")
    parser.add_argument("--min-importance", type=int, default=1,
                        help="Skip events below this Benzinga importance (0-5). 0 = keep all.")
    parser.add_argument("--pre-days", type=int, default=3)
    parser.add_argument("--post-days", type=int, default=12,
                        help="Calendar days after the event to cover >=5 trading sessions + buffer.")
    parser.add_argument("--max-symbols", type=int, default=400, help="Safety cap per run.")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--request-delay", type=float, default=13.0,
                        help="Seconds between symbol fetches (Polygon plan is ~5 req/min).")
    parser.add_argument("--retry-attempts", type=int, default=4)
    parser.add_argument("--retry-sleep", type=float, default=15.0,
                        help="Sleep on HTTP 429 before retry (matches the bot's polygon service).")
    parser.add_argument("--force-refetch", action="store_true",
                        help="Ignore the coverage short-circuit and refetch every symbol window.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Plan only: report what would be fetched, no API calls.")
    args = parser.parse_args(argv)

    api_key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print(json.dumps({"report_version": REPORT_VERSION, "error": "POLYGON_API_KEY not set"}),
              file=sys.stderr)
        return 2

    research_path = Path(args.research_db)
    if not research_path.exists():
        print(json.dumps({"report_version": REPORT_VERSION,
                          "error": f"research DB not found: {research_path} "
                          "(run pead_benzinga_snapshot.py first to ingest events)"}), file=sys.stderr)
        return 2
    con = sqlite3.connect(str(research_path))
    try:
        has_events = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='external_signal_features'"
        ).fetchone()
        if not has_events:
            print(json.dumps({"report_version": REPORT_VERSION,
                              "error": "external_signal_features missing in research DB "
                              "(run the snapshotter first)"}), file=sys.stderr)
            return 2
        con.execute(BAR_TABLE_SQL)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_bpf_sym_tf_ts "
            "ON bar_pattern_features(symbol, timeframe, bar_timestamp)"
        )
        con.commit()

        events = _events(con, args.min_importance)
        spans = _windows_by_symbol(events, args.pre_days, args.post_days)
        symbols = sorted(spans)[: args.max_symbols]

        summary = {
            "report_version": REPORT_VERSION,
            "runtime_effect": RUNTIME_EFFECT,
            "research_db": str(research_path),
            "events_after_importance_filter": len(events),
            "symbols_in_scope": len(spans),
            "symbols_this_run": len(symbols),
            "min_importance": args.min_importance,
        }

        if args.dry_run:
            summary["dry_run"] = True
            summary["sample_windows"] = {s: spans[s] for s in symbols[:10]}
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0

        fetched_symbols = 0
        skipped_covered = 0
        bars_inserted = 0
        failures: list[dict] = []
        today = datetime.now(UTC).date().isoformat()
        first = True
        for symbol in symbols:
            frm, to = spans[symbol]
            # Incremental: only fetch the tail we don't already have, up to the most
            # recent available trading day. Avoids re-downloading whole windows daily
            # and avoids endlessly refetching recent events whose forward window is
            # still in the future.
            if not args.force_refetch:
                existing_max = _existing_max_date(con, symbol)
                if existing_max:
                    nxt = (datetime.fromisoformat(existing_max).date() + timedelta(days=1)).isoformat()
                    frm = max(frm, nxt)
            eff_to = min(to, today)
            if frm > eff_to:
                skipped_covered += 1
                continue
            if not first and args.request_delay > 0:
                time.sleep(args.request_delay)  # stay under the ~5 req/min plan limit
            first = False
            try:
                rows = _fetch_rth_bars(api_key, symbol, frm, eff_to, args.max_pages,
                                       args.retry_attempts, args.retry_sleep)
            except Exception as exc:  # noqa: BLE001 - per-symbol resilience
                failures.append({"symbol": symbol, "error": str(exc)[:200]})
                continue
            if rows:
                before = con.total_changes
                con.executemany(
                    "INSERT OR IGNORE INTO bar_pattern_features "
                    "(symbol, bar_timestamp, timeframe, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                con.commit()
                bars_inserted += con.total_changes - before
            fetched_symbols += 1

        summary.update({
            "symbols_fetched": fetched_symbols,
            "symbols_skipped_already_covered": skipped_covered,
            "bars_inserted": bars_inserted,
            "fetch_failures": failures[:20],
            "fetch_failure_count": len(failures),
            "total_bar_rows": con.execute(
                "SELECT COUNT(*) FROM bar_pattern_features WHERE timeframe='1m'").fetchone()[0],
        })
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
