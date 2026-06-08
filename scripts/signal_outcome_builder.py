#!/usr/bin/env python3
"""
Build historical signal outcomes from imported signals and reconstructed Alpaca outcomes.

Inputs:
- historical_signal_experience
- historical_trade_outcomes

Output:
- historical_signal_outcomes

This is learning-only. It does not touch live trades/matched_trades.

What it measures:
- Was the signal associated with a real reconstructed trade?
- How long after the signal did the actual entry happen?
- How long after the signal did the actual exit happen?
- What P&L was associated with that signal?
- Was the signal likely early, late, or near actual execution?
"""

import argparse
from datetime import datetime

from repositories.signal_outcome_repo import SignalOutcomeRepository

_repo = SignalOutcomeRepository()


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def init_table():
    _repo.init_table()


def pct_change(old, new):
    try:
        old = float(old)
        new = float(new)
        if old == 0:
            return None
        return (new - old) / old * 100.0
    except Exception:
        return None


def load_signals(start_date=None, end_date=None, symbol=None):
    """Load deduped signal events when available, otherwise raw signal experience."""
    params = []
    where = ["first_timestamp IS NOT NULL", "symbol IS NOT NULL", "action IS NOT NULL"]

    if start_date:
        where.append("market_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("market_date <= ?")
        params.append(end_date)
    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())

    try:
        rows = _repo.load_signal_events(where, params)
        if rows:
            return rows
    except Exception:
        pass

    # Fallback for older DBs.
    params = []
    where = ["timestamp IS NOT NULL", "symbol IS NOT NULL", "action IS NOT NULL"]

    if start_date:
        where.append("market_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("market_date <= ?")
        params.append(end_date)
    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())

    return _repo.load_signal_experience(where, params)


def load_outcomes_by_symbol():
    out = {}
    for r in _repo.load_trade_outcomes():
        out.setdefault(r["symbol"], []).append(r)
    return out


def find_matching_outcome(
    signal, outcomes_by_symbol, entry_window_minutes=90, exit_window_minutes=90
):
    symbol = signal["symbol"]
    action = (signal["action"] or "").lower()
    ts = parse_dt(signal["timestamp"])

    if not symbol or not action or not ts:
        return None, None

    candidates = outcomes_by_symbol.get(symbol, [])

    best = None
    best_score = None
    best_kind = None

    for o in candidates:
        entry_ts = parse_dt(o["entry_timestamp"])
        exit_ts = parse_dt(o["exit_timestamp"])
        if not entry_ts or not exit_ts:
            continue

        # Buy signal should align to actual entry.
        if action == "buy":
            delta = (entry_ts - ts).total_seconds() / 60.0

            # Allow signal slightly after entry too, because logs/imports may have small ordering offsets.
            if -5 <= delta <= entry_window_minutes:
                score = abs(delta)
                if best is None or score < best_score:
                    best = o
                    best_score = score
                    best_kind = "entry_match"

        # Sell signal should align to actual exit.
        elif action == "sell":
            delta = (exit_ts - ts).total_seconds() / 60.0
            if -5 <= delta <= exit_window_minutes:
                score = abs(delta)
                if best is None or score < best_score:
                    best = o
                    best_score = score
                    best_kind = "exit_match"

    return best, best_kind


def classify_entry_timing(action, signal_ts, entry_ts, realized_pnl):
    if not signal_ts or not entry_ts:
        return "unmatched"

    delay = (entry_ts - signal_ts).total_seconds() / 60.0

    if action == "sell":
        return "not_entry_signal"

    if delay < -2:
        return "signal_after_entry"
    if delay <= 2:
        return "immediate_entry"
    if delay <= 10:
        return "slight_delay"
    if delay <= 30:
        return "delayed_entry"
    return "very_late_entry"


def classify_exit_timing(action, signal_ts, exit_ts):
    if not signal_ts or not exit_ts:
        return "unmatched"

    delay = (exit_ts - signal_ts).total_seconds() / 60.0

    if action == "buy":
        if delay <= 10:
            return "fast_exit_after_buy"
        if delay <= 45:
            return "normal_intraday_exit"
        return "late_or_held_exit"

    if action == "sell":
        if -2 <= delay <= 2:
            return "immediate_exit"
        if delay <= 10:
            return "slight_exit_delay"
        if delay <= 30:
            return "delayed_exit"
        return "very_late_exit"

    return "unknown"


def classify_learning(signal, outcome, match_kind, entry_delay, exit_delay):
    action = (signal["action"] or "").lower()
    approved = signal["approved"]
    pnl = float(outcome["realized_pnl"] or 0) if outcome else None

    if not outcome:
        if approved == 0:
            return "rejected_no_trade", "Rejected/gated signal had no matched reconstructed trade."
        return "unmatched_signal", "No reconstructed Alpaca outcome matched this signal."

    if action == "buy":
        if pnl is not None and pnl > 0:
            if entry_delay is not None and entry_delay > 30:
                return (
                    "profitable_but_late_entry",
                    "Buy signal eventually matched a profitable trade, but actual entry was delayed over 30 minutes.",
                )
            return "profitable_entry", "Buy signal matched a profitable reconstructed trade."

        if pnl is not None and pnl < 0:
            if entry_delay is not None and entry_delay <= 2:
                return (
                    "immediate_entry_lost",
                    "Immediate buy entry matched a losing reconstructed trade.",
                )
            return "losing_entry", "Buy signal matched a losing reconstructed trade."

        return "flat_entry", "Buy signal matched a flat reconstructed trade."

    if action == "sell":
        if pnl is not None and pnl > 0:
            return (
                "profitable_exit_context",
                "Sell signal matched exit of a profitable reconstructed trade.",
            )
        if pnl is not None and pnl < 0:
            return "loss_exit_context", "Sell signal matched exit of a losing reconstructed trade."
        return "flat_exit_context", "Sell signal matched exit of a flat reconstructed trade."

    return "matched_other", f"Signal matched reconstructed outcome via {match_kind or 'unknown'}."


def build_row(signal, outcome, match_kind):
    signal_ts = parse_dt(signal["timestamp"])
    entry_ts = parse_dt(outcome["entry_timestamp"]) if outcome else None
    exit_ts = parse_dt(outcome["exit_timestamp"]) if outcome else None

    entry_delay = None
    exit_delay = None

    if signal_ts and entry_ts:
        entry_delay = (entry_ts - signal_ts).total_seconds() / 60.0

    if signal_ts and exit_ts:
        exit_delay = (exit_ts - signal_ts).total_seconds() / 60.0

    action = (signal["action"] or "").lower()

    entry_label = classify_entry_timing(
        action,
        signal_ts,
        entry_ts,
        float(outcome["realized_pnl"] or 0) if outcome else None,
    )
    exit_label = classify_exit_timing(action, signal_ts, exit_ts)

    learning_label, learning_reason = classify_learning(
        signal, outcome, match_kind, entry_delay, exit_delay
    )

    signal_price = signal["signal_price"]

    entry_price = outcome["entry_price"] if outcome else None
    exit_price = outcome["exit_price"] if outcome else None

    return {
        "signal_id": signal["id"],
        "market_date": signal["market_date"],
        "symbol": signal["symbol"],
        "action": action,
        "signal_timestamp": signal["timestamp"],
        "signal_price": signal_price,
        "approved": signal["approved"],
        "decision_summary": signal["decision_summary"],
        "rejection_reason": signal["rejection_reason"],
        "matched_outcome_id": outcome["id"] if outcome else None,
        "outcome_source": outcome["source"] if outcome else None,
        "entry_timestamp": outcome["entry_timestamp"] if outcome else None,
        "exit_timestamp": outcome["exit_timestamp"] if outcome else None,
        "entry_delay_minutes": entry_delay,
        "exit_delay_minutes": exit_delay,
        "holding_minutes": outcome["holding_minutes"] if outcome else None,
        "qty": outcome["qty"] if outcome else None,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "realized_pnl": outcome["realized_pnl"] if outcome else None,
        "realized_pnl_pct": outcome["realized_pnl_pct"] if outcome else None,
        "exit_type": outcome["exit_type"] if outcome else None,
        "signal_to_entry_pct": pct_change(signal_price, entry_price),
        "signal_to_exit_pct": pct_change(signal_price, exit_price),
        "entry_timing_label": entry_label,
        "exit_timing_label": exit_label,
        "learning_label": learning_label,
        "learning_reason": learning_reason,
    }


def insert_rows(rows, replace=False):
    return _repo.insert_signal_outcome_rows(rows, replace=replace)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--symbol")
    parser.add_argument("--entry-window-minutes", type=float, default=90)
    parser.add_argument("--exit-window-minutes", type=float, default=90)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace", action="store_true", help="Clear historical_signal_outcomes before insert"
    )
    args = parser.parse_args()

    init_table()

    signals = load_signals(args.start_date, args.end_date, args.symbol)
    outcomes_by_symbol = load_outcomes_by_symbol()

    rows = []
    matched = 0

    for sig in signals:
        outcome, kind = find_matching_outcome(
            sig,
            outcomes_by_symbol,
            entry_window_minutes=args.entry_window_minutes,
            exit_window_minutes=args.exit_window_minutes,
        )
        if outcome:
            matched += 1
        rows.append(build_row(sig, outcome, kind))

    print()
    print("=== Signal outcome builder ===")
    print(f"  Signals loaded : {len(signals)}")
    print(f"  Matched        : {matched}")
    print(f"  Unmatched      : {len(signals) - matched}")
    print(f"  Dry run        : {args.dry_run}")
    print(f"  Replace        : {args.replace}")

    by_label = {}
    for r in rows:
        by_label[r["learning_label"]] = by_label.get(r["learning_label"], 0) + 1

    print(f"  Learning labels: {by_label}")

    print()
    print(
        f"  {'Date':<10} {'Sym':<6} {'Act':<5} {'SigTime':<19} {'EntryDelay':>10} {'ExitDelay':>9} {'P&L':>9} {'EntryLabel':<18} {'Learning':<24}"
    )
    print(
        f"  {'-' * 10} {'-' * 6} {'-' * 5} {'-' * 19} {'-' * 10} {'-' * 9} {'-' * 9} {'-' * 18} {'-' * 24}"
    )

    for r in rows[:60]:
        pnl = "-" if r["realized_pnl"] is None else f"{float(r['realized_pnl']):+.2f}"
        ed = "-" if r["entry_delay_minutes"] is None else f"{float(r['entry_delay_minutes']):.1f}"
        xd = "-" if r["exit_delay_minutes"] is None else f"{float(r['exit_delay_minutes']):.1f}"
        print(
            f"  {str(r['market_date'] or '-'):<10} "
            f"{str(r['symbol'] or '-'):<6} "
            f"{str(r['action'] or '-'):<5} "
            f"{str(r['signal_timestamp'] or '-'):<19} "
            f"{ed:>10} "
            f"{xd:>9} "
            f"{pnl:>9} "
            f"{str(r['entry_timing_label'] or '-'):<18} "
            f"{str(r['learning_label'] or '-'):<24}"
        )

    if len(rows) > 60:
        print(f"  ... {len(rows) - 60} more rows")

    if args.dry_run:
        return 0

    inserted = insert_rows(rows, replace=args.replace)
    print()
    print(f"Inserted/updated historical_signal_outcomes rows: {inserted}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
