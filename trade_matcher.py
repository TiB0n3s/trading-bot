#!/usr/bin/env python3
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from db import DB_PATH, get_connection


def parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


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

                matched.append({
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

                    # Entry-side decision context
                    "macro_regime": entry_row["macro_regime"],
                    "risk_multiplier": entry_row["risk_multiplier"],
                    "market_bias": entry_row["market_bias"],
                    "risk_level": entry_row["risk_level"],
                    "entry_quality": entry_row["entry_quality"],
                    "trend_direction": entry_row["trend_direction"],
                    "trend_strength": entry_row["trend_strength"],
                    "momentum_direction": entry_row["momentum_direction"],
                    "momentum_pct": entry_row["momentum_pct"],
                    "correlation_cluster": entry_row["correlation_cluster"],
                    "cluster_exposure_pct": entry_row["cluster_exposure_pct"],
                })

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
            cluster_exposure_pct REAL
        )
    """)
    con.commit()
    con.close()


def rebuild_matched_trades():
    matched, open_lots = match_trades()
    init_matched_trades_table()

    con = get_connection(DB_PATH)
    con.execute("DELETE FROM matched_trades")

    for t in matched:
        con.execute("""
            INSERT INTO matched_trades (
                symbol, entry_timestamp, exit_timestamp, holding_minutes,
                qty, entry_price, exit_price, realized_pnl, realized_pnl_pct, won,
                macro_regime, risk_multiplier, market_bias, risk_level, entry_quality,
                trend_direction, trend_strength, momentum_direction, momentum_pct,
                correlation_cluster, cluster_exposure_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            t["symbol"], t["entry_timestamp"], t["exit_timestamp"], t["holding_minutes"],
            t["qty"], t["entry_price"], t["exit_price"], t["realized_pnl"],
            t["realized_pnl_pct"], t["won"],
            t["macro_regime"], t["risk_multiplier"], t["market_bias"],
            t["risk_level"], t["entry_quality"], t["trend_direction"],
            t["trend_strength"], t["momentum_direction"], t["momentum_pct"],
            t["correlation_cluster"], t["cluster_exposure_pct"],
        ))

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
            f"trend={t['trend_direction']}/{t['trend_strength']} "
            f"macro={t['macro_regime']}"
        )

    print()
    print("Open lots:")
    for symbol, lots in open_lots.items():
        open_qty = sum(lot["qty"] for lot in lots)
        if open_qty > 0:
            print(f"{symbol}: {open_qty} shares across {len(lots)} lots")


if __name__ == "__main__":
    main()
