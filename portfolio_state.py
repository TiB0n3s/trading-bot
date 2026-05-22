import logging
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path
from pnl import get_daily_realized_pnl
from market_time import now_et

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "trades.db"


def _session_time_context():
    """Return trading-window elapsed/remaining minutes for Claude context."""
    try:
        now = now_et()
        market_open  = now.replace(hour=9,  minute=45, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=45, second=0, microsecond=0)
        elapsed      = max(0, round((now - market_open).total_seconds()  / 60))
        until_close  = max(0, round((market_close - now).total_seconds() / 60))
        return {
            "session_elapsed_minutes": elapsed,
            "minutes_until_close":     until_close,
        }
    except Exception:
        return {"session_elapsed_minutes": None, "minutes_until_close": None}


def get_account_snapshot(api, get_account_func):
    """Return canonical account snapshot from Alpaca."""
    snapshot = {
        "balance": 10000.00,
        "portfolio_value": None,
        "buying_power": None,
        "account_status": None,
    }

    try:
        account = get_account_func()
        if account:
            snapshot["balance"] = account.get("balance", snapshot["balance"])
            snapshot["portfolio_value"] = account.get("portfolio_value")
            snapshot["buying_power"] = account.get("buying_power")
            snapshot["account_status"] = account.get("status")
    except Exception as e:
        logger.error(f"portfolio_state: failed to fetch account: {e}")

    return snapshot


def get_open_positions(api):
    """Return canonical open-position list and unrealized P&L."""
    positions_out = []
    unrealized_pnl = 0.0

    try:
        positions = api.list_positions()
        for p in positions:
            try:
                qty = float(p.qty)
                unrealized = float(p.unrealized_pl)
                market_value = float(getattr(p, "market_value", 0) or 0)
                current_price = float(getattr(p, "current_price", 0) or 0)
                avg_entry = float(getattr(p, "avg_entry_price", 0) or 0)

                positions_out.append({
                    "symbol": p.symbol,
                    "qty": qty,
                    "avg_entry_price": avg_entry,
                    "current_price": current_price,
                    "market_value": market_value,
                    "unrealized_pl": unrealized,
                })
                unrealized_pnl += unrealized
            except Exception as e:
                logger.warning(f"portfolio_state: failed to parse position {getattr(p, 'symbol', '?')}: {e}")
    except Exception as e:
        logger.error(f"portfolio_state: failed to fetch positions: {e}")

    return positions_out, unrealized_pnl


def get_realized_pnl_today(db_path=DB_PATH, target_date=None):
    return get_daily_realized_pnl(target_date=target_date)


def _portfolio_stress(positions, balance):
    """Summarise portfolio-level risk state for Claude context."""
    try:
        if not positions:
            return {
                "positions_in_loss":   0,
                "positions_in_profit": 0,
                "largest_loss_pct":    None,
                "largest_gain_pct":    None,
                "portfolio_heat":      "neutral",
            }
        loss_pcts, gain_pcts = [], []
        for pos in positions:
            cost = (pos.get("avg_entry_price") or 0) * (pos.get("qty") or 0)
            if cost <= 0:
                continue
            pct = round(pos.get("unrealized_pl", 0) / cost * 100, 2)
            (loss_pcts if pct < 0 else gain_pcts).append(pct)
        largest_loss = min(loss_pcts) if loss_pcts else None
        largest_gain = max(gain_pcts) if gain_pcts else None
        n_loss  = len(loss_pcts)
        n_total = len(positions)
        if largest_loss is not None and largest_loss < -1.5:
            heat = "stressed"
        elif n_total > 0 and n_loss >= n_total * 0.6:
            heat = "elevated"
        elif gain_pcts and not loss_pcts:
            heat = "positive"
        else:
            heat = "neutral"
        return {
            "positions_in_loss":   n_loss,
            "positions_in_profit": len(gain_pcts),
            "largest_loss_pct":    largest_loss,
            "largest_gain_pct":    largest_gain,
            "portfolio_heat":      heat,
        }
    except Exception:
        return {"portfolio_heat": "neutral"}


def build_account_state(api, get_account_func, db_path=DB_PATH):
    """Canonical runtime account state used by app.py and decision_engine.py."""
    account = get_account_snapshot(api, get_account_func)
    positions, unrealized_pnl = get_open_positions(api)
    realized_pnl = get_realized_pnl_today(db_path=db_path)

    portfolio_value = account.get("portfolio_value") or account.get("balance") or 0
    daily_pnl = unrealized_pnl + realized_pnl
    start_of_day = portfolio_value - daily_pnl

    daily_pnl_pct = 0.0
    if start_of_day > 0:
        daily_pnl_pct = daily_pnl / start_of_day * 100

    return {
        "balance": account.get("balance", 10000.00),
        "portfolio_value": account.get("portfolio_value"),
        "buying_power": account.get("buying_power"),
        "account_status": account.get("account_status"),
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_pct": round(daily_pnl_pct, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "open_positions": [
            {
                "symbol": p["symbol"],
                "qty": p["qty"],
                "avg_entry_price": p["avg_entry_price"],
                "current_price": p["current_price"],
                "market_value": p["market_value"],
                "unrealized_pl": p["unrealized_pl"],
                "unrealized_pl_pct": round(
                    p["unrealized_pl"] / (p["avg_entry_price"] * p["qty"]) * 100, 2
                ) if p.get("avg_entry_price") and p.get("qty") else None,
            }
            for p in positions
        ],
        "open_position_count": len(positions),
        "positions_detail": positions,
        "market_session": "regular",
        **_session_time_context(),
        "portfolio_stress": _portfolio_stress(positions, account.get("balance", 0)),
    }