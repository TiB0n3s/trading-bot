#!/usr/bin/env python3
"""Fetch and normalize current CFTC financial-futures COT context."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from symbols_config import SYMBOL_CONFIG  # noqa: E402

from market_intelligence.cot_positioning import (  # noqa: E402
    DEFAULT_STATE_PATH,
    normalize_cot_state,
)

CURRENT_URL = "https://www.cftc.gov/dea/newcot/FinFutWk.txt"
DEFAULT_HISTORICAL_ZIP = ROOT / "data/cot/raw/fut_fin_txt_2026.zip"
DEFAULT_RAW_OUTPUT = ROOT / "data/cot/raw/FinFutWk_current.txt"
DEFAULT_JSON_OUTPUT = ROOT / "data/cot/latest_financial_futures.json"
MARKETS = {
    "NASDAQ_100": "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",
    "RUSSELL_2000": "RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE",
    "S_AND_P_500": "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE",
}


def _float(row: dict[str, str], key: str) -> float:
    value = (row.get(key) or "").strip()
    if value in {"", ".", "·"}:
        return 0.0
    return float(value.replace(",", ""))


def _net(row: dict[str, str], long_key: str, short_key: str) -> float:
    return _float(row, long_key) - _float(row, short_key)


def _date_value(row: dict[str, str]) -> str:
    return row["Report_Date_as_YYYY-MM-DD"].strip()


def _read_historical_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with zipfile.ZipFile(path) as archive:
        name = archive.namelist()[0]
        text = archive.read(name).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader.fieldnames or []), list(reader)


def _fetch_current_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 trading-bot-cot-context/1.0",
            "Accept": "text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def _current_rows(fieldnames: list[str], text: str) -> list[dict[str, str]]:
    return [dict(zip(fieldnames, row)) for row in csv.reader(io.StringIO(text)) if row]


def _published_at(as_of_date: str) -> str:
    report_date = datetime.fromisoformat(as_of_date).date()
    published = datetime.combine(
        report_date + timedelta(days=3),
        datetime.min.time(),
        tzinfo=ZoneInfo("America/New_York"),
    ).replace(hour=15, minute=30)
    return published.isoformat()


def build_latest_payload(
    *,
    fieldnames: list[str],
    historical_rows: list[dict[str, str]],
    current_text: str,
    source_url: str,
) -> dict:
    rows = historical_rows + _current_rows(fieldnames, current_text)
    deduped: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        market = (row.get("Market_and_Exchange_Names") or "").strip()
        report_date = (row.get("Report_Date_as_YYYY-MM-DD") or "").strip()
        if market and report_date:
            deduped[(market, report_date)] = row

    markets_out = {}
    all_rows = list(deduped.values())
    for key, market_name in MARKETS.items():
        history = [
            row
            for row in all_rows
            if (row.get("Market_and_Exchange_Names") or "").strip() == market_name
        ]
        if not history:
            raise RuntimeError(f"missing COT market {key}: {market_name}")
        history.sort(key=_date_value)
        latest = history[-1]
        previous = history[-2] if len(history) > 1 else None
        leveraged_net = _net(
            latest,
            "Lev_Money_Positions_Long_All",
            "Lev_Money_Positions_Short_All",
        )
        nonreportable_net = _net(
            latest,
            "NonRept_Positions_Long_All",
            "NonRept_Positions_Short_All",
        )
        previous_leveraged_net = (
            _net(previous, "Lev_Money_Positions_Long_All", "Lev_Money_Positions_Short_All")
            if previous
            else leveraged_net
        )
        previous_nonreportable_net = (
            _net(previous, "NonRept_Positions_Long_All", "NonRept_Positions_Short_All")
            if previous
            else nonreportable_net
        )
        previous_open_interest = (
            _float(previous, "Open_Interest_All")
            if previous
            else _float(latest, "Open_Interest_All")
        )
        history_52 = history[-52:]
        markets_out[key] = {
            "market": key,
            "source_market_name": market_name,
            "as_of_date": _date_value(latest),
            "published_at": _published_at(_date_value(latest)),
            "source": "cftc_cot_financial_futures_current_week",
            "open_interest": _float(latest, "Open_Interest_All"),
            "open_interest_change": _float(latest, "Open_Interest_All") - previous_open_interest,
            "dealer_intermediary_long": _float(latest, "Dealer_Positions_Long_All"),
            "dealer_intermediary_short": _float(latest, "Dealer_Positions_Short_All"),
            "asset_manager_long": _float(latest, "Asset_Mgr_Positions_Long_All"),
            "asset_manager_short": _float(latest, "Asset_Mgr_Positions_Short_All"),
            "leveraged_funds_long": _float(latest, "Lev_Money_Positions_Long_All"),
            "leveraged_funds_short": _float(latest, "Lev_Money_Positions_Short_All"),
            "leveraged_funds_net": leveraged_net,
            "leveraged_funds_net_change": leveraged_net - previous_leveraged_net,
            "nonreportable_long": _float(latest, "NonRept_Positions_Long_All"),
            "nonreportable_short": _float(latest, "NonRept_Positions_Short_All"),
            "nonreportable_net_change": nonreportable_net - previous_nonreportable_net,
            "leveraged_funds_net_history": [
                _net(
                    row,
                    "Lev_Money_Positions_Long_All",
                    "Lev_Money_Positions_Short_All",
                )
                for row in history_52
            ],
            "history_points": len(history),
        }

    return {
        "version": "cot_financial_futures_latest_v1",
        "source": "cftc_cot_financial_futures_current_week",
        "source_url": source_url,
        "generated_at": datetime.now(ZoneInfo("America/Chicago")).isoformat(timespec="seconds"),
        "markets": markets_out,
    }


def _resolve(path_text: str | None, default: Path) -> Path:
    path = Path(path_text) if path_text else default
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-url", default=CURRENT_URL)
    parser.add_argument("--current-file", help="Use an already downloaded CFTC current-week file.")
    parser.add_argument("--historical-zip", default=str(DEFAULT_HISTORICAL_ZIP))
    parser.add_argument("--raw-output", default=str(DEFAULT_RAW_OUTPUT))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--state-output", default=str(DEFAULT_STATE_PATH))
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Only write the mirrored raw text and latest JSON payload.",
    )
    args = parser.parse_args()

    historical_zip = _resolve(args.historical_zip, DEFAULT_HISTORICAL_ZIP)
    raw_output = _resolve(args.raw_output, DEFAULT_RAW_OUTPUT)
    json_output = _resolve(args.json_output, DEFAULT_JSON_OUTPUT)
    state_output = _resolve(args.state_output, ROOT / DEFAULT_STATE_PATH)

    fieldnames, historical_rows = _read_historical_rows(historical_zip)
    if args.current_file:
        current_text = _resolve(args.current_file, Path(args.current_file)).read_text()
    else:
        current_text = _fetch_current_text(args.current_url)

    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(current_text, encoding="utf-8")
    payload = build_latest_payload(
        fieldnames=fieldnames,
        historical_rows=historical_rows,
        current_text=current_text,
        source_url=args.current_url,
    )
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    if not args.no_normalize:
        normalized = normalize_cot_state(payload, SYMBOL_CONFIG)
        state_output.parent.mkdir(parents=True, exist_ok=True)
        state_output.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")

    summary = {
        market: {
            "as_of_date": data.get("as_of_date"),
            "published_at": data.get("published_at"),
        }
        for market, data in (payload.get("markets") or {}).items()
    }
    print(
        "Wrote CFTC COT current-week context "
        f"json={json_output} state={state_output if not args.no_normalize else 'skipped'}"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
