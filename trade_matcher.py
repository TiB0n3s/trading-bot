#!/usr/bin/env python3
import json
from collections import defaultdict, deque
from datetime import datetime

from db import DB_PATH, get_connection


MATCH_SOURCE_FIELDS = [
    "match_source",
    "entry_source",
    "exit_order_id",
    "exit_reason",
]

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

                # Exit-side source fields.
                item["match_source"] = "fifo_match"
                item["entry_source"] = "webhook_buy"
                item["exit_order_id"] = row_get(row, "order_id")
                item["exit_reason"] = row_get(row, "rejection_reason")

                matched.append(item)

                lot["qty"] -= matched_qty
                remaining -= matched_qty

                if lot["qty"] <= 0:
                    open_lots[symbol].popleft()

    # Synthetic matches for filled position-manager exits that had no matching
    # approved BUY lot in trades.db, usually legacy/orphan positions.
    synthetic = []

    with get_connection(DB_PATH) as con:
        sells = con.execute("""
            SELECT *
            FROM trades
            WHERE action = 'sell'
              AND approved = 1
              AND order_status = 'filled'
              AND fill_price IS NOT NULL
              AND rejection_reason LIKE 'position_manager_%'
            ORDER BY timestamp ASC
        """).fetchall()

        existing_synthetic_order_ids = {
            str(row["exit_order_id"] or "")
            for row in con.execute("""
                SELECT exit_order_id
                FROM matched_trades
                WHERE match_source = 'synthetic_position_manager_exit'
                  AND exit_order_id IS NOT NULL
            """).fetchall()
        }

        for sell_row in sells:
            order_id = str(sell_row["order_id"] or "")
            if not order_id:
                continue

            if order_id in existing_synthetic_order_ids:
                continue

            # If this exact sell already exists as a normal matched trade, skip.
            normal_match_exists = any(
                t.get("symbol") == sell_row["symbol"]
                and t.get("exit_timestamp") == sell_row["timestamp"]
                for t in matched
            )
            if normal_match_exists:
                continue

            item = _synthetic_match_from_position_manager_exit(con, sell_row)
            if item:
                synthetic.append(item)

        if synthetic:
            insert_fields = [
                "symbol", "entry_timestamp", "exit_timestamp", "holding_minutes",
                "qty", "entry_price", "exit_price", "realized_pnl",
                "realized_pnl_pct", "won",
            ] + ENTRY_CONTEXT_FIELDS + MATCH_SOURCE_FIELDS

            placeholders = ", ".join(["?"] * len(insert_fields))
            columns = ", ".join(insert_fields)

            for t in synthetic:
                con.execute(
                    f"INSERT INTO matched_trades ({columns}) VALUES ({placeholders})",
                    [t.get(field) for field in insert_fields],
                )

    if synthetic:
        matched.extend(synthetic)

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
            buy_opportunity_reason TEXT,
            exit_reason TEXT,
            exit_order_id TEXT,
            entry_source TEXT,
            match_source TEXT
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



def _event_payload_for_order(con, order_id):
    """Find bot_events payload for a position-manager order by Alpaca order_id."""
    if not order_id:
        return None

    try:
        rows = con.execute("""
            SELECT payload_json
            FROM bot_events
            WHERE event_type = 'POSITION_MANAGER_ORDER'
              AND payload_json LIKE ?
            ORDER BY id DESC
            LIMIT 1
        """, (f"%{order_id}%",)).fetchall()
    except Exception:
        return None

    if not rows:
        return None

    try:
        return json.loads(rows[0]["payload_json"] or "{}")
    except Exception:
        return None


def _synthetic_match_from_position_manager_exit(con, sell_row):
    """
    Build a synthetic matched trade for a filled position-manager sell that has
    no recorded FIFO buy lot in trades.db.

    This is for legacy/orphan positions where Alpaca held the position but
    the entry leg was not logged as an approved filled BUY in trades.db.
    """
    payload = _event_payload_for_order(con, sell_row["order_id"])
    if not payload:
        return None

    decision = payload.get("decision") or {}

    try:
        qty = float(sell_row["qty"] or decision.get("qty") or 0)
        entry_price = float(decision.get("avg_entry") or 0)
        exit_price = float(sell_row["fill_price"] or 0)
    except Exception:
        return None

    if qty <= 0 or entry_price <= 0 or exit_price <= 0:
        return None

    realized_pnl = round((exit_price - entry_price) * qty, 2)
    realized_pnl_pct = round(((exit_price - entry_price) / entry_price) * 100.0, 3)
    won = 1 if realized_pnl > 0 else 0

    return {
        "symbol": sell_row["symbol"],
        "entry_timestamp": None,
        "exit_timestamp": sell_row["timestamp"],
        "holding_minutes": None,
        "qty": qty,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": realized_pnl_pct,
        "won": won,

        # Entry-side context from position-manager decision/payload.
        "macro_regime": None,
        "risk_multiplier": None,
        "market_bias": None,
        "risk_level": None,
        "entry_quality": None,
        "trend_direction": None,
        "trend_strength": None,
        "momentum_direction": None,
        "momentum_pct": None,
        "correlation_cluster": None,
        "cluster_exposure_pct": None,

        "market_bias_effective": None,
        "market_bias_override_reason": None,
        "fundamental_score": None,

        "session_trend_label": None,
        "session_trend_score": None,
        "session_return_pct": None,
        "session_momentum_5m_pct": decision.get("momentum_5m_pct"),
        "session_momentum_15m_pct": decision.get("momentum_15m_pct"),
        "session_momentum_30m_pct": decision.get("momentum_30m_pct"),
        "session_distance_from_vwap_pct": decision.get("vwap_dist_pct"),
        "session_momentum_reason": None,

        "prediction_score": None,
        "prediction_decision": None,
        "prediction_reason": None,

        "setup_label": None,
        "setup_policy_action": None,
        "setup_policy_reason": None,
        "setup_confidence_adjustment": None,
        "setup_size_multiplier": None,

        "buy_opportunity_score": None,
        "buy_opportunity_recommendation": None,
        "buy_opportunity_reason": None,

        "match_source": "synthetic_position_manager_exit",
        "entry_source": "position_manager_avg_entry",
        "exit_order_id": sell_row["order_id"],
        "exit_reason": sell_row["rejection_reason"],
    }


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
    ] + ENTRY_CONTEXT_FIELDS + MATCH_SOURCE_FIELDS

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
