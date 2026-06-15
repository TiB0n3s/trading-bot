#!/usr/bin/env python3
"""Tests for automated pre-market context source collectors."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cot_positioning_fetch import build_latest_payload  # noqa: E402
from webull_context_collect import (  # noqa: E402
    build_market_evidence_payload,
    build_morning_brief_payload,
)

FIELDS = [
    "Market_and_Exchange_Names",
    "As_of_Date_In_Form_YYMMDD",
    "Report_Date_as_YYYY-MM-DD",
    "CFTC_Contract_Market_Code",
    "CFTC_Market_Code",
    "CFTC_Region_Code",
    "CFTC_Commodity_Code",
    "Open_Interest_All",
    "Dealer_Positions_Long_All",
    "Dealer_Positions_Short_All",
    "Dealer_Positions_Spread_All",
    "Asset_Mgr_Positions_Long_All",
    "Asset_Mgr_Positions_Short_All",
    "Asset_Mgr_Positions_Spread_All",
    "Lev_Money_Positions_Long_All",
    "Lev_Money_Positions_Short_All",
    "Lev_Money_Positions_Spread_All",
    "Other_Rept_Positions_Long_All",
    "Other_Rept_Positions_Short_All",
    "Other_Rept_Positions_Spread_All",
    "Tot_Rept_Positions_Long_All",
    "Tot_Rept_Positions_Short_All",
    "NonRept_Positions_Long_All",
    "NonRept_Positions_Short_All",
]


def _row(market: str, date: str, lev_long: int, lev_short: int, oi: int = 1000) -> dict:
    return {
        "Market_and_Exchange_Names": market,
        "Report_Date_as_YYYY-MM-DD": date,
        "Open_Interest_All": str(oi),
        "Dealer_Positions_Long_All": "100",
        "Dealer_Positions_Short_All": "80",
        "Asset_Mgr_Positions_Long_All": "200",
        "Asset_Mgr_Positions_Short_All": "75",
        "Lev_Money_Positions_Long_All": str(lev_long),
        "Lev_Money_Positions_Short_All": str(lev_short),
        "NonRept_Positions_Long_All": "25",
        "NonRept_Positions_Short_All": "20",
    }


def test_cot_fetch_builds_latest_payload_from_current_week_rows():
    historical = []
    current_rows = []
    for market in {
        "NASDAQ_100": "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",
        "RUSSELL_2000": "RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE",
        "S_AND_P_500": "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE",
    }.values():
        historical.append(_row(market, "2026-06-02", 20, 50, oi=900))
        current_rows.append(_row(market, "2026-06-09", 40, 30, oi=1000))

    current_text = "\n".join(
        ",".join(f'"{row.get(field, "")}"' for field in FIELDS) for row in current_rows
    )
    payload = build_latest_payload(
        fieldnames=FIELDS,
        historical_rows=historical,
        current_text=current_text,
        source_url="https://example.test/FinFutWk.txt",
    )

    assert payload["markets"]["NASDAQ_100"]["as_of_date"] == "2026-06-09"
    assert payload["markets"]["NASDAQ_100"]["published_at"] == "2026-06-12T15:30:00-04:00"
    assert payload["markets"]["NASDAQ_100"]["leveraged_funds_net"] == 10.0
    assert payload["markets"]["NASDAQ_100"]["leveraged_funds_net_change"] == 40.0


def test_webull_collector_builds_morning_and_market_payloads_from_screeners():
    raw = {
        "published_at": "2026-06-15T13:00:00+00:00",
        "screeners": {
            "top_active": [
                {"symbol": "SOFI", "volume": "1000", "price": "16.8", "change_ratio": "0.01"}
            ],
            "gainers": [{"symbol": "AMD", "volume": "500", "price": "170", "change_ratio": "0.05"}],
            "losers": [
                {"symbol": "RDW", "volume": "800", "price": "15.5", "change_ratio": "-0.08"}
            ],
        },
    }

    morning = build_morning_brief_payload(raw, brief_date="2026-06-15")
    market = build_market_evidence_payload(raw)

    assert morning["source"] == "webull_openapi_screener_proxy"
    assert morning["symbols"]["AMD"]["event_bias"] == "supportive"
    assert morning["symbols"]["RDW"]["event_bias"] == "caution"
    assert market["screeners"]["top_active"][0]["symbol"] == "SOFI"
    assert market["attention"]["symbols"]["SOFI"]["rank"] == 1


if __name__ == "__main__":
    test_cot_fetch_builds_latest_payload_from_current_week_rows()
    test_webull_collector_builds_morning_and_market_payloads_from_screeners()
    print("pre-market context collector tests passed")
