import logging
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path
from pnl import get_daily_realized_pnl

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "trades.db"


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
                "unrealized_pl": p["unrealized_pl"],
            }
            for p in positions
        ],
        "open_position_count": len(positions),
        "positions_detail": positions,
        "market_session": "regular",
    }