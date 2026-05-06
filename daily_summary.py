import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "trades.db"
LOG_PATH = Path(__file__).parent / "daily_summary.log"

# claude-haiku-4-5-20251001 pricing (per million tokens)
HAIKU_INPUT_CPM  = 0.80
HAIKU_OUTPUT_CPM = 4.00
AVG_INPUT_TOKENS  = 550
AVG_OUTPUT_TOKENS = 125


def _render(rows, header):
    lines = []
    def p(*args):
        line = " ".join(str(a) for a in args)
        lines.append(line)
        print(line)

    p(f"\n{'='*60}")
    p(f"  {header}")
    p(f"{'='*60}")

    # ── 1. Signal overview ────────────────────────────────────────
    total     = len(rows)
    approved  = [r for r in rows if r["approved"]]
    rejected  = [r for r in rows if not r["approved"]]
    apr_rate  = 100 * len(approved) / total if total else 0

    p(f"\n── SIGNALS ──────────────────────────────────────────────")
    p(f"  Total received : {total}")
    p(f"  Approved       : {len(approved)}  ({apr_rate:.0f}%)")
    p(f"  Rejected       : {len(rejected)}  ({100-apr_rate:.0f}%)")

    reason_counts = defaultdict(int)
    for r in rejected:
        reason = r["rejection_reason"] or "unknown"
        rl = reason.lower()
        if "already" in rl or "concentration" in rl or "existing" in rl:
            bucket = "Position already open / concentration risk"
        elif "max" in rl and "position" in rl:
            bucket = "Max position limit reached"
        elif "parse error" in rl or "engine error" in rl:
            bucket = "Parse / engine error"
        elif "outside" in rl or "time" in rl or "hours" in rl:
            bucket = "Outside trading hours"
        elif "loss limit" in rl or "daily" in rl:
            bucket = "Daily loss limit"
        elif "source" in rl:
            bucket = "Invalid signal source"
        elif "short" in rl or "conflict" in rl or "direction" in rl:
            bucket = "Conflicting position direction"
        else:
            bucket = "Other"
        reason_counts[bucket] += 1

    p(f"\n  Rejection breakdown:")
    for bucket, cnt in sorted(reason_counts.items(), key=lambda x: -x[1]):
        p(f"    {cnt:>4}  {bucket}")

    # ── 2. Orders placed vs null by symbol ───────────────────────
    p(f"\n── ORDERS BY SYMBOL ─────────────────────────────────────")
    sym_data = defaultdict(lambda: {"approved": 0, "with_order": 0, "null_order": 0})
    for r in approved:
        sym = r["symbol"]
        sym_data[sym]["approved"] += 1
        if r["order_id"]:
            sym_data[sym]["with_order"] += 1
        else:
            sym_data[sym]["null_order"] += 1

    p(f"  {'Symbol':<6}  {'Approved':>8}  {'Orders':>7}  {'Null':>6}")
    p(f"  {'------':<6}  {'--------':>8}  {'-------':>7}  {'----':>6}")
    for sym, d in sorted(sym_data.items()):
        p(f"  {sym:<6}  {d['approved']:>8}  {d['with_order']:>7}  {d['null_order']:>6}")

    # ── 3 & 4 & 5. P&L via FIFO matching ─────────────────────────
    p(f"\n── REALIZED P&L ─────────────────────────────────────────")

    filled = [r for r in rows if r["order_id"]]
    sym_buys  = defaultdict(list)
    sym_sells = defaultdict(list)
    for r in filled:
        price = r["fill_price"] if r["fill_price"] is not None else r["signal_price"]
        entry = {"qty": r["qty"] or 0, "price": price, "symbol": r["symbol"],
                 "ts": r["timestamp"], "id": r["id"]}
        if r["action"] == "buy":
            sym_buys[r["symbol"]].append(entry)
        else:
            sym_sells[r["symbol"]].append(entry)

    trades_pnl = []
    sym_pnl    = defaultdict(float)

    for sym in set(list(sym_buys) + list(sym_sells)):
        buys  = list(sym_buys[sym])
        sells = list(sym_sells[sym])

        for sell in sells:
            remaining = sell["qty"]
            while remaining > 0 and buys:
                buy = buys[0]
                matched = min(remaining, buy["qty"])
                pnl = (sell["price"] - buy["price"]) * matched
                trades_pnl.append((sym, matched, buy["price"], sell["price"], pnl))
                sym_pnl[sym] += pnl
                buy["qty"] -= matched
                remaining  -= matched
                if buy["qty"] == 0:
                    buys.pop(0)

    if sym_pnl:
        total_pnl = sum(sym_pnl.values())

        p(f"  {'Symbol':<6}  {'P&L':>10}")
        p(f"  {'------':<6}  {'----------':>10}")
        for sym, pnl in sorted(sym_pnl.items(), key=lambda x: -x[1]):
            tag = "+" if pnl >= 0 else ""
            p(f"  {sym:<6}  {tag}{pnl:>9.2f}")
        p(f"  {'------':<6}  {'----------':>10}")
        p(f"  {'TOTAL':<6}  {('+' if total_pnl>=0 else '')}{total_pnl:>9.2f}")

        # ── 4. Win rate ──────────────────────────────────────────
        n_wins   = len([t for t in trades_pnl if t[4] > 0])
        n_losses = len([t for t in trades_pnl if t[4] < 0])
        n_flat   = len([t for t in trades_pnl if t[4] == 0])
        n_total  = n_wins + n_losses + n_flat
        win_rate = 100 * n_wins / n_total if n_total else 0

        p(f"\n── WIN RATE ──────────────────────────────────────────────")
        p(f"  Matched trades : {n_total}")
        p(f"  Wins           : {n_wins}  ({win_rate:.0f}%)")
        p(f"  Losses         : {n_losses}")
        p(f"  Flat           : {n_flat}")

        # ── 5. Best / worst ──────────────────────────────────────
        if trades_pnl:
            best  = max(trades_pnl, key=lambda t: t[4])
            worst = min(trades_pnl, key=lambda t: t[4])
            p(f"\n── BEST / WORST TRADES ───────────────────────────────────")
            p(f"  Best  : {best[0]}  {best[1]} shares  buy={best[2]:.2f} sell={best[3]:.2f}  P&L=+{best[4]:.2f}")
            p(f"  Worst : {worst[0]}  {worst[1]} shares  buy={worst[2]:.2f} sell={worst[3]:.2f}  P&L={worst[4]:.2f}")
    else:
        p("  No matched buy/sell pairs found for this period.")

    # ── 6. Claude API cost estimate ───────────────────────────────
    p(f"\n── CLAUDE API USAGE (est.) ───────────────────────────────")
    api_calls   = total
    input_cost  = api_calls * AVG_INPUT_TOKENS  / 1_000_000 * HAIKU_INPUT_CPM
    output_cost = api_calls * AVG_OUTPUT_TOKENS / 1_000_000 * HAIKU_OUTPUT_CPM
    total_cost  = input_cost + output_cost
    p(f"  Est. API calls : {api_calls}")
    p(f"  Est. tokens    : {api_calls * AVG_INPUT_TOKENS:,} in / {api_calls * AVG_OUTPUT_TOKENS:,} out")
    p(f"  Est. cost      : ${total_cost:.4f}  (Haiku @ $0.80/$4.00 per MTok)")

    p(f"\n{'='*60}\n")

    with open(LOG_PATH, "a") as f:
        f.write("\n".join(lines) + "\n")


def run(target_date: str = None):
    target_date = target_date or str(date.today())
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM trades WHERE timestamp LIKE ?", (f"{target_date}%",)
    ).fetchall()
    con.close()
    _render(rows, f"DAILY SUMMARY — {target_date}")


def run_week(target_date: str = None):
    if target_date:
        ref = date.fromisoformat(target_date)
    else:
        today = date.today()
        # Weekend: roll back to the just-completed Friday; weekday: use current week
        if today.weekday() >= 5:
            ref = today - timedelta(days=today.weekday() - 4)
        else:
            ref = today

    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM trades WHERE timestamp >= ? AND timestamp < ?",
        (monday.isoformat(), (friday + timedelta(days=1)).isoformat())
    ).fetchall()
    con.close()
    _render(rows, f"WEEKLY SUMMARY — {monday} to {friday}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--week":
        run_week(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else None)
