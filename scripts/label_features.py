#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


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
from repositories.label_features_repo import LabelFeaturesRepository
from services.label_features_market_data_service import label_features_market_data_service

_repo = LabelFeaturesRepository()
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
    return label_features_market_data_service.fetch_forward_bars(
        symbol=symbol,
        snapshot_dt=snapshot_dt,
    )


def first_price_at_or_after(
    rows: list[dict], minutes_forward: int, snapshot_dt: datetime
) -> float | None:
    target = snapshot_dt + timedelta(minutes=minutes_forward)
    for row in rows:
        row_dt = parse_ts(row["timestamp"])
        if row_dt >= target:
            return float(row["close"])
    return None


def excursion(
    rows: list[dict], snapshot_price: float, snapshot_dt: datetime, minutes_forward: int
) -> tuple[float | None, float | None]:
    cutoff = snapshot_dt + timedelta(minutes=minutes_forward)
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


def action_direction(row) -> str:
    raw = " ".join(
        str(row[key] or "").lower()
        for key in ("setup_recommendation", "setup_label")
        if key in row.keys()
    )
    if any(token in raw for token in ("short", "sell", "exit", "reduce")):
        return "short"
    return "long"


def action_excursion_60m(
    *,
    direction: str,
    max_up_60m: float | None,
    max_down_60m: float | None,
) -> tuple[float | None, float | None]:
    if max_up_60m is None or max_down_60m is None:
        return None, None
    if direction == "short":
        return round(abs(min(max_down_60m, 0.0)), 6), round(-abs(max_up_60m), 6)
    return max_up_60m, max_down_60m


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


def unlabeled_snapshots(
    limit: int = 100,
    *,
    newest_first: bool = True,
    target_date: str | None = None,
) -> list:
    cutoff = datetime.now(ET) - timedelta(minutes=65)
    return _repo.unlabeled_snapshots(
        cutoff,
        limit,
        newest_first=newest_first,
        target_date=target_date,
    )


def insert_label(
    row,
    fwd5: float | None,
    fwd15: float | None,
    fwd30: float | None,
    fwd60: float | None,
    ret5: float | None,
    ret15: float | None,
    ret30: float | None,
    ret60: float | None,
    max_up_15m: float | None,
    max_down_15m: float | None,
    max_up_60m: float | None,
    max_down_60m: float | None,
    direction: str | None,
    action_mfe_60m_pct: float | None,
    action_mae_60m_pct: float | None,
    label: str | None,
) -> None:
    _repo.insert_label(
        row,
        fwd5=fwd5,
        fwd15=fwd15,
        fwd30=fwd30,
        fwd60=fwd60,
        ret5=ret5,
        ret15=ret15,
        ret30=ret30,
        ret60=ret60,
        max_up_15m=max_up_15m,
        max_down_15m=max_down_15m,
        max_up_60m=max_up_60m,
        max_down_60m=max_down_60m,
        action_direction=direction,
        action_mfe_60m_pct=action_mfe_60m_pct,
        action_mae_60m_pct=action_mae_60m_pct,
        label=label,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Label matured feature snapshots.")
    parser.add_argument("--limit", type=int, default=int(os.getenv("LABEL_FEATURES_LIMIT", "200")))
    parser.add_argument(
        "--date",
        default=os.getenv("LABEL_FEATURES_TARGET_DATE"),
        help="Optional feature snapshot date to label, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--oldest-first",
        action="store_true",
        default=os.getenv("LABEL_FEATURES_OLDEST_FIRST", "").lower() in ("1", "true", "yes"),
        help="Process historical backlog oldest-first. Default is newest matured snapshots first.",
    )
    args = parser.parse_args()

    rows = unlabeled_snapshots(
        limit=args.limit,
        newest_first=not args.oldest_first,
        target_date=args.date,
    )
    if not rows:
        logger.info("No unlabeled snapshots found")
        return 0

    logger.info(
        "Labeling %s matured snapshots newest_first=%s target_date=%s",
        len(rows),
        not args.oldest_first,
        args.date or "any",
    )

    labeled = 0
    skipped = 0
    errors = 0

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
            fwd60 = first_price_at_or_after(bars, 60, snapshot_dt)

            ret5 = safe_pct_change(fwd5, snapshot_price)
            ret15 = safe_pct_change(fwd15, snapshot_price)
            ret30 = safe_pct_change(fwd30, snapshot_price)
            ret60 = safe_pct_change(fwd60, snapshot_price)

            max_up_15m, max_down_15m = excursion(bars, snapshot_price, snapshot_dt, 15)
            max_up_60m, max_down_60m = excursion(bars, snapshot_price, snapshot_dt, 60)
            direction = action_direction(row)
            action_mfe, action_mae = action_excursion_60m(
                direction=direction,
                max_up_60m=max_up_60m,
                max_down_60m=max_down_60m,
            )
            label = outcome_label(ret15)

            insert_label(
                row,
                fwd5,
                fwd15,
                fwd30,
                fwd60,
                ret5,
                ret15,
                ret30,
                ret60,
                max_up_15m,
                max_down_15m,
                max_up_60m,
                max_down_60m,
                direction,
                action_mfe,
                action_mae,
                label,
            )
            labeled += 1
            logger.info(
                f"{row['symbol']} snapshot_id={row['id']}: labeled ret15={ret15} label={label}"
            )
        except Exception as e:
            skipped += 1
            errors += 1
            logger.error(f"{row['symbol']} snapshot_id={row['id']}: failed: {e}")

    logger.info(f"Labeling complete: labeled={labeled}, skipped={skipped}, errors={errors}")
    print(f"rows_written: {labeled}")
    print(f"label_features_summary: labeled={labeled} skipped={skipped} errors={errors}")
    return 1 if errors and labeled == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
