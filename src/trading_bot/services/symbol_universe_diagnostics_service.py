"""Read-only symbol-universe diagnostics.

Pure payload builders (no DB / no IO) for two operator diagnostics:
  * prediction coverage (#25): approved symbols that have intelligence context
    but no ML prediction for a trading date, or a whole-universe prediction
    failure.
  * affordability (#22): approved symbols whose integer-only sizing rounds to
    qty < 1 at the default per-order size, making them undeployable.

These are diagnostic-only. They have no trade, sizing, or order authority.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

RUNTIME_EFFECT = "diagnostic_only_no_trade_authority"


def build_prediction_coverage(
    *,
    market_date: str,
    approved_symbols: Iterable[str],
    context_symbols: Iterable[str],
    predicted_symbols: Iterable[str],
) -> dict[str, Any]:
    """Coverage of approved symbols against same-day intelligence and predictions.

    ``context_no_prediction`` are approved symbols that have a context row but no
    prediction row — they fall through to deterministic-only handling with no
    calibrated probability/EV input (a Level-0/1 thesis blind spot). A
    ``whole_universe_prediction_failure`` flags the case where context exists for
    the date but zero predictions were produced.
    """
    approved = {str(s).upper() for s in approved_symbols if str(s)}
    context = {str(s).upper() for s in context_symbols if str(s)}
    predicted = {str(s).upper() for s in predicted_symbols if str(s)}

    context_no_prediction = sorted((context & approved) - predicted)
    approved_no_context = sorted(approved - context)
    whole_universe_failure = bool(context) and not predicted
    has_gap = bool(context_no_prediction) or whole_universe_failure

    return {
        "version": "symbol_prediction_coverage_v1",
        "runtime_effect": RUNTIME_EFFECT,
        "market_date": market_date,
        "approved_count": len(approved),
        "context_count": len(context),
        "prediction_count": len(predicted),
        "context_no_prediction": context_no_prediction,
        "context_no_prediction_count": len(context_no_prediction),
        "approved_no_context": approved_no_context,
        "approved_no_context_count": len(approved_no_context),
        "whole_universe_prediction_failure": whole_universe_failure,
        "status": "gap" if has_gap else "ok",
    }


def build_affordability_report(
    *,
    approved_symbols: Iterable[str],
    price_ranges: Mapping[str, Sequence[float]],
    balance: float,
    position_size_pct: float,
) -> dict[str, Any]:
    """Approved symbols whose integer-share sizing rounds to qty < 1.

    Uses the TOP of each symbol's configured price range as a conservative entry
    price. A symbol with max_qty == 0 cannot be opened at the default size, so it
    can never meet the per-name EV-deployability bar and is effectively
    universe-slot-only.
    """
    balance = float(balance or 0)
    position_size_pct = float(position_size_pct or 0)
    risk_amount = balance * (position_size_pct / 100.0)

    rows: list[dict[str, Any]] = []
    for symbol in approved_symbols:
        rng = price_ranges.get(symbol)
        if not rng:
            continue
        try:
            top_price = float(rng[1] if len(rng) > 1 else rng[0])
        except (TypeError, ValueError, IndexError):
            continue
        max_qty = int(risk_amount / top_price) if top_price > 0 else 0
        rows.append(
            {
                "symbol": str(symbol).upper(),
                "top_price": top_price,
                "max_qty": max_qty,
                "affordable": max_qty >= 1,
            }
        )

    rows.sort(key=lambda r: r["top_price"], reverse=True)
    unaffordable = [r["symbol"] for r in rows if not r["affordable"]]

    return {
        "version": "symbol_affordability_v1",
        "runtime_effect": RUNTIME_EFFECT,
        "balance": balance,
        "position_size_pct": position_size_pct,
        "risk_amount": round(risk_amount, 2),
        "approved_priced_count": len(rows),
        "unaffordable_count": len(unaffordable),
        "unaffordable": unaffordable,
        "rows": rows,
        "status": "gap" if unaffordable else "ok",
    }
