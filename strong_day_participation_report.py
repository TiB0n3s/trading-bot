#!/usr/bin/env python3
"""
Strong-Day Participation Report

Identifies symbols with persistent session strength and reports whether the
bot participated — and if not, what blocked it.

This fills a gap in missed_opportunity_report.py, which only evaluates
rejected signals already in the trades table. A symbol that never sent a
TradingView alert is invisible to that report. This one starts from the full
approved-symbol universe and asks:

  Did the bot participate in symbols that had a genuinely strong day?
  If not: was the blocker missing alerts, affordability, macro cap,
          setup policy, or something else?

For no_signals symbols, this also acts as a TradingView coverage report:
first_strong_time and minutes_strong_without_alert show how long the session
was strong before (and without) any alert being received.

Read-only by default. With --write-db it persists analytics rows to
strong_day_participation for prediction/intelligence validation. It does not
place, cancel, or modify orders.

Usage:
  python3 strong_day_participation_report.py
  python3 strong_day_participation_report.py --date 2026-05-26
  python3 strong_day_participation_report.py --date 2026-05-26 --write-db
  python3 strong_day_participation_report.py --date 2026-05-26 --min-session-pct 1.5
  python3 strong_day_participation_report.py --date 2026-05-26 --symbol AMD
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytz

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


reexec_under_venv_if_available()
load_env_file()

from services.market_data_service import market_data_service
from db import DB_PATH, get_connection
from symbols_config import APPROVED_SYMBOLS_LIST, SYMBOL_SIGNAL_SOURCE

ET = pytz.timezone("America/New_York")

MIN_SESSION_BARS = 10

# Hard gates are functionally different from intelligence gates — keep them visibly separate.
# Lower priority number = higher importance in the hierarchy.
BLOCKER_PRIORITY = {
    "market_hours": 1,
    "exposure_cap": 2,
    "affordability": 2,
    "macro_position_limit": 3,
    "macro_risk": 3,
    "correlation_cap": 4,
    "second_look": 5,
    "trend_confirmation": 6,
    "chase_prevention": 6,
    "setup_policy": 6,
    "live_bias_downgrade": 7,
    "market_bias_avoid": 7,
    "prediction_gate": 8,
    "soft_avoid_prediction_gate": 8,
    "confidence_gate": 9,
}

AFFORDABILITY_CATEGORIES = {"exposure_cap", "affordability", "macro_position_limit"}
MACRO_CAP_CATEGORIES = {"macro_position_limit", "macro_risk"}
ROTATION_CATEGORIES = {"correlation_cap"}


def init_strong_day_participation_table():
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS strong_day_participation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_source TEXT,
                min_session_pct REAL NOT NULL,
                session_return_pct REAL,
                mfe_pct REAL,
                return_30m_pct REAL,
                return_60m_pct REAL,
                first_strong_time TEXT,
                session_high_time TEXT,
                primary_status TEXT,
                primary_blocker TEXT,
                buy_signal_count INTEGER,
                approved_buy_count INTEGER,
                rejected_buy_count INTEGER,
                sell_signal_count INTEGER,
                auto_buy_candidate_count INTEGER,
                auto_buy_strong_count INTEGER,
                auto_buy_watch_count INTEGER,
                auto_buy_submitted_count INTEGER,
                auto_buy_max_score REAL,
                auto_buy_first_candidate_time TEXT,
                auto_buy_first_strong_time TEXT,
                prediction_score REAL,
                prediction_decision TEXT,
                prediction_confidence TEXT,
                prediction_sample_size INTEGER,
                prediction_timing_score REAL,
                prediction_trend_score REAL,
                prediction_trend_label TEXT,
                raw_json TEXT,
                generated_at TEXT NOT NULL,
                UNIQUE(market_date, symbol, min_session_pct)
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_strong_day_participation_date_symbol
            ON strong_day_participation(market_date, symbol)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_strong_day_participation_status
            ON strong_day_participation(market_date, primary_status)
            """
        )


# ── bar helpers ──────────────────────────────────────────────────────────────

def session_window_utc(date_str):
    d = datetime.fromisoformat(date_str)
    open_et = ET.localize(datetime(d.year, d.month, d.day, 9, 30, 0))
    close_et = ET.localize(datetime(d.year, d.month, d.day, 16, 10, 0))
    return open_et.astimezone(timezone.utc), close_et.astimezone(timezone.utc)


def fetch_session_bars(symbol, date_str):
    start_utc, end_utc = session_window_utc(date_str)
    bars = market_data_service.get_bars_with_fallback(
        symbol,
        "1Min",
        start=start_utc.isoformat(),
        end=end_utc.isoformat(),
        feed="iex",
    )
    out = []
    for b in bars:
        bt = b.t
        if bt.tzinfo is None:
            bt = bt.replace(tzinfo=timezone.utc)
        else:
            bt = bt.astimezone(timezone.utc)
        out.append({
            "timestamp": bt,
            "open": float(b.o),
            "high": float(b.h),
            "low": float(b.l),
            "close": float(b.c),
            "volume": float(getattr(b, "v", 0) or 0),
        })
    return out


def _pct_change(start, end):
    if not start or not end or start <= 0:
        return None
    return (end - start) / start * 100.0


def _bar_et_hhmm(bar):
    return bar["timestamp"].astimezone(ET).strftime("%H:%M")


def compute_session_metrics(bars, threshold_pct):
    if not bars:
        return None

    closes = [b["close"] for b in bars]
    session_open = bars[0]["open"]
    session_return = _pct_change(session_open, closes[-1])

    ret_30m = _pct_change(session_open, closes[min(29, len(closes) - 1)]) if len(closes) >= 5 else None
    ret_60m = _pct_change(session_open, closes[min(59, len(closes) - 1)]) if len(closes) >= 5 else None

    max_close = max(closes)
    min_close = min(closes)
    mfe = _pct_change(session_open, max_close)

    session_high_time = _bar_et_hhmm(bars[closes.index(max_close)])
    session_low_time = _bar_et_hhmm(bars[closes.index(min_close)])

    first_strong_time = None
    first_strong_return_pct = None
    minutes_strong = None
    for i, bar in enumerate(bars):
        ret = _pct_change(session_open, bar["close"])
        if ret is not None and ret >= threshold_pct:
            first_strong_time = _bar_et_hhmm(bar)
            first_strong_return_pct = round(ret, 3)
            minutes_strong = len(bars) - i
            break

    return {
        "bar_count": len(bars),
        "session_open": session_open,
        "session_close": closes[-1],
        "session_return_pct": round(session_return, 3) if session_return is not None else None,
        "return_30m_pct": round(ret_30m, 3) if ret_30m is not None else None,
        "return_60m_pct": round(ret_60m, 3) if ret_60m is not None else None,
        "mfe_pct": round(mfe, 3) if mfe is not None else None,
        "session_high_time": session_high_time,
        "session_low_time": session_low_time,
        "first_strong_time": first_strong_time,
        "first_strong_return_pct": first_strong_return_pct,
        "minutes_strong": minutes_strong,
    }


# ── DB helpers ───────────────────────────────────────────────────────────────

def load_symbol_trades(target_date, symbol):
    with get_connection(DB_PATH) as con:
        return con.execute(
            """
            SELECT id, timestamp, action, approved, rejection_reason,
                   signal_price, setup_label, setup_policy_action,
                   session_trend_label, session_trend_score,
                   buy_opportunity_score, buy_opportunity_recommendation,
                   momentum_pct, prediction_score, prediction_decision
            FROM trades
            WHERE timestamp LIKE ?
              AND symbol = ?
            ORDER BY id ASC
            """,
            (f"{target_date}%", symbol.upper()),
        ).fetchall()


def load_max_setup_score(target_date, symbol):
    with get_connection(DB_PATH) as con:
        try:
            row = con.execute(
                """
                SELECT MAX(setup_score) AS v
                FROM feature_snapshots
                WHERE substr(timestamp, 1, 10) = ?
                  AND symbol = ?
                """,
                (target_date, symbol.upper()),
            ).fetchone()
            return float(row["v"]) if row and row["v"] is not None else None
        except Exception:
            return None


def load_auto_buy_candidates(target_date, symbol):
    with get_connection(DB_PATH) as con:
        try:
            return con.execute(
                """
                SELECT timestamp, decision, score, reason, hard_block_reason,
                       order_submitted, order_id
                FROM auto_buy_candidates
                WHERE substr(timestamp, 1, 10) = ?
                  AND symbol = ?
                ORDER BY timestamp ASC, id ASC
                """,
                (target_date, symbol.upper()),
            ).fetchall()
        except Exception:
            return []


def load_prediction(target_date, symbol):
    with get_connection(DB_PATH) as con:
        try:
            row = con.execute(
                """
                SELECT prediction_score, confidence, sample_size,
                       timing_score, trend_score, trend_label
                FROM daily_symbol_predictions
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (target_date, symbol.upper()),
            ).fetchone()
            if not row:
                return {}
            prediction = dict(row)
            prediction["prediction_decision"] = None
            return prediction
        except Exception:
            return {}


def upsert_strong_day_results(results, target_date, min_session_pct):
    init_strong_day_participation_table()
    generated_at = datetime.now(ET).isoformat()
    rows_written = 0
    with get_connection(DB_PATH) as con:
        for r in results:
            if r.get("error"):
                continue
            con.execute(
                """
                INSERT INTO strong_day_participation (
                    market_date, symbol, signal_source, min_session_pct,
                    session_return_pct, mfe_pct, return_30m_pct, return_60m_pct,
                    first_strong_time, session_high_time,
                    primary_status, primary_blocker,
                    buy_signal_count, approved_buy_count, rejected_buy_count,
                    sell_signal_count,
                    auto_buy_candidate_count, auto_buy_strong_count,
                    auto_buy_watch_count, auto_buy_submitted_count,
                    auto_buy_max_score, auto_buy_first_candidate_time,
                    auto_buy_first_strong_time,
                    prediction_score, prediction_decision, prediction_confidence,
                    prediction_sample_size, prediction_timing_score,
                    prediction_trend_score, prediction_trend_label,
                    raw_json, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market_date, symbol, min_session_pct) DO UPDATE SET
                    signal_source = excluded.signal_source,
                    session_return_pct = excluded.session_return_pct,
                    mfe_pct = excluded.mfe_pct,
                    return_30m_pct = excluded.return_30m_pct,
                    return_60m_pct = excluded.return_60m_pct,
                    first_strong_time = excluded.first_strong_time,
                    session_high_time = excluded.session_high_time,
                    primary_status = excluded.primary_status,
                    primary_blocker = excluded.primary_blocker,
                    buy_signal_count = excluded.buy_signal_count,
                    approved_buy_count = excluded.approved_buy_count,
                    rejected_buy_count = excluded.rejected_buy_count,
                    sell_signal_count = excluded.sell_signal_count,
                    auto_buy_candidate_count = excluded.auto_buy_candidate_count,
                    auto_buy_strong_count = excluded.auto_buy_strong_count,
                    auto_buy_watch_count = excluded.auto_buy_watch_count,
                    auto_buy_submitted_count = excluded.auto_buy_submitted_count,
                    auto_buy_max_score = excluded.auto_buy_max_score,
                    auto_buy_first_candidate_time = excluded.auto_buy_first_candidate_time,
                    auto_buy_first_strong_time = excluded.auto_buy_first_strong_time,
                    prediction_score = excluded.prediction_score,
                    prediction_decision = excluded.prediction_decision,
                    prediction_confidence = excluded.prediction_confidence,
                    prediction_sample_size = excluded.prediction_sample_size,
                    prediction_timing_score = excluded.prediction_timing_score,
                    prediction_trend_score = excluded.prediction_trend_score,
                    prediction_trend_label = excluded.prediction_trend_label,
                    raw_json = excluded.raw_json,
                    generated_at = excluded.generated_at
                """,
                (
                    target_date,
                    r.get("symbol"),
                    r.get("signal_source"),
                    min_session_pct,
                    r.get("session_return_pct"),
                    r.get("mfe_pct"),
                    r.get("return_30m_pct"),
                    r.get("return_60m_pct"),
                    r.get("first_strong_time"),
                    r.get("session_high_time"),
                    r.get("primary_status"),
                    r.get("primary_blocker"),
                    r.get("buy_signal_count"),
                    r.get("approved_buy_count"),
                    r.get("rejected_buy_count"),
                    r.get("sell_signal_count"),
                    r.get("auto_buy_candidate_count"),
                    r.get("auto_buy_strong_count"),
                    r.get("auto_buy_watch_count"),
                    r.get("auto_buy_submitted_count"),
                    r.get("auto_buy_max_score"),
                    r.get("auto_buy_first_candidate_time"),
                    r.get("auto_buy_first_strong_time"),
                    r.get("prediction_score"),
                    r.get("prediction_decision"),
                    r.get("prediction_confidence"),
                    r.get("prediction_sample_size"),
                    r.get("prediction_timing_score"),
                    r.get("prediction_trend_score"),
                    r.get("prediction_trend_label"),
                    json.dumps(r, sort_keys=True, default=str),
                    generated_at,
                ),
            )
            rows_written += 1
    return rows_written


# ── classification helpers ───────────────────────────────────────────────────

def _reason_category(reason):
    if not reason:
        return "unknown"
    if ":" in reason:
        return reason.split(":", 1)[0].strip()
    return reason.strip()


def _count_blockers(rejected_rows):
    counts = Counter()
    for r in rejected_rows:
        cat = _reason_category(r["rejection_reason"])
        counts[cat] += 1
    return sorted(counts.items(), key=lambda x: -x[1])


def _primary_blocker(blockers):
    if not blockers:
        return None
    def priority(item):
        cat, count = item
        return (BLOCKER_PRIORITY.get(cat, 99), -count)
    return sorted(blockers, key=priority)[0][0]


def classify_participation(rows):
    """
    Returns (status, blockers).

    status:
      no_signals           — zero rows in trades for this symbol/date
      no_buy_signals       — signals exist but none are buys (mixed non-buy actions)
      sell_only_signals    — signals exist and all are sells (no buy alerts fired)
      all_rejected         — buy signals received, all rejected
      partial_participation — buy signals received, some approved, some rejected
      full_participation   — buy signals received, all (or some) approved, none rejected
    blockers:
      list of (category, count) from rejection reasons, desc by count
    """
    if not rows:
        return "no_signals", []

    buy_rows = [r for r in rows if r["action"] and r["action"].lower() == "buy"]

    if not buy_rows:
        sell_rows = [r for r in rows if r["action"] and r["action"].lower() == "sell"]
        if sell_rows and len(sell_rows) == len(rows):
            return "sell_only_signals", [("sell_signals", len(sell_rows))]
        return "no_buy_signals", [("non_buy_signals", len(rows))]

    approved = [r for r in buy_rows if r["approved"] == 1]
    rejected = [r for r in buy_rows if r["approved"] == 0]
    blockers = _count_blockers(rejected)

    if approved and not rejected:
        return "full_participation", []
    if approved and rejected:
        return "partial_participation", blockers
    return "all_rejected", blockers


# ── signal timing helpers ────────────────────────────────────────────────────

def _signal_hhmm(row):
    ts = row["timestamp"]
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = ET.localize(dt)
        return dt.astimezone(ET).strftime("%H:%M")
    except Exception:
        return str(ts)[:16]


def _hhmm_to_dt(hhmm, date_str):
    d = datetime.fromisoformat(date_str)
    h, m = map(int, hhmm.split(":"))
    return ET.localize(datetime(d.year, d.month, d.day, h, m))


def _alert_gap_minutes(first_strong_time, first_signal_time, date_str):
    if not first_strong_time or not first_signal_time:
        return None
    try:
        t_strong = _hhmm_to_dt(first_strong_time, date_str)
        t_alert = _hhmm_to_dt(first_signal_time, date_str)
        gap = (t_alert - t_strong).total_seconds() / 60.0
        return round(gap, 1) if gap >= 0 else None
    except Exception:
        return None


def _best_rejected_signal(rejected_buys):
    if not rejected_buys:
        return None, None
    best = max(rejected_buys, key=lambda r: float(r["buy_opportunity_score"] or 0))
    return _signal_hhmm(best), _reason_category(best["rejection_reason"])


def _auto_buy_hhmm(row):
    ts = row["timestamp"]
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = ET.localize(dt)
        return dt.astimezone(ET).strftime("%H:%M")
    except Exception:
        return str(ts)[:16]


# ── analysis ─────────────────────────────────────────────────────────────────

def analyze_symbol(symbol, target_date, threshold_pct):
    try:
        bars = fetch_session_bars(symbol, target_date)
    except Exception as e:
        return {"symbol": symbol, "error": f"bar fetch failed: {e}"}

    if len(bars) < MIN_SESSION_BARS:
        return {
            "symbol": symbol,
            "error": (
                f"insufficient bars (got {len(bars)}, need {MIN_SESSION_BARS}); "
                "market may be closed"
            ),
        }

    metrics = compute_session_metrics(bars, threshold_pct)
    if metrics is None:
        return {"symbol": symbol, "error": "no session bars returned"}

    all_rows = load_symbol_trades(target_date, symbol)
    status, blockers = classify_participation(all_rows)
    auto_rows = load_auto_buy_candidates(target_date, symbol)
    prediction = load_prediction(target_date, symbol)

    buy_rows = [r for r in all_rows if r["action"] and r["action"].lower() == "buy"]
    sell_rows = [r for r in all_rows if r["action"] and r["action"].lower() == "sell"]
    approved_buys = [r for r in buy_rows if r["approved"] == 1]
    rejected_buys = [r for r in buy_rows if r["approved"] == 0]

    blocker_counts = dict(blockers)
    primary_blocker = _primary_blocker(blockers)
    auto_strong = [r for r in auto_rows if r["decision"] == "strong_buy_candidate"]
    auto_watch = [r for r in auto_rows if r["decision"] == "watch"]
    auto_submitted = [r for r in auto_rows if int(r["order_submitted"] or 0) == 1]
    auto_blocked = [r for r in auto_rows if r["hard_block_reason"]]

    if not buy_rows and auto_submitted:
        status = "auto_buy_participation"
        primary_blocker = None
    elif not buy_rows and (auto_strong or auto_watch):
        status = "auto_buy_candidate_only"
        primary_blocker = "auto_buy_not_submitted"
    elif not buy_rows and auto_blocked and status == "no_signals":
        primary_blocker = "auto_buy_hard_block"

    affordability_gap = sum(n for c, n in blockers if c in AFFORDABILITY_CATEGORIES) or None
    macro_cap_blocked_count = sum(n for c, n in blockers if c in MACRO_CAP_CATEGORIES) or None
    rotation_blocked_count = sum(n for c, n in blockers if c in ROTATION_CATEGORIES) or None

    first_buy_signal_time = _signal_hhmm(buy_rows[0]) if buy_rows else None
    first_approved_buy_time = _signal_hhmm(approved_buys[0]) if approved_buys else None
    best_signal_time, best_signal_rejection_reason = _best_rejected_signal(rejected_buys)

    tradingview_alert_gap = _alert_gap_minutes(
        metrics.get("first_strong_time"),
        first_buy_signal_time,
        target_date,
    )

    minutes_strong_without_alert = (
        metrics.get("minutes_strong")
        if status == "no_signals"
        else None
    )

    max_buy_opportunity_score = max(
        (float(r["buy_opportunity_score"]) for r in buy_rows if r["buy_opportunity_score"] is not None),
        default=None,
    )
    max_session_momentum_score = max(
        (float(r["session_trend_score"]) for r in all_rows if r["session_trend_score"] is not None),
        default=None,
    )
    max_setup_score = load_max_setup_score(target_date, symbol)

    return {
        "symbol": symbol,
        "signal_source": SYMBOL_SIGNAL_SOURCE.get(symbol, "unknown"),
        "error": None,
        **metrics,
        "buy_signal_count": len(buy_rows),
        "sell_signal_count": len(sell_rows),
        "approved_buy_count": len(approved_buys),
        "rejected_buy_count": len(rejected_buys),
        "primary_status": status,
        "primary_blocker": primary_blocker,
        "blocker_counts": blocker_counts,
        "first_buy_signal_time": first_buy_signal_time,
        "first_approved_buy_time": first_approved_buy_time,
        "best_signal_time": best_signal_time,
        "best_signal_rejection_reason": best_signal_rejection_reason,
        "affordability_gap": affordability_gap,
        "macro_cap_blocked_count": macro_cap_blocked_count,
        "rotation_blocked_count": rotation_blocked_count,
        "tradingview_alert_gap": tradingview_alert_gap,
        "minutes_strong_without_alert": minutes_strong_without_alert,
        "max_buy_opportunity_score": max_buy_opportunity_score,
        "max_session_momentum_score": max_session_momentum_score,
        "max_setup_score": max_setup_score,
        "auto_buy_candidate_count": len(auto_rows),
        "auto_buy_strong_count": len(auto_strong),
        "auto_buy_watch_count": len(auto_watch),
        "auto_buy_submitted_count": len(auto_submitted),
        "auto_buy_first_candidate_time": _auto_buy_hhmm(auto_rows[0]) if auto_rows else None,
        "auto_buy_first_strong_time": _auto_buy_hhmm(auto_strong[0]) if auto_strong else None,
        "auto_buy_max_score": max((float(r["score"]) for r in auto_rows if r["score"] is not None), default=None),
        "auto_buy_hard_block_count": len(auto_blocked),
        "prediction_score": prediction.get("prediction_score"),
        "prediction_decision": prediction.get("prediction_decision"),
        "prediction_confidence": prediction.get("confidence"),
        "prediction_sample_size": prediction.get("sample_size"),
        "prediction_timing_score": prediction.get("timing_score"),
        "prediction_trend_score": prediction.get("trend_score"),
        "prediction_trend_label": prediction.get("trend_label"),
    }


# ── formatting ───────────────────────────────────────────────────────────────

def _fp(v, decimals=2):
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{decimals}f}%"


def _fv(v, decimals=1):
    if v is None:
        return "n/a"
    return f"{v:.{decimals}f}"


def _fmt_blockers(blocker_counts):
    if not blocker_counts:
        return "—"
    return ", ".join(f"{cat} x{n}" for cat, n in sorted(blocker_counts.items(), key=lambda x: -x[1])[:4])


def _fmt_gap(minutes):
    if minutes is None:
        return "n/a"
    return f"+{minutes:.0f} min"


# ── report output ─────────────────────────────────────────────────────────────

MISSED_STATUSES = {
    "no_signals",
    "no_buy_signals",
    "sell_only_signals",
    "all_rejected",
    "auto_buy_candidate_only",
}


_TV_LATE_ALERT_THRESHOLD_MINS = 30

_CAPACITY_BLOCKERS = {"exposure_cap", "affordability", "macro_position_limit", "macro_risk", "correlation_cap"}


def _render_affordability_section(strong):
    # Symbols where ANY signals hit capacity-type gates
    capacity_hits = [
        r for r in strong
        if (r.get("affordability_gap") or 0) > 0
        or (r.get("macro_cap_blocked_count") or 0) > 0
        or (r.get("rotation_blocked_count") or 0) > 0
        or r.get("primary_blocker") in _CAPACITY_BLOCKERS
    ]
    if not capacity_hits:
        return

    print()
    print("── Affordability & Capacity Blockers ────────────────────────────────────")
    print(
        f"  Symbols with strong days where sizing/capacity gates fired: {len(capacity_hits)}"
    )
    print()
    print(
        f"  {'Symbol':<6}  {'Session%':>9}  {'Status':<22}  "
        f"{'Afford':>6}  {'Macro':>5}  {'Rot':>3}  PrimaryBlocker"
    )
    print(
        f"  {'──────':<6}  {'─────────':>9}  {'──────────────────────':<22}  "
        f"{'──────':>6}  {'─────':>5}  {'───':>3}  ──────────────────"
    )
    for r in sorted(capacity_hits, key=lambda x: -(x.get("session_return_pct") or 0)):
        print(
            f"  {r['symbol']:<6}  "
            f"{_fp(r.get('session_return_pct')):>9}  "
            f"{r.get('primary_status', '?'):<22}  "
            f"{(r.get('affordability_gap') or 0):>6}  "
            f"{(r.get('macro_cap_blocked_count') or 0):>5}  "
            f"{(r.get('rotation_blocked_count') or 0):>3}  "
            f"{r.get('primary_blocker') or '—'}"
        )

    # Highlight symbols primarily blocked by pre-Claude affordability gate
    primary_afford = [
        r for r in capacity_hits
        if r.get("primary_blocker") in {"affordability", "exposure_cap"}
    ]
    if primary_afford:
        print()
        print(
            "  Note: symbols with primary_blocker=affordability were rejected before Claude."
        )
        print(
            "  The pre-Claude affordability gate now checks whether buying_power can buy at least 1 share at the signal price."
        )
        print(
            "  High-priced symbols (e.g. ASML, AMD, COST) may fail at reduced macro multipliers."
        )
        print(
            "  To investigate: python3 blocked_signal_outcome_report.py --category affordability"
        )


def _render_tv_coverage_section(strong):
    tv_strong = [r for r in strong if r.get("signal_source") == "tradingview_alert"]
    if not tv_strong:
        return

    uncovered = [r for r in tv_strong if r.get("primary_status") == "no_signals"]
    late = [
        r for r in tv_strong
        if r.get("primary_status") != "no_signals"
        and r.get("tradingview_alert_gap") is not None
        and r["tradingview_alert_gap"] >= _TV_LATE_ALERT_THRESHOLD_MINS
    ]
    timely = [
        r for r in tv_strong
        if r not in uncovered and r not in late
    ]

    print()
    print("── TradingView Alert Coverage ───────────────────────────────────────────")
    print(
        f"  TV-alert symbols with strong day : {len(tv_strong)}"
    )
    print(
        f"    Timely coverage (alert <{_TV_LATE_ALERT_THRESHOLD_MINS} min after threshold) : {len(timely)}"
    )
    print(
        f"    Late coverage   (alert >={_TV_LATE_ALERT_THRESHOLD_MINS} min after threshold): {len(late)}"
    )
    print(
        f"    No coverage     (no alert received at all)               : {len(uncovered)}"
    )

    if uncovered:
        print()
        print(
            f"  {'Symbol':<6}  {'Session%':>9}  {'MFE%':>7}  {'FirstStrong':>11}  "
            f"{'MinsStrongNoAlert':>17}  Status"
        )
        print(
            f"  {'──────':<6}  {'─────────':>9}  {'───────':>7}  {'───────────':>11}  "
            f"{'─────────────────':>17}  ──────────────────────"
        )
        for r in sorted(uncovered, key=lambda x: -(x.get("session_return_pct") or 0)):
            mins = r.get("minutes_strong_without_alert")
            mins_str = f"{mins} min" if mins is not None else "n/a"
            print(
                f"  {r['symbol']:<6}  "
                f"{_fp(r.get('session_return_pct')):>9}  "
                f"{_fp(r.get('mfe_pct')):>7}  "
                f"{r.get('first_strong_time') or '—':>11}  "
                f"{mins_str:>17}  "
                f"{r.get('primary_status', '?')}"
            )

    if late:
        print()
        print("  Late alerts (alert arrived after threshold but with significant delay):")
        print(
            f"  {'Symbol':<6}  {'Session%':>9}  {'FirstStrong':>11}  "
            f"{'AlertGap':>8}  {'FirstAlert':>10}  Status"
        )
        print(
            f"  {'──────':<6}  {'─────────':>9}  {'───────────':>11}  "
            f"{'────────':>8}  {'──────────':>10}  ──────────────────────"
        )
        for r in sorted(late, key=lambda x: -(x.get("tradingview_alert_gap") or 0)):
            gap = r.get("tradingview_alert_gap")
            gap_str = f"+{gap} min" if gap is not None else "n/a"
            print(
                f"  {r['symbol']:<6}  "
                f"{_fp(r.get('session_return_pct')):>9}  "
                f"{r.get('first_strong_time') or '—':>11}  "
                f"{gap_str:>8}  "
                f"{r.get('first_buy_signal_time') or '—':>10}  "
                f"{r.get('primary_status', '?')}"
            )


def print_report(results, target_date, min_session_pct):
    valid = [r for r in results if not r.get("error")]
    errors = [r for r in results if r.get("error")]

    strong = [
        r for r in valid
        if r.get("session_return_pct") is not None
        and r["session_return_pct"] >= min_session_pct
    ]

    def by_return(lst):
        return sorted(lst, key=lambda x: -(x.get("session_return_pct") or 0))

    def count_status(s):
        return sum(1 for r in strong if r.get("primary_status") == s)

    print()
    print("=" * 72)
    print(f"  Strong-Day Participation Report — {target_date}")
    print("=" * 72)
    print()
    print(f"  Min session return threshold : {min_session_pct:.1f}%")
    print(f"  Symbols evaluated            : {len(valid)}")
    print(f"  Strong-session symbols       : {len(strong)}")
    print(f"    Full participation         : {count_status('full_participation')}")
    print(f"    Partial participation      : {count_status('partial_participation')}")
    print(f"    Missed — all_rejected      : {count_status('all_rejected')}")
    print(f"    Missed — sell_only_signals : {count_status('sell_only_signals')}")
    print(f"    Missed — no_buy_signals    : {count_status('no_buy_signals')}")
    print(f"    Missed — no_signals        : {count_status('no_signals')}")
    print(f"    Auto-buy participation     : {count_status('auto_buy_participation')}")
    print(f"    Auto-buy candidate only    : {count_status('auto_buy_candidate_only')}")
    if errors:
        print(f"  Bar fetch errors             : {len(errors)}")

    if not strong:
        print()
        print("  No symbols met the strong-day threshold for this date.")
        print("  (Possible causes: market holiday, weekend, threshold too high, bar data unavailable)")
        if errors:
            _print_errors(errors)
        return

    _render_tv_coverage_section(strong)
    _render_affordability_section(strong)

    # ── compact summary table ────────────────────────────────────────────────
    print()
    print("── All Strong-Session Symbols (ranked) ─────────────────────────────────")
    print(
        f"  {'Symbol':<6}  {'Session%':>9}  {'MFE%':>7}  {'FirstStrong':>11}  "
        f"{'Status':<22}  {'Pred':>6}  {'Auto':>5}  PrimaryBlocker"
    )
    print(
        f"  {'──────':<6}  {'─────────':>9}  {'───────':>7}  {'───────────':>11}  "
        f"{'──────────────────────':<22}  {'──────':>6}  {'─────':>5}  ──────────────────"
    )
    for r in by_return(strong):
        blocker_label = r.get("primary_blocker") or "—"
        first_strong = r.get("first_strong_time") or "—"
        print(
            f"  {r['symbol']:<6}  "
            f"{_fp(r.get('session_return_pct')):>9}  "
            f"{_fp(r.get('mfe_pct')):>7}  "
            f"{first_strong:>11}  "
            f"{r.get('primary_status', '?'):<22}  "
            f"{_fv(r.get('prediction_score')):>6}  "
            f"{r['auto_buy_candidate_count']:>5}  "
            f"{blocker_label}"
        )

    # ── detail blocks for missed symbols ─────────────────────────────────────
    missed = [r for r in by_return(strong) if r.get("primary_status") in MISSED_STATUSES]
    if missed:
        print()
        print("── Missed Participation Detail ──────────────────────────────────────────")
        for r in missed:
            _print_detail_block(r, min_session_pct)

    # ── participated ─────────────────────────────────────────────────────────
    participated = [r for r in strong if r.get("primary_status") not in MISSED_STATUSES]
    if participated:
        print()
        print("── Participated ─────────────────────────────────────────────────────────")
        print(
            f"  {'Symbol':<6}  {'Session%':>9}  {'30m%':>7}  {'60m%':>7}  "
            f"{'Approved':>8}  {'Buys':>4}  {'FirstEntry':>10}"
        )
        print(
            f"  {'──────':<6}  {'─────────':>9}  {'───────':>7}  {'───────':>7}  "
            f"{'────────':>8}  {'────':>4}  {'──────────':>10}"
        )
        for r in by_return(participated):
            print(
                f"  {r['symbol']:<6}  "
                f"{_fp(r.get('session_return_pct')):>9}  "
                f"{_fp(r.get('return_30m_pct')):>7}  "
                f"{_fp(r.get('return_60m_pct')):>7}  "
                f"{r['approved_buy_count']:>8}  "
                f"{r['buy_signal_count']:>4}  "
                f"{(r.get('first_approved_buy_time') or '—'):>10}"
            )

    if errors:
        _print_errors(errors)


def _print_detail_block(r, min_session_pct):
    sym = r["symbol"]
    status = r.get("primary_status", "?")
    session_pct = _fp(r.get("session_return_pct"))
    mfe_pct = _fp(r.get("mfe_pct"))

    print()
    print(f"  {sym}  —  {status}  —  session {session_pct}  (MFE {mfe_pct})")
    print(f"    {'return_30m':.<34} {_fp(r.get('return_30m_pct'))}")
    print(f"    {'return_60m':.<34} {_fp(r.get('return_60m_pct'))}")
    print(f"    {'session_high_time':.<34} {r.get('session_high_time') or '—'}")
    print(f"    {'session_low_time':.<34} {r.get('session_low_time') or '—'}")

    first_strong = r.get("first_strong_time")
    first_strong_ret = r.get("first_strong_return_pct")
    if first_strong:
        print(f"    {'first_strong_time':.<34} {first_strong}  ({_fp(first_strong_ret)} at threshold cross)")
    else:
        print(f"    {'first_strong_time':.<34} never crossed {min_session_pct:.1f}% threshold intraday (end-of-day only)")

    mins_strong = r.get("minutes_strong_without_alert")
    if mins_strong is not None:
        print(f"    {'minutes_strong_without_alert':.<34} {mins_strong} min  (no buy alert received)")

    tv_gap = r.get("tradingview_alert_gap")
    first_buy = r.get("first_buy_signal_time")
    if first_buy:
        print(f"    {'first_buy_signal_time':.<34} {first_buy}")
        print(f"    {'tradingview_alert_gap':.<34} {_fmt_gap(tv_gap)}")
    else:
        print(f"    {'tradingview_alert_gap':.<34} n/a  (no buy alert received)")

    first_approved = r.get("first_approved_buy_time")
    print(f"    {'first_approved_buy_time':.<34} {first_approved or '—'}")

    print(f"    {'buy_signal_count':.<34} {r['buy_signal_count']}")
    print(f"    {'sell_signal_count':.<34} {r['sell_signal_count']}")
    print(f"    {'approved_buy_count':.<34} {r['approved_buy_count']}")
    print(f"    {'rejected_buy_count':.<34} {r['rejected_buy_count']}")
    print(f"    {'signal_source':.<34} {r.get('signal_source') or '—'}")
    print(f"    {'auto_buy_candidate_count':.<34} {r.get('auto_buy_candidate_count', 0)}")
    print(f"    {'auto_buy_strong_count':.<34} {r.get('auto_buy_strong_count', 0)}")
    print(f"    {'auto_buy_watch_count':.<34} {r.get('auto_buy_watch_count', 0)}")
    print(f"    {'auto_buy_submitted_count':.<34} {r.get('auto_buy_submitted_count', 0)}")
    print(f"    {'auto_buy_first_candidate_time':.<34} {r.get('auto_buy_first_candidate_time') or '—'}")
    print(f"    {'auto_buy_first_strong_time':.<34} {r.get('auto_buy_first_strong_time') or '—'}")
    print(f"    {'auto_buy_max_score':.<34} {_fv(r.get('auto_buy_max_score'))}")
    print(f"    {'auto_buy_hard_block_count':.<34} {r.get('auto_buy_hard_block_count', 0)}")

    pb = r.get("primary_blocker")
    print(f"    {'primary_blocker':.<34} {pb or '—'}")
    print(f"    {'blocker_counts':.<34} {_fmt_blockers(r.get('blocker_counts', {}))}")

    best_t = r.get("best_signal_time")
    best_reason = r.get("best_signal_rejection_reason")
    if best_t:
        print(f"    {'best_signal_time':.<34} {best_t}  (reason: {best_reason or '—'})")
    else:
        print(f"    {'best_signal_time':.<34} —")

    print(f"    {'max_buy_opportunity_score':.<34} {_fv(r.get('max_buy_opportunity_score'))}")
    print(f"    {'max_session_momentum_score':.<34} {_fv(r.get('max_session_momentum_score'))}")
    print(f"    {'max_setup_score':.<34} {_fv(r.get('max_setup_score'))}")
    print(f"    {'prediction_score':.<34} {_fv(r.get('prediction_score'))}")
    print(f"    {'prediction_decision':.<34} {r.get('prediction_decision') or '—'}")
    print(f"    {'prediction_confidence':.<34} {r.get('prediction_confidence') or '—'}")
    print(f"    {'prediction_sample_size':.<34} {r.get('prediction_sample_size') if r.get('prediction_sample_size') is not None else '—'}")
    print(f"    {'prediction_timing_score':.<34} {_fv(r.get('prediction_timing_score'))}")
    print(f"    {'prediction_trend_score':.<34} {_fv(r.get('prediction_trend_score'))}")
    print(f"    {'prediction_trend_label':.<34} {r.get('prediction_trend_label') or '—'}")

    aff = r.get("affordability_gap")
    macro = r.get("macro_cap_blocked_count")
    rot = r.get("rotation_blocked_count")
    if aff:
        print(f"    {'affordability_gap':.<34} {aff} signal(s) blocked")
    if macro:
        print(f"    {'macro_cap_blocked_count':.<34} {macro} signal(s) blocked")
    if rot:
        print(f"    {'rotation_blocked_count':.<34} {rot} signal(s) blocked")


def _print_errors(errors):
    print()
    print("── Bar Fetch Errors ─────────────────────────────────────────────────────")
    for r in errors[:10]:
        print(f"  {r['symbol']}: {r['error']}")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--date",
        default=datetime.now(ET).date().isoformat(),
        help="Session date (default: today)",
    )
    parser.add_argument(
        "--min-session-pct",
        type=float,
        default=1.0,
        help="Session return threshold to qualify as a strong day (default: 1.0)",
    )
    parser.add_argument("--symbol", help="Evaluate only this symbol")
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Persist per-symbol participation rows for prediction/intelligence reports.",
    )
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else sorted(APPROVED_SYMBOLS_LIST)

    print(f"Evaluating {len(symbols)} symbol(s) for {args.date} ...")
    results = [analyze_symbol(sym, args.date, args.min_session_pct) for sym in symbols]

    print_report(results, args.date, args.min_session_pct)
    if args.write_db:
        rows_written = upsert_strong_day_results(results, args.date, args.min_session_pct)
        print()
        print(f"[OK] wrote strong_day_participation rows: {rows_written}")


if __name__ == "__main__":
    main()
