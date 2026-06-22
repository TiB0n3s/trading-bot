"""Operator reports for symbol-universe coverage and affordability (read-only)."""

from __future__ import annotations

import os

import symbols_config

from services.symbol_universe_diagnostics_service import (
    build_affordability_report,
    build_prediction_coverage,
)
from trading_bot.persistence.repositories.experience_model_repo import ExperienceModelRepository
from trading_bot.persistence.repositories.prediction_repo import PredictionRepository


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def run_prediction_coverage_report(target_date: str) -> bool:
    """Flag approved symbols that have context but no prediction for the date."""
    context_symbols = ExperienceModelRepository().prediction_symbols(target_date)
    predicted_symbols = [
        row.get("symbol")
        for row in PredictionRepository().daily_predictions(target_date)
        if row.get("symbol")
    ]
    payload = build_prediction_coverage(
        market_date=target_date,
        approved_symbols=symbols_config.APPROVED_SYMBOLS_LIST,
        context_symbols=context_symbols,
        predicted_symbols=predicted_symbols,
    )

    print()
    print("=" * 72)
    print("  Symbol Prediction Coverage")
    print("=" * 72)
    print(f"market_date              : {payload['market_date']}")
    print(f"runtime_effect           : {payload['runtime_effect']}")
    print(f"approved / context / pred: "
          f"{payload['approved_count']} / {payload['context_count']} / "
          f"{payload['prediction_count']}")
    print(f"status                   : {payload['status']}")
    if payload["whole_universe_prediction_failure"]:
        print("  !! WHOLE-UNIVERSE PREDICTION FAILURE: context exists but 0 predictions")
    if payload["context_no_prediction"]:
        print(f"  context-but-no-prediction ({payload['context_no_prediction_count']}):")
        print(f"    {', '.join(payload['context_no_prediction'])}")
    if payload["approved_no_context"]:
        print(f"  approved-but-no-context ({payload['approved_no_context_count']}):")
        print(f"    {', '.join(payload['approved_no_context'])}")
    if payload["status"] == "ok":
        print("  all approved symbols with context have predictions")
    print()
    return True


def run_symbol_affordability_report() -> bool:
    """Flag approved symbols undeployable at default integer-share sizing."""
    balance = _env_float("OPS_AFFORDABILITY_BALANCE", 100000.0)
    position_size_pct = _env_float("OPS_AFFORDABILITY_POSITION_SIZE_PCT", 0.50)
    payload = build_affordability_report(
        approved_symbols=symbols_config.APPROVED_SYMBOLS_LIST,
        price_ranges=symbols_config.PRICE_RANGES,
        balance=balance,
        position_size_pct=position_size_pct,
    )

    print()
    print("=" * 72)
    print("  Approved-but-Unaffordable Symbols")
    print("=" * 72)
    print(f"runtime_effect           : {payload['runtime_effect']}")
    print(f"balance / size_pct       : ${payload['balance']:,.0f} / {payload['position_size_pct']}%")
    print(f"risk_amount per order    : ${payload['risk_amount']:,.2f}")
    print(f"approved (priced)        : {payload['approved_priced_count']}")
    print(f"unaffordable_count       : {payload['unaffordable_count']}")
    print(f"status                   : {payload['status']}")
    if payload["unaffordable"]:
        print("  undeployable at default size (max_qty rounds to 0):")
        print(f"    {'symbol':<8} {'top_price':>10} {'max_qty':>8}")
        for row in payload["rows"]:
            if not row["affordable"]:
                print(f"    {row['symbol']:<8} {row['top_price']:>10.2f} {row['max_qty']:>8}")
        print("  (override balance/size via OPS_AFFORDABILITY_BALANCE / "
              "OPS_AFFORDABILITY_POSITION_SIZE_PCT)")
    else:
        print("  all approved symbols are deployable at default size")
    print()
    return True
