"""Tests for read-only symbol-universe diagnostics (#22 affordability, #25 coverage)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.services.symbol_universe_diagnostics_service import (
    build_affordability_report,
    build_prediction_coverage,
)


# --- #25: prediction coverage ------------------------------------------------

def test_coverage_flags_context_without_prediction():
    payload = build_prediction_coverage(
        market_date="2026-06-11",
        approved_symbols=["AAPL", "MSFT", "INTC"],
        context_symbols=["AAPL", "MSFT", "INTC"],
        predicted_symbols=["AAPL", "MSFT"],
    )
    assert payload["status"] == "gap"
    assert payload["context_no_prediction"] == ["INTC"]
    assert payload["whole_universe_prediction_failure"] is False


def test_coverage_ok_when_all_context_predicted():
    payload = build_prediction_coverage(
        market_date="2026-06-11",
        approved_symbols=["AAPL", "MSFT"],
        context_symbols=["AAPL", "MSFT"],
        predicted_symbols=["AAPL", "MSFT"],
    )
    assert payload["status"] == "ok"
    assert payload["context_no_prediction"] == []


def test_coverage_flags_whole_universe_failure():
    payload = build_prediction_coverage(
        market_date="2026-06-11",
        approved_symbols=["AAPL", "MSFT"],
        context_symbols=["AAPL", "MSFT"],
        predicted_symbols=[],
    )
    assert payload["whole_universe_prediction_failure"] is True
    assert payload["status"] == "gap"


def test_coverage_reports_approved_without_context():
    payload = build_prediction_coverage(
        market_date="2026-06-11",
        approved_symbols=["AAPL", "MSFT", "NVDA"],
        context_symbols=["AAPL", "MSFT"],
        predicted_symbols=["AAPL", "MSFT"],
    )
    assert payload["approved_no_context"] == ["NVDA"]
    # approved-without-context alone is not a context-no-prediction gap
    assert payload["status"] == "ok"


# --- #22: affordability ------------------------------------------------------

def test_affordability_flags_unaffordable_highprice():
    payload = build_affordability_report(
        approved_symbols=["AAPL", "ASML"],
        price_ranges={"AAPL": (150, 500), "ASML": (900, 2200)},
        balance=100000.0,
        position_size_pct=0.50,  # $500 risk
    )
    # $500 / 500 = 1 (AAPL affordable); $500 / 2200 = 0 (ASML unaffordable)
    assert "ASML" in payload["unaffordable"]
    assert "AAPL" not in payload["unaffordable"]
    assert payload["status"] == "gap"


def test_affordability_all_ok_with_large_balance():
    payload = build_affordability_report(
        approved_symbols=["AAPL", "ASML"],
        price_ranges={"AAPL": (150, 500), "ASML": (900, 2200)},
        balance=10_000_000.0,
        position_size_pct=1.0,
        )
    assert payload["unaffordable"] == []
    assert payload["status"] == "ok"


def test_affordability_rows_sorted_by_price_desc():
    payload = build_affordability_report(
        approved_symbols=["AAPL", "ASML", "KO"],
        price_ranges={"AAPL": (150, 500), "ASML": (900, 2200), "KO": (50, 80)},
        balance=100000.0,
        position_size_pct=1.0,
    )
    prices = [row["top_price"] for row in payload["rows"]]
    assert prices == sorted(prices, reverse=True)


def test_affordability_skips_symbols_without_price_range():
    payload = build_affordability_report(
        approved_symbols=["AAPL", "UNKNOWN"],
        price_ranges={"AAPL": (150, 500)},
        balance=100000.0,
        position_size_pct=1.0,
    )
    assert payload["approved_priced_count"] == 1
