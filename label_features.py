#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import sqlite3
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

from broker import api
from db import DB_PATH, get_connection

logger = logging.getLogger("label_features")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

ET = pytz.timezone("America/New_York")


def parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        return ET.localize(dt)
    return dt.astimezone(ET)


def safe_pct_change(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return round(((current - base) / base) * 100.0, 6)


def fetch_forward_bars(symbol: str, ts: str) -> list[dict]:
    snapshot_dt = parse_ts(ts)
    end_dt = snapshot_dt + timedelta(minutes=35)

    bars = api.get_bars(
        symbol,
        "1Min",
        start=snapshot_dt.isoformat(),
        end=end_dt.isoformat(),
        adjustment="raw",
        feed="iex",
    ).df

    if bars is None or bars.empty:
        return []

    if "symbol" in bars.columns:
        bars = bars[bars["symbol"] == symbol]

    rows = []
    for idx, row in bars.iterrows():
        rows.append({
            "timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
            "close": float(row["close"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
        })
    return rows


def first_price_at_or_after(rows: list[dict], minutes_forward: int, snapshot_dt: datetime) -> float | None:
    target = snapshot_dt + timedelta(minutes=minutes_forward)
    for row in rows:
        row_dt = parse_ts(row["timestamp"])
        if row_dt >= target:
            return float(row["close"])
    return None


def excursion_15m(rows: list[dict], snapshot_price: float, snapshot_dt: datetime) -> tuple[float | None, float | None]:
    cutoff = snapshot_dt + timedelta(minutes=15)
    highs = []
    lows = []

    for row in rows:
        row_dt = parse_ts(row["timestamp"])
        if row_dt <= cutoff:
            highs.append(float(row["high"]))
            lows.append(float(row["low"]))

    if not highs or not lows or snapshot_price == 0:
        return None, None

    max_up = round(((max(highs) - snapshot_price) / snapshot_price) * 100.0, 6)

    raw_down = ((min(lows) - snapshot_price) / snapshot_price) * 100.0
    max_down = round(min(raw_down, 0.0), 6)

    return max_up, max_down


def outcome_label(ret_fwd_15m: float | None) -> str | None:
    if ret_fwd_15m is None:
        return None
    if ret_fwd_15m >= 0.5:
        return "up_strong"
    if ret_fwd_15m >= 0.1:
        return "up"
    if ret_fwd_15m <= -0.5:
        return "down_strong"
    if ret_fwd_15m <= -0.1:
        return "down"
    return "flat"


def unlabeled_snapshots(limit: int = 100) -> list[sqlite3.Row]:
    cutoff = datetime.now(ET) - timedelta(minutes=35)

    with get_connection(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT fs.id, fs.symbol, fs.timestamp, fs.last_price
            FROM feature_snapshots fs
            LEFT JOIN labeled_setups ls
              ON ls.snapshot_id = fs.id
            WHERE ls.snapshot_id IS NULL
              AND fs.last_price IS NOT NULL
              AND fs.timestamp <= ?
            ORDER BY fs.timestamp ASC
            LIMIT ?
            """,
            (cutoff.isoformat(), limit),
        ).fetchall()
    return rows


def insert_label(row: sqlite3.Row, fwd5: float | None, fwd15: float | None, fwd30: float | None,
                 ret5: float | None, ret15: float | None, ret30: float | None,
                 max_up_15m: float | None, max_down_15m: float | None, label: str | None) -> None:
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO labeled_setups (
                snapshot_id,
                symbol,
                timestamp,
                price_at_snapshot,
                future_price_5m,
                future_price_15m,
                future_price_30m,
                ret_fwd_5m,
                ret_fwd_15m,
                ret_fwd_30m,
                max_up_15m,
                max_down_15m,
                outcome_label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["symbol"],
                row["timestamp"],
                row["last_price"],
                fwd5,
                fwd15,
                fwd30,
                ret5,
                ret15,
                ret30,
                max_up_15m,
                max_down_15m,
                label,
            ),
        )


def main() -> int:
    rows = unlabeled_snapshots(limit=200)
    if not rows:
        logger.info("No unlabeled snapshots found")
        return 0

    labeled = 0
    skipped = 0

    for row in rows:
        try:
            snapshot_dt = parse_ts(row["timestamp"])
            snapshot_price = float(row["last_price"])
            bars = fetch_forward_bars(row["symbol"], row["timestamp"])

            if not bars:
                skipped += 1
                logger.info(f"{row['symbol']} snapshot_id={row['id']}: no forward bars yet")
                continue

            fwd5 = first_price_at_or_after(bars, 5, snapshot_dt)
            fwd15 = first_price_at_or_after(bars, 15, snapshot_dt)
            fwd30 = first_price_at_or_after(bars, 30, snapshot_dt)

            ret5 = safe_pct_change(fwd5, snapshot_price)
            ret15 = safe_pct_change(fwd15, snapshot_price)
            ret30 = safe_pct_change(fwd30, snapshot_price)

            max_up_15m, max_down_15m = excursion_15m(bars, snapshot_price, snapshot_dt)
            label = outcome_label(ret15)

            insert_label(row, fwd5, fwd15, fwd30, ret5, ret15, ret30, max_up_15m, max_down_15m, label)
            labeled += 1
            logger.info(
                f"{row['symbol']} snapshot_id={row['id']}: labeled ret15={ret15} label={label}"
            )
        except Exception as e:
            skipped += 1
            logger.error(f"{row['symbol']} snapshot_id={row['id']}: failed: {e}")

    logger.info(f"Labeling complete: labeled={labeled}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
