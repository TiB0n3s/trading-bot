#!/usr/bin/env python3
from collections import defaultdict, deque
from datetime import datetime

from db import DB_PATH, get_connection


ENTRY_CONTEXT_FIELDS = [
    "macro_regime",
    "risk_multiplier",
    "market_bias",
    "risk_level",
    "entry_quality",
    "trend_direction",
    "trend_strength",
    "momentum_direction",
    "momentum_pct",
    "correlation_cluster",
    "cluster_exposure_pct",

    # Newer live intelligence fields copied from the entry-side BUY row.
    "market_bias_effective",
    "market_bias_override_reason",
    "fundamental_score",

    "session_trend_label",
    "session_trend_score",
    "session_return_pct",
    "session_momentum_5m_pct",
    "session_momentum_15m_pct",
    "session_momentum_30m_pct",
    "session_distance_from_vwap_pct",
    "session_momentum_reason",

    "prediction_score",
    "prediction_decision",
    "prediction_reason",

    "setup_label",
    "setup_policy_action",
    "setup_policy_reason",
    "setup_confidence_adjustment",
    "setup_size_multiplier",

    "buy_opportunity_score",
    "buy_opportunity_recommendation",
    "buy_opportunity_reason",
]


def parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def row_get(row, key, default=None):
    """sqlite3.Row-safe getter for schemas that may be mid-migration."""
    try:
        return row[key]
    except Exception:
        return default


def load_filled_trades():
    con = get_connection(DB_PATH)

    rows = con.execute("""
        SELECT *
        FROM trades
        WHERE approved = 1
          AND action IN ('buy', 'sell')
          AND qty IS NOT NULL
          AND fill_price IS NOT NULL
          AND order_status IN ('filled', 'partially_filled')
        ORDER BY timestamp ASC, id ASC
    """).fetchall()

    con.close()
    return rows


def match_trades():
    rows = load_filled_trades()
    open_lots = defaultdict(deque)
    matched = []

    for row in rows:
        symbol = row["symbol"]
        action = row["action"]
        qty = float(row["qty"] or 0)
        price = float(row["fill_price"] or 0)

        if not symbol or qty <= 0 or price <= 0:
            continue

        if action == "buy":
            open_lots[symbol].append({
                "timestamp": row["timestamp"],
                "qty": qty,
                "price": price,
                "row": row,
            })
            continue

        if action == "sell":
            remaining = qty

            while remaining > 0 and open_lots[symbol]:
                lot = open_lots[symbol][0]
                matched_qty = min(remaining, lot["qty"])

                entry_price = lot["price"]
                exit_price = price
                pnl = (exit_price - entry_price) * matched_qty
                pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0

                entry_ts = parse_ts(lot["timestamp"])
                exit_ts = parse_ts(row["timestamp"])
                holding_minutes = None
                if entry_ts and exit_ts:
                    holding_minutes = round((exit_ts - entry_ts).total_seconds() / 60, 2)

                entry_row = lot["row"]

                item = {
                    "symbol": symbol,
                    "entry_timestamp": lot["timestamp"],
                    "exit_timestamp": row["timestamp"],
                    "holding_minutes": holding_minutes,
                    "qty": matched_qty,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "realized_pnl": round(pnl, 2),
                    "realized_pnl_pct": round(pnl_pct, 3),
                    "won": 1 if pnl > 0 else 0,
                }

                # Entry-side decision/intelligence context.
                for field in ENTRY_CONTEXT_FIELDS:
                    item[field] = row_get(entry_row, field)

                matched.append(item)

                lot["qty"] -= matched_qty
                remaining -= matched_qty

                if lot["qty"] <= 0:
                    open_lots[symbol].popleft()

    return matched, open_lots


def init_matched_trades_table():
    con = get_connection(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS matched_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            entry_timestamp TEXT,
            exit_timestamp TEXT,
            holding_minutes REAL,
            qty REAL,
            entry_price REAL,
            exit_price REAL,
            realized_pnl REAL,
            realized_pnl_pct REAL,
            won INTEGER,

            macro_regime TEXT,
            risk_multiplier REAL,
            market_bias TEXT,
            risk_level TEXT,
            entry_quality TEXT,
            trend_direction TEXT,
            trend_strength TEXT,
            momentum_direction TEXT,
            momentum_pct REAL,
            correlation_cluster TEXT,
            cluster_exposure_pct REAL,

            market_bias_effective TEXT,
            market_bias_override_reason TEXT,
            fundamental_score TEXT,

            session_trend_label TEXT,
            session_trend_score REAL,
            session_return_pct REAL,
            session_momentum_5m_pct REAL,
            session_momentum_15m_pct REAL,
            session_momentum_30m_pct REAL,
            session_distance_from_vwap_pct REAL,
            session_momentum_reason TEXT,

            prediction_score REAL,
            prediction_decision TEXT,
            prediction_reason TEXT,

            setup_label TEXT,
            setup_policy_action TEXT,
            setup_policy_reason TEXT,
            setup_confidence_adjustment REAL,
            setup_size_multiplier REAL,

            buy_opportunity_score REAL,
            buy_opportunity_recommendation TEXT,
            buy_opportunity_reason TEXT
        )
    """)

    # Idempotently add columns for existing DBs.
    existing = {
        row["name"]
        for row in con.execute("PRAGMA table_info(matched_trades)").fetchall()
    }

    add_columns = {
        "market_bias_effective": "TEXT",
        "market_bias_override_reason": "TEXT",
        "fundamental_score": "TEXT",
        "session_trend_label": "TEXT",
        "session_trend_score": "REAL",
        "session_return_pct": "REAL",
        "session_momentum_5m_pct": "REAL",
        "session_momentum_15m_pct": "REAL",
        "session_momentum_30m_pct": "REAL",
        "session_distance_from_vwap_pct": "REAL",
        "session_momentum_reason": "TEXT",
        "prediction_score": "REAL",
        "prediction_decision": "TEXT",
        "prediction_reason": "TEXT",
        "setup_label": "TEXT",
        "setup_policy_action": "TEXT",
        "setup_policy_reason": "TEXT",
        "setup_confidence_adjustment": "REAL",
        "setup_size_multiplier": "REAL",
        "buy_opportunity_score": "REAL",
        "buy_opportunity_recommendation": "TEXT",
        "buy_opportunity_reason": "TEXT",
    }

    for name, typ in add_columns.items():
        if name not in existing:
            con.execute(f"ALTER TABLE matched_trades ADD COLUMN {name} {typ}")

    con.commit()
    con.close()


def rebuild_matched_trades():
    matched, open_lots = match_trades()
    init_matched_trades_table()

    con = get_connection(DB_PATH)
    con.execute("DELETE FROM matched_trades")

    columns = [
        "symbol",
        "entry_timestamp",
        "exit_timestamp",
        "holding_minutes",
        "qty",
        "entry_price",
        "exit_price",
        "realized_pnl",
        "realized_pnl_pct",
        "won",
    ] + ENTRY_CONTEXT_FIELDS

    placeholders = ", ".join(["?"] * len(columns))
    col_sql = ", ".join(columns)

    for t in matched:
        values = [t.get(c) for c in columns]
        con.execute(
            f"INSERT INTO matched_trades ({col_sql}) VALUES ({placeholders})",
            values,
        )

    con.commit()
    con.close()
    return matched, open_lots


def main():
    matched, open_lots = rebuild_matched_trades()

    print("Matched trades:", len(matched))
    print()

    realized = sum(t["realized_pnl"] for t in matched)
    wins = [t for t in matched if t["realized_pnl"] > 0]
    losses = [t for t in matched if t["realized_pnl"] < 0]

    print(f"Realized P&L: ${realized:.2f}")
    print(f"Wins: {len(wins)}")
    print(f"Losses: {len(losses)}")

    if matched:
        print(f"Win rate: {len(wins) / len(matched) * 100:.1f}%")
        print(f"Expectancy: ${realized / len(matched):.2f} per matched trade")

    print()
    print("Recent matched trades:")
    for t in matched[-10:]:
        print(
            f"{t['symbol']} qty={t['qty']} "
            f"{t['entry_price']} → {t['exit_price']} "
            f"PnL=${t['realized_pnl']} "
            f"hold={t['holding_minutes']}m "
            f"trend={t.get('trend_direction')}/{t.get('trend_strength')} "
            f"setup={t.get('setup_label')}/{t.get('setup_policy_action')} "
            f"session={t.get('session_trend_label')}/{t.get('session_trend_score')} "
            f"prediction={t.get('prediction_score')}/{t.get('prediction_decision')} "
            f"buy_opp={t.get('buy_opportunity_score')}/{t.get('buy_opportunity_recommendation')} "
            f"macro={t.get('macro_regime')}"
        )

    print()
    print("Open lots:")
    for symbol, lots in open_lots.items():
        open_qty = sum(lot["qty"] for lot in lots)
        if open_qty > 0:
            print(f"{symbol}: {open_qty} shares across {len(lots)} lots")


if __name__ == "__main__":
    main()
