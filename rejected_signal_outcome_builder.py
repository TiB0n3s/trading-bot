#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, time, timedelta
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

from db import DB_PATH, ensure_rejected_signal_outcomes_table, get_connection


logger = logging.getLogger("rejected_signal_outcome_builder")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(levelname)s - %(message)s",
)

LOCAL_TZ = pytz.timezone(os.getenv("TRADING_BOT_LOCAL_TZ", "America/Chicago"))
ET = pytz.timezone("America/New_York")
MARKET_CLOSE_ET = time(16, 0)
MARKET_OPEN_ET = time(9, 30)


def parse_trade_timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = LOCAL_TZ.localize(dt)
    return dt.astimezone(ET)


def pct_change(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return round((float(current) - float(base)) / float(base) * 100.0, 6)


def signal_adjusted_return(raw_return: float | None, action: str) -> float | None:
    if raw_return is None:
        return None
    if str(action or "").lower() == "sell":
        return round(-float(raw_return), 6)
    return round(float(raw_return), 6)


def first_close_at_or_after(rows: list[dict], target_dt: datetime) -> float | None:
    for row in rows:
        row_dt = parse_trade_timestamp(row["timestamp"])
        if row_dt >= target_dt:
            return float(row["close"])
    return None


def last_close_at_or_before(rows: list[dict], target_dt: datetime) -> float | None:
    latest = None
    for row in rows:
        row_dt = parse_trade_timestamp(row["timestamp"])
        if row_dt <= target_dt:
            latest = float(row["close"])
    return latest


def excursion_60m(rows: list[dict], signal_price: float, signal_dt: datetime, action: str) -> tuple[float | None, float | None]:
    cutoff = signal_dt + timedelta(minutes=60)
    highs = []
    lows = []

    for row in rows:
        row_dt = parse_trade_timestamp(row["timestamp"])
        if signal_dt <= row_dt <= cutoff:
            highs.append(float(row["high"]))
            lows.append(float(row["low"]))

    if not highs or not lows or signal_price <= 0:
        return None, None

    max_up = pct_change(max(highs), signal_price)
    max_down = pct_change(min(lows), signal_price)

    if str(action or "").lower() == "sell":
        favorable = signal_adjusted_return(max_down, "sell")
        adverse = signal_adjusted_return(max_up, "sell")
    else:
        favorable = max_up
        adverse = max_down

    if favorable is not None:
        favorable = max(0.0, float(favorable))
    if adverse is not None:
        adverse = min(0.0, float(adverse))

    return favorable, adverse


def market_close_for(signal_dt: datetime) -> datetime:
    return ET.localize(datetime.combine(signal_dt.date(), MARKET_CLOSE_ET))


def market_open_for_date(target_date: str) -> datetime:
    day = datetime.fromisoformat(target_date).date()
    return ET.localize(datetime.combine(day, MARKET_OPEN_ET))


def market_close_for_date(target_date: str) -> datetime:
    day = datetime.fromisoformat(target_date).date()
    return ET.localize(datetime.combine(day, MARKET_CLOSE_ET))


def compute_outcome(row: dict, bars: list[dict]) -> dict:
    signal_dt = parse_trade_timestamp(row["timestamp"])
    action = str(row.get("action") or "").lower()
    signal_price = float(row["signal_price"])

    def return_at(minutes: int) -> float | None:
        target = signal_dt + timedelta(minutes=minutes)
        close = first_close_at_or_after(bars, target)
        return signal_adjusted_return(pct_change(close, signal_price), action)

    close_eod = last_close_at_or_before(bars, market_close_for(signal_dt))
    mfe_60m, mae_60m = excursion_60m(bars, signal_price, signal_dt, action)

    values = {
        "return_5m": return_at(5),
        "return_15m": return_at(15),
        "return_30m": return_at(30),
        "return_60m": return_at(60),
        "return_eod": signal_adjusted_return(pct_change(close_eod, signal_price), action),
        "max_favorable_60m": mfe_60m,
        "max_adverse_60m": mae_60m,
    }

    if not bars:
        values["label_status"] = "no_bars"
        values["partial_reason"] = "no_bars"
    elif all(values[key] is not None for key in ("return_5m", "return_15m", "return_30m", "return_60m")):
        values["label_status"] = "labeled"
        values["partial_reason"] = None
    elif any(values[key] is not None for key in ("return_5m", "return_15m", "return_30m", "return_60m", "return_eod")):
        values["label_status"] = "partial"
        if signal_dt + timedelta(minutes=60) > market_close_for(signal_dt):
            values["partial_reason"] = "near_close_no_60m_window"
        else:
            values["partial_reason"] = "missing_forward_bars"
    else:
        values["label_status"] = "pending"
        values["partial_reason"] = "pending_forward_bars"

    return values


def fetch_forward_bars(symbol: str, timestamp: str) -> list[dict]:
    from broker import api

    signal_dt = parse_trade_timestamp(timestamp)
    end_dt = max(signal_dt + timedelta(minutes=65), market_close_for(signal_dt))

    bars = api.get_bars(
        symbol,
        "1Min",
        start=signal_dt.isoformat(),
        end=end_dt.isoformat(),
        adjustment="raw",
        feed=os.getenv("ALPACA_BARS_FEED", "iex"),
    ).df

    if bars is None or bars.empty:
        return []

    if "symbol" in bars.columns:
        bars = bars[bars["symbol"] == symbol]

    rows = []
    for idx, bar in bars.iterrows():
        rows.append(
            {
                "timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                "close": float(bar["close"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
            }
        )
    return rows


def fetch_day_bars(symbol: str, target_date: str) -> list[dict]:
    from broker import api

    start_dt = market_open_for_date(target_date)
    end_dt = market_close_for_date(target_date) + timedelta(minutes=1)

    bars = api.get_bars(
        symbol,
        "1Min",
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
        adjustment="raw",
        feed=os.getenv("ALPACA_BARS_FEED", "iex"),
    ).df

    if bars is None or bars.empty:
        return []

    if "symbol" in bars.columns:
        bars = bars[bars["symbol"] == symbol]

    rows = []
    for idx, bar in bars.iterrows():
        rows.append(
            {
                "timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                "close": float(bar["close"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
            }
        )
    return rows


def rejected_rows(target_date: str, limit: int | None = None, symbol: str | None = None) -> list:
    clauses = [
        "substr(timestamp, 1, 10) = ?",
        "approved = 0",
        "symbol IS NOT NULL",
        "action IS NOT NULL",
        "signal_price IS NOT NULL",
        "LOWER(action) IN ('buy', 'sell')",
    ]
    params: list = [target_date]

    if symbol:
        clauses.append("UPPER(symbol) = ?")
        params.append(symbol.upper())

    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT ?"
        params.append(int(limit))

    with get_connection(DB_PATH) as con:
        return con.execute(
            f"""
            SELECT id, timestamp, symbol, action, signal_price, rejection_reason
            FROM trades
            WHERE {' AND '.join(clauses)}
            ORDER BY timestamp ASC, id ASC
            {limit_sql}
            """,
            params,
        ).fetchall()


def upsert_outcome(row, outcome: dict, source: str = "rejected_signal_outcome_builder") -> None:
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO rejected_signal_outcomes (
                trade_id, timestamp, symbol, action, signal_price, rejection_reason,
                return_5m, return_15m, return_30m, return_60m, return_eod,
                max_favorable_60m, max_adverse_60m,
                label_status, partial_reason, source, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(trade_id) DO UPDATE SET
                timestamp = excluded.timestamp,
                symbol = excluded.symbol,
                action = excluded.action,
                signal_price = excluded.signal_price,
                rejection_reason = excluded.rejection_reason,
                return_5m = excluded.return_5m,
                return_15m = excluded.return_15m,
                return_30m = excluded.return_30m,
                return_60m = excluded.return_60m,
                return_eod = excluded.return_eod,
                max_favorable_60m = excluded.max_favorable_60m,
                max_adverse_60m = excluded.max_adverse_60m,
                label_status = excluded.label_status,
                partial_reason = excluded.partial_reason,
                source = excluded.source,
                generated_at = excluded.generated_at
            """,
            (
                row["id"],
                row["timestamp"],
                row["symbol"],
                row["action"],
                row["signal_price"],
                row["rejection_reason"],
                outcome.get("return_5m"),
                outcome.get("return_15m"),
                outcome.get("return_30m"),
                outcome.get("return_60m"),
                outcome.get("return_eod"),
                outcome.get("max_favorable_60m"),
                outcome.get("max_adverse_60m"),
                outcome.get("label_status") or "pending",
                outcome.get("partial_reason"),
                source,
            ),
        )


def build(target_date: str, limit: int | None = None, symbol: str | None = None) -> dict:
    ensure_rejected_signal_outcomes_table(DB_PATH)
    rows = rejected_rows(target_date, limit=limit, symbol=symbol)
    bars_by_symbol: dict[str, list[dict]] = {}

    counts = {
        "rows": len(rows),
        "labeled": 0,
        "partial": 0,
        "pending": 0,
        "no_bars": 0,
        "error": 0,
    }

    for row in rows:
        try:
            row_symbol = row["symbol"]
            if row_symbol not in bars_by_symbol:
                bars_by_symbol[row_symbol] = fetch_day_bars(row_symbol, target_date)
            bars = bars_by_symbol[row_symbol]
            outcome = compute_outcome(dict(row), bars)
            upsert_outcome(row, outcome)
            status = outcome.get("label_status") or "pending"
            counts[status] = counts.get(status, 0) + 1
            logger.info(
                "%s trade_id=%s %s status=%s ret15=%s ret60=%s",
                row["symbol"],
                row["id"],
                row["timestamp"],
                status,
                outcome.get("return_15m"),
                outcome.get("return_60m"),
            )
        except Exception as exc:
            counts["error"] += 1
            error_outcome = {
                "label_status": "error",
                "partial_reason": "exception",
                "return_5m": None,
                "return_15m": None,
                "return_30m": None,
                "return_60m": None,
                "return_eod": None,
                "max_favorable_60m": None,
                "max_adverse_60m": None,
            }
            upsert_outcome(row, error_outcome)
            logger.error("%s trade_id=%s failed: %s", row["symbol"], row["id"], exc)

    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Trade date YYYY-MM-DD")
    parser.add_argument("--symbol", help="Optional symbol filter")
    parser.add_argument("--limit", type=int, help="Optional row limit")
    args = parser.parse_args()

    counts = build(args.date, limit=args.limit, symbol=args.symbol)
    print("Rejected signal outcome build")
    for key in ("rows", "labeled", "partial", "pending", "no_bars", "error"):
        print(f"{key:>8}: {counts.get(key, 0)}")

    return 0 if counts.get("error", 0) == 0 else 1


if __name__ == "__main__":
    reexec_under_venv_if_available()
    raise SystemExit(main())
