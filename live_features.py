#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")


def reexec_under_venv_if_available() -> None:
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


reexec_under_venv_if_available()


def load_env_file(path: Path = ENV_FILE) -> bool:
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


load_env_file()

import pytz

from strategy_constants import SYMBOL_MARKET_ALIGNMENT
from db import get_connection, DB_PATH
from feature_engine import compute_feature_snapshot
from macro_risk import get_macro_risk
from market_time import is_trading_day, market_session, now_et
from prior_session_context import prior_session_context
from rolling_context import rolling_symbol_context
from services.market_data_service import market_data_service
from symbols_config import APPROVED_SYMBOLS
from setup_engine import classify_feature_snapshot as classify_setup

logger = logging.getLogger("live_features")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

MARKET_CONTEXT_FILE = BASE_DIR / "market_context.json"
ET = pytz.timezone("America/New_York")
_BAR_CACHE: dict[tuple[str, str], tuple[list[float], list[float]]] = {}
# Tracks which feed was used for each (symbol, session) cache key.
_BAR_FEED_USED: dict[tuple[str, str], str] = {}


def add_feature_audit_fields(snapshot: dict) -> dict:
    """Attach leakage/audit metadata for dataset exports."""
    generated_at = datetime.now(ET).isoformat()
    feature_time = snapshot.get("timestamp") or generated_at
    snapshot["feature_generated_at"] = generated_at
    snapshot["feature_available_at"] = generated_at
    snapshot["feature_age_seconds"] = 0.0
    snapshot["source"] = "live_features"
    snapshot["is_stale"] = 0
    snapshot["staleness_reason"] = None
    if not snapshot.get("timestamp"):
        snapshot["timestamp"] = feature_time
        snapshot["is_stale"] = 1
        snapshot["staleness_reason"] = "missing_snapshot_timestamp"
    return snapshot

def load_market_context() -> dict:
    if not MARKET_CONTEXT_FILE.exists():
        return {}
    try:
        return json.loads(MARKET_CONTEXT_FILE.read_text())
    except Exception as e:
        logger.warning(f"Could not parse market_context.json: {e}")
        return {}


def benchmark_for(symbol: str) -> str:
    mapping = SYMBOL_MARKET_ALIGNMENT.get(symbol) or {}
    return mapping.get("benchmark", "SPY")


def recent_actions(symbol: str, limit: int = 10) -> list[str]:
    with get_connection(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT action
            FROM trades
            WHERE symbol = ?
              AND action IS NOT NULL
              AND (
                    approved = 1
                 OR rejection_reason LIKE 'confidence_gate:%'
                 OR rejection_reason LIKE 'trend_gate:%'
                 OR rejection_reason LIKE 'trend_confirmation:%'
              )
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol, limit),
        ).fetchall()

    return [r["action"] for r in rows]


def compute_trend(recent_actions_list: list[str]) -> dict:
    if not recent_actions_list:
        return {
            "direction": "neutral",
            "strength": "weak",
            "consecutive_count": 0,
            "last_signal": None,
        }

    first = recent_actions_list[0]
    count = 0
    for action in recent_actions_list:
        if action == first:
            count += 1
        else:
            break

    direction = ("bullish" if first == "buy" else "bearish") if count >= 3 else "neutral"
    strength = "confirmed" if count >= 5 else "developing" if count >= 3 else "weak"

    return {
        "direction": direction,
        "strength": strength,
        "consecutive_count": count,
        "last_signal": first,
    }


def trend_for(symbol: str) -> dict:
    return compute_trend(recent_actions(symbol))


def get_bar_series(
    symbol: str,
    session: str,
    min_bars_needed: int = 16,
    target_bars: int = 30,
) -> tuple[list[float], list[float], str, int]:
    cache_key = (symbol, session)
    if cache_key in _BAR_CACHE:
        return _BAR_CACHE[cache_key]

    end = datetime.now(ET)

    timeframe = "1Min" if session == "open" else "5Min"
    lookbacks = (90, 180, 360) if timeframe == "1Min" else (300, 600, 1200)

    for window_minutes in lookbacks:
        start = end - timedelta(minutes=window_minutes)
        barset = market_data_service.get_barset_with_fallback(
            symbol,
            timeframe,
            start=start.isoformat(),
            end=end.isoformat(),
            adjustment="raw",
            feed="sip",
        )
        feed_used = market_data_service.get_feed_used(symbol) or "sip"
        bars = barset.df

        if bars is None or bars.empty:
            continue

        if "symbol" in bars.columns:
            bars = bars[bars["symbol"] == symbol]

        closes = [float(x) for x in bars["close"].tolist()]
        volumes = [float(x) for x in bars["volume"].tolist()]

        if len(closes) >= min_bars_needed:
            result = (closes[-target_bars:], volumes[-target_bars:], timeframe, len(closes))
            _BAR_CACHE[cache_key] = result
            _BAR_FEED_USED[cache_key] = feed_used
            logger.info(
                f"{symbol}: using {timeframe} bars ({feed_used}), "
                f"got {len(closes)} bars from {window_minutes}m lookback"
            )
            return result

        logger.info(
            f"{symbol}: only {len(closes)} {timeframe} bars from {window_minutes}m lookback; retrying wider window"
        )

    raise RuntimeError(
        f"Not enough {timeframe} bars for {symbol} even after widened lookback"
    )


def build_snapshot(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    if symbol not in APPROVED_SYMBOLS:
        raise ValueError(f"{symbol} is not in APPROVED_SYMBOLS")

    session = market_session()
    benchmark_symbol = benchmark_for(symbol)

    closes, volumes, timeframe, bar_count = get_bar_series(symbol, session=session)
    benchmark_closes, _, _, _ = get_bar_series(benchmark_symbol, session=session)

    ctx = load_market_context()
    symbol_ctx = (ctx.get("symbols") or {}).get(symbol) or {}
    macro = get_macro_risk(BASE_DIR)
    trend = trend_for(symbol)

    snapshot = compute_feature_snapshot(
        symbol=symbol,
        benchmark_symbol=benchmark_symbol,
        closes=closes,
        volumes=volumes,
        benchmark_closes=benchmark_closes,
        market_session=session,
        macro_regime=macro.get("macro_regime"),
        market_bias=symbol_ctx.get("bias"),
        trend_direction=trend.get("direction"),
        trend_strength=trend.get("strength"),
    )

    snapshot["timestamp"] = datetime.now(ET).isoformat()
    snapshot["bar_timeframe"] = timeframe
    snapshot["bar_count"] = bar_count
    snapshot["bar_feed_used"] = _BAR_FEED_USED.get((symbol, session), "sip")

    if len(closes) >= 5:
        returns = []
        for prev, cur in zip(closes[-5:-1], closes[-4:]):
            if prev > 0:
                returns.append((cur - prev) / prev * 100)
        if len(returns) >= 4:
            snapshot["momentum_acceleration_pct"] = round(
                returns[-1] - (sum(returns[:-1]) / len(returns[:-1])),
                4,
            )

    if len(volumes) >= 11:
        current_volume = float(volumes[-1] or 0)
        prior_volumes = [float(v or 0) for v in volumes[-11:-1]]
        usable = [v for v in prior_volumes if v > 0]
        if usable:
            avg_volume = sum(usable) / len(usable)
            if avg_volume > 0:
                snapshot["volume_surge_ratio"] = round(current_volume / avg_volume, 3)

    try:
        rolling = rolling_symbol_context(symbol) or {}
        snapshot["extension_from_recent_base_pct"] = rolling.get("extension_from_recent_base_pct")
    except Exception:
        snapshot["extension_from_recent_base_pct"] = None

    try:
        prior = prior_session_context(symbol) or {}
        snapshot["prior_session_return_pct"] = prior.get("session_return_pct")
    except Exception:
        snapshot["prior_session_return_pct"] = None
    
    setup = classify_setup(snapshot)
    snapshot["setup_label"] = setup.setup_label
    snapshot["setup_recommendation"] = setup.recommendation
    snapshot["setup_score"] = setup.setup_score
    snapshot["setup_confidence"] = setup.confidence
    snapshot["setup_key"] = setup.setup_key
    snapshot["setup_rationale"] = setup.rationale

    return add_feature_audit_fields(snapshot)

def insert_snapshot(snapshot: dict) -> None:
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO feature_snapshots (
                timestamp,
                symbol,
                last_price,
                ret_1m,
                ret_5m,
                ret_15m,
                range_pos_15m,
                distance_from_5m_high,
                distance_from_5m_low,
                distance_from_vwap,
                volume_ratio_5m,
                benchmark_symbol,
                benchmark_ret_5m,
                relative_strength_5m,
                spread_pct,
                market_session,
                macro_regime,
                market_bias,
                trend_direction,
                trend_strength,
                feature_available_at,
                feature_generated_at,
                feature_age_seconds,
                source,
                is_stale,
                staleness_reason,
                bar_timeframe,
                bar_count,
                setup_label,
                setup_recommendation,
                setup_score,
                setup_confidence,
                setup_key,
                momentum_acceleration_pct,
                volume_surge_ratio,
                extension_from_recent_base_pct,
                prior_session_return_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.get("timestamp"),
                snapshot.get("symbol"),
                snapshot.get("last_price"),
                snapshot.get("ret_1m"),
                snapshot.get("ret_5m"),
                snapshot.get("ret_15m"),
                snapshot.get("range_pos_15m"),
                snapshot.get("distance_from_5m_high"),
                snapshot.get("distance_from_5m_low"),
                snapshot.get("distance_from_vwap"),
                snapshot.get("volume_ratio_5m"),
                snapshot.get("benchmark_symbol"),
                snapshot.get("benchmark_ret_5m"),
                snapshot.get("relative_strength_5m"),
                snapshot.get("spread_pct"),
                snapshot.get("market_session"),
                snapshot.get("macro_regime"),
                snapshot.get("market_bias"),
                snapshot.get("trend_direction"),
                snapshot.get("trend_strength"),
                snapshot.get("feature_available_at"),
                snapshot.get("feature_generated_at"),
                snapshot.get("feature_age_seconds"),
                snapshot.get("source"),
                snapshot.get("is_stale"),
                snapshot.get("staleness_reason"),
                snapshot.get("bar_timeframe"),
                snapshot.get("bar_count"),
                snapshot.get("setup_label"),
                snapshot.get("setup_recommendation"),
                snapshot.get("setup_score"),
                snapshot.get("setup_confidence"),
                snapshot.get("setup_key"),
                snapshot.get("momentum_acceleration_pct"),
                snapshot.get("volume_surge_ratio"),
                snapshot.get("extension_from_recent_base_pct"),
                snapshot.get("prior_session_return_pct"),
            ),
        )

def collect_all_symbols(write: bool = False, stdout: bool = False) -> tuple[int, int]:
    global _BAR_CACHE
    _BAR_CACHE = {}

    success = 0
    failed = 0

    for symbol in sorted(APPROVED_SYMBOLS):
        try:
            snapshot = build_snapshot(symbol)

            if stdout:
                print(json.dumps(snapshot, sort_keys=True))

            if write:
                insert_snapshot(snapshot)

            success += 1
            logger.info(f"{symbol}: snapshot collected")
        except Exception as e:
            failed += 1
            logger.error(f"{symbol}: snapshot failed: {e}")

    logger.info(f"feature snapshot collection complete: success={success} failed={failed}")
    return success, failed

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Approved symbol, e.g. QQQ")
    parser.add_argument("--all-symbols", action="store_true", help="Collect snapshots for all approved symbols")
    parser.add_argument("--stdout", action="store_true", help="Print JSON snapshot(s)")
    parser.add_argument("--write", action="store_true", help="Insert snapshot(s) into feature_snapshots")
    args = parser.parse_args()

    if not args.symbol and not args.all_symbols:
        parser.error("Must provide either --symbol or --all-symbols")

    if args.symbol and args.all_symbols:
        parser.error("Use either --symbol or --all-symbols, not both")

    if not is_trading_day(now_et().date()):
        logger.info("Skipping live feature collection: today is not a trading day")
        return 0

    if args.all_symbols:
        success, failed = collect_all_symbols(write=args.write, stdout=args.stdout)
        return 0 if success > 0 and failed == 0 else 1

    try:
        snapshot = build_snapshot(args.symbol)
    except Exception as e:
        logger.error(f"Failed to build snapshot for {args.symbol}: {e}")
        return 1

    if args.stdout or not args.write:
        print(json.dumps(snapshot, indent=2, sort_keys=True))

    if args.write:
        insert_snapshot(snapshot)
        logger.info(
            f"Inserted feature snapshot for {snapshot['symbol']} at {snapshot['timestamp']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
