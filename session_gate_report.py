#!/usr/bin/env python3
"""
Session momentum gate outcome correlation report.

For each approved BUY decision recorded in decision_snapshots, reconstructs
whether the session momentum gate WOULD have blocked (using the same logic as
_evaluate_session_momentum_gate), then correlates that with realized outcomes
from matched_trades.

Run once decision_snapshots starts accumulating data from live paper sessions.

Usage:
  python3 session_gate_report.py
  python3 session_gate_report.py --date 2026-05-26
  python3 session_gate_report.py --start-date 2026-05-20 --end-date 2026-05-26
"""

from __future__ import annotations

import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

from repositories.ops_check_repo import OpsCheckRepository


def _would_gate_block(
    session_label: str | None,
    session_score: int | None,
    setup_action: str | None,
    prediction_score: int | None,
    trend_direction: str | None,
    trend_strength: str | None,
) -> tuple[bool, str]:
    """Mirror of _evaluate_session_momentum_gate logic in app.py."""
    session_score = int(session_score or 0)
    prediction_score = int(prediction_score or 0)

    hard_negative = session_label == "downtrend" or session_score <= -5
    soft_negative = session_label == "fading" or session_score <= -2

    if hard_negative and setup_action != "boost":
        return True, "hard_negative"

    if (
        soft_negative
        and prediction_score < 8
        and not (
            trend_direction == "bullish"
            and trend_strength == "confirmed"
            and setup_action == "boost"
        )
    ):
        return True, "soft_negative"

    return False, "pass"


def _pct(n, total):
    if total == 0:
        return 0.0
    return n / total * 100.0


def _fmt_pct(v):
    if v is None:
        return "  N/A"
    return f"{v:+.2f}%"


def _mean(values):
    vs = [v for v in values if v is not None]
    return sum(vs) / len(vs) if vs else None


def _build_date_clause(start_date, end_date, column="substr(ds.decision_time,1,10)"):
    parts = []
    params = []
    if start_date:
        parts.append(f"{column} >= ?")
        params.append(start_date)
    if end_date:
        parts.append(f"{column} <= ?")
        params.append(end_date)
    return (" AND " + " AND ".join(parts)) if parts else "", params


def run_report(start_date=None, end_date=None, db_path=BASE_DIR / "trades.db"):
    repo = OpsCheckRepository(db_path)
    date_clause, date_params = _build_date_clause(start_date, end_date)

    # Load all approved BUY decision snapshots with session fields.
    rows = repo.session_gate_snapshot_rows(date_clause, date_params)

    # Load trades actually rejected by the session gate.
    blocked_rows = repo.session_gate_blocked_trade_rows(date_clause, date_params)

    if not rows:
        date_range = ""
        if start_date or end_date:
            date_range = f" for {start_date or '?'} to {end_date or '?'}"
        print(f"No decision_snapshots{date_range}. Run after a live paper session.")
        if blocked_rows:
            print(f"\nFound {len(blocked_rows)} session-gate hard rejections in trades table:")
            for r in blocked_rows[:20]:
                print(f"  {r['timestamp'][:16]}  {r['symbol']:6s}  {r['rejection_reason'][:80]}")
        return

    # Partition snapshots into gate_would_block / gate_passes.
    gate_block_approved = []
    gate_block_rejected_elsewhere = []
    gate_pass_approved = []
    gate_pass_rejected_elsewhere = []

    for r in rows:
        would_block, severity = _would_gate_block(
            r["session_trend_label"],
            r["session_trend_score"],
            r["setup_policy_action"],
            r["prediction_score"],
            r["trend_direction"],
            r["trend_strength"],
        )
        matched = r["realized_pnl"] is not None
        pnl = float(r["realized_pnl"] or 0) if matched else None
        pnl_pct = float(r["realized_pnl_pct"] or 0) if matched else None

        entry = {
            "symbol": r["symbol"],
            "time": r["decision_time"][:16],
            "session_label": r["session_trend_label"],
            "session_score": r["session_trend_score"],
            "severity": severity,
            "final_decision": r["final_decision"],
            "matched": matched,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        }

        if would_block:
            if r["approved"]:
                gate_block_approved.append(entry)
            else:
                gate_block_rejected_elsewhere.append(entry)
        else:
            if r["approved"]:
                gate_pass_approved.append(entry)
            else:
                gate_pass_rejected_elsewhere.append(entry)

    def _outcome_summary(label, entries):
        matched = [e for e in entries if e["matched"]]
        winners = [e for e in matched if (e["pnl"] or 0) > 0]
        losers = [e for e in matched if (e["pnl"] or 0) < 0]
        avg_pnl_pct = _mean([e["pnl_pct"] for e in matched])
        total_pnl = sum(e["pnl"] or 0 for e in matched)
        win_rate = _pct(len(winners), len(matched)) if matched else None

        print(f"\n  {label}")
        print(f"    Signals      : {len(entries)}")
        print(f"    With outcomes: {len(matched)}")
        if matched:
            print(f"    Winners      : {len(winners)}  ({win_rate:.0f}%)")
            print(f"    Losers       : {len(losers)}")
            print(f"    Avg PnL%     : {_fmt_pct(avg_pnl_pct)}")
            print(f"    Total PnL    : ${total_pnl:+.2f}")

    # Date range summary
    if rows:
        dates = [r["decision_time"][:10] for r in rows]
        print(f"\nSession Gate Outcome Correlation")
        print(f"  Dates    : {min(dates)} to {max(dates)}")
        print(f"  Snapshots: {len(rows)}  (buy signals)")
    print()
    print("GATE WOULD BLOCK (observe-only — ENFORCE_SESSION_MOMENTUM_GATE=False)")
    print("-" * 64)
    _outcome_summary("Would-block, but approved anyway (gate off):", gate_block_approved)
    _outcome_summary("Would-block, rejected by other gate:", gate_block_rejected_elsewhere)

    print()
    print("GATE WOULD PASS")
    print("-" * 64)
    _outcome_summary("Gate passes, trade approved:", gate_pass_approved)
    _outcome_summary("Gate passes, rejected by other gate:", gate_pass_rejected_elsewhere)

    # Enforcement simulation summary.
    total_matched_pass = [e for e in gate_pass_approved if e["matched"]]
    total_matched_block = [e for e in gate_block_approved if e["matched"]]
    if total_matched_pass or total_matched_block:
        pass_wr = _pct(
            sum(1 for e in total_matched_pass if (e["pnl"] or 0) > 0),
            len(total_matched_pass),
        ) if total_matched_pass else None
        block_wr = _pct(
            sum(1 for e in total_matched_block if (e["pnl"] or 0) > 0),
            len(total_matched_block),
        ) if total_matched_block else None

        print()
        print("ENFORCEMENT SIMULATION")
        print("-" * 64)
        print(f"  Trades that would survive enforcement : {len(gate_pass_approved)}")
        print(f"  Trades that would be stopped by gate : {len(gate_block_approved)}")
        if pass_wr is not None:
            print(f"  Win rate (gate passes)               : {pass_wr:.0f}%")
        if block_wr is not None:
            print(f"  Win rate (gate would block)          : {block_wr:.0f}%")
        note = (
            "Gate is HELPFUL"
            if (block_wr is not None and pass_wr is not None and pass_wr > block_wr)
            else "Gate needs more data"
            if len(total_matched_block) < 5
            else "Gate may be filtering good trades — review"
        )
        print(f"  Assessment                           : {note}")

    # Session-gate hard rejections from trades table.
    if blocked_rows:
        print()
        print(f"HARD REJECTIONS in trades table (gate was enforced): {len(blocked_rows)}")
        for r in blocked_rows[:15]:
            ts = r["timestamp"][:16] if r["timestamp"] else "?"
            print(f"  {ts}  {r['symbol']:6s}  {(r['rejection_reason'] or '')[:70]}")


def main():
    parser = argparse.ArgumentParser(description="Session gate outcome correlation report")
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--start-date", help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date YYYY-MM-DD")
    args = parser.parse_args()

    start = args.date or args.start_date
    end = args.date or args.end_date
    run_report(start_date=start, end_date=end)


if __name__ == "__main__":
    main()
