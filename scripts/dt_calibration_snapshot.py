#!/usr/bin/env python3
"""Read-only calibration snapshot for Deep Thought (Jarvis Tier 3).

NO TRADE AUTHORITY, NO MUTATION. Opens trades.db read-only and buckets matched
trades by the bot's prediction_score, reporting per-bucket the (min-max normalized)
mean predicted score vs the REALIZED win rate (fraction with realized_pnl_pct > 0),
plus an overall Brier of normalized-score vs win. This is a discrimination/calibration
proxy over matched_trades (the table that carries both a prediction and a realized
outcome); refine the table/columns as the bot's schema evolves. Prints stamped JSON.

Usage: python3 scripts/dt_calibration_snapshot.py --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

RUNTIME_EFFECT = "diagnostic_only_no_schema_or_data_mutation"
_C1 = Path(__file__).resolve().parent.parent / "trades.db"
DB = _C1 if _C1.exists() else (Path.cwd() / "trades.db")
N_BUCKETS = 10
MIN_BUCKET_N = 10  # buckets below this are flagged low_n; not excluded


def _snapshot() -> dict:
    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT prediction_score AS s, realized_pnl_pct AS r FROM matched_trades "
        "WHERE prediction_score IS NOT NULL AND realized_pnl_pct IS NOT NULL"
    ).fetchall()
    conn.close()
    pts = [(float(x["s"]), 1.0 if float(x["r"]) > 0 else 0.0) for x in rows]
    if len(pts) < N_BUCKETS:
        return {"buckets": [], "n": len(pts), "note": "insufficient matched_trades for calibration"}
    smin = min(p[0] for p in pts)
    smax = max(p[0] for p in pts)
    span = (smax - smin) or 1.0
    norm = [((s - smin) / span, win) for s, win in pts]
    norm.sort(key=lambda p: p[0])
    buckets = []
    brier_sum = 0.0
    per = max(len(norm) // N_BUCKETS, 1)
    for i in range(0, len(norm), per):
        chunk = norm[i:i + per]
        if not chunk:
            continue
        pred = sum(p for p, _ in chunk) / len(chunk)
        real = sum(w for _, w in chunk) / len(chunk)
        buckets.append({"bucket": "%.2f-%.2f" % (chunk[0][0], chunk[-1][0]),
                        "predicted": round(pred, 3), "realized": round(real, 3), "n": len(chunk),
                        "low_n": len(chunk) < MIN_BUCKET_N})
        brier_sum += sum((p - w) ** 2 for p, w in chunk)
    brier = round(brier_sum / len(norm), 4)
    return {"buckets": buckets, "n": len(norm), "brier": brier,
            "source": "matched_trades.prediction_score vs realized_pnl_pct>0"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only calibration snapshot (no authority)")
    ap.add_argument("--json", action="store_true")
    ap.parse_args()
    out = {"runtime_effect": RUNTIME_EFFECT}
    try:
        out.update(_snapshot())
    except Exception as exc:
        out.update({"error": str(exc), "buckets": []})
    print(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
