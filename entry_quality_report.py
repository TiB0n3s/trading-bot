#!/usr/bin/env python3
"""Post-session entry-quality validation report.

Read-only. Segments matched BUY outcomes by observe-only entry intelligence
fields captured in decision_snapshots and matched_trades.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from statistics import mean

from db import DB_PATH, get_connection

MIN_BUCKET_SAMPLE = 20


def _bucket_extension(value):
    if value is None:
        return "unknown"
    v = float(value)
    if v >= 8.0:
        return ">=8% (overextended)"
    if v >= 5.0:
        return "5-8% (extended)"
    if v >= 3.0:
        return "3-5% (slightly_extended)"
    if v >= 0.0:
        return "0-3% (normal)"
    return "<0% (pullback)"


def _bucket_prior(value):
    if value is None:
        return "unknown"
    v = float(value)
    if v > 5.0:
        return ">5% (strong prior)"
    if v > 3.0:
        return "3-5% (good prior)"
    if v > 1.5:
        return "1.5-3% (up prior)"
    if v >= -1.5:
        return "-1.5-1.5% (flat prior)"
    return "<-1.5% (down prior)"


def _bucket_setup_score(value):
    if value is None:
        return "unknown"
    v = int(value)
    if v >= 70:
        return ">=70 (favorable)"
    if v >= 50:
        return "50-69 (watch)"
    if v >= 30:
        return "30-49 (weak)"
    return "<30 (avoid)"


def _rows(target_date: str):
    with get_connection(DB_PATH) as con:
        return con.execute(
            """
            SELECT ds.symbol,
                   ds.decision_time,
                   ds.momentum_state,
                   ds.volume_state,
                   ds.extension_from_recent_base_pct,
                   ds.rolling_special_labels,
                   ds.prior_session_return_pct,
                   ds.prior_session_participated,
                   ds.tape_label_at_signal,
                   ds.tape_bar_age_seconds,
                   ds.setup_label,
                   ds.setup_score,
                   ds.setup_rationale,
                   mt.realized_pnl_pct,
                   mt.won,
                   mt.exit_reason,
                   mt.holding_minutes
            FROM decision_snapshots ds
            JOIN trades t ON t.id = ds.trade_id
            JOIN matched_trades mt
              ON mt.symbol = t.symbol
             AND mt.entry_timestamp = t.timestamp
            WHERE substr(ds.decision_time, 1, 10) = ?
              AND lower(ds.action) = 'buy'
              AND ds.approved = 1
              AND mt.realized_pnl_pct IS NOT NULL
            ORDER BY ds.decision_time ASC, ds.symbol ASC
            """,
            (target_date,),
        ).fetchall()


def _rows_all():
    with get_connection(DB_PATH) as con:
        return con.execute(
            """
            SELECT ds.symbol,
                   ds.decision_time,
                   ds.momentum_state,
                   ds.volume_state,
                   ds.extension_from_recent_base_pct,
                   ds.rolling_special_labels,
                   ds.prior_session_return_pct,
                   ds.prior_session_participated,
                   ds.tape_label_at_signal,
                   ds.tape_bar_age_seconds,
                   ds.setup_label,
                   ds.setup_score,
                   ds.setup_rationale,
                   mt.realized_pnl_pct,
                   mt.won,
                   mt.exit_reason,
                   mt.holding_minutes
            FROM decision_snapshots ds
            JOIN trades t ON t.id = ds.trade_id
            JOIN matched_trades mt
              ON mt.symbol = t.symbol
             AND mt.entry_timestamp = t.timestamp
            WHERE lower(ds.action) = 'buy'
              AND ds.approved = 1
              AND mt.realized_pnl_pct IS NOT NULL
            ORDER BY ds.decision_time ASC, ds.symbol ASC
            """,
        ).fetchall()


def _summarize(rows, key_fn):
    buckets = defaultdict(list)
    for row in rows:
        buckets[key_fn(row)].append(float(row["realized_pnl_pct"]))
    return buckets


def _print_bucket_table(title, buckets):
    print()
    print("-" * 72)
    print(title)
    print("-" * 72)
    print(f"{'Bucket':<34} {'N':>5} {'AvgPnL%':>10} {'WinRate%':>10} {'Status'}")
    for bucket in sorted(buckets):
        values = buckets[bucket]
        status = "" if len(values) >= MIN_BUCKET_SAMPLE else "  [low_sample]"
        # win rate requires per-row won flag; approximate from sign of pnl
        wins = sum(1 for v in values if v > 0)
        wr = wins / len(values) * 100 if values else 0
        print(
            f"{str(bucket):<34} {len(values):>5} {mean(values):>10.3f} {wr:>9.0f}%{status}"
        )


def _print_exit_reason_table(rows):
    print()
    print("-" * 72)
    print("Exit Reason Distribution")
    print("-" * 72)
    counts: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        reason = r["exit_reason"] or "unknown"
        # Shorten position_manager reasons to their type
        if reason.startswith("position_manager_full_exit"):
            key = "position_manager_full_exit"
        elif reason.startswith("position_manager_partial_exit"):
            key = "position_manager_partial_exit"
        elif reason.startswith("synthetic_bracket_exit"):
            key = "bracket_exit (historical)"
        else:
            key = reason[:40] if reason else "unknown"
        counts[key].append(float(r["realized_pnl_pct"]))

    print(f"{'Exit Type':<40} {'N':>5} {'AvgPnL%':>10} {'WinRate%':>10}")
    for key in sorted(counts, key=lambda k: -len(counts[k])):
        vals = counts[key]
        wins = sum(1 for v in vals if v > 0)
        wr = wins / len(vals) * 100 if vals else 0
        print(f"{key:<40} {len(vals):>5} {mean(vals):>10.3f} {wr:>9.0f}%")


def _print_modifier_table(rows):
    """Compare outcomes when setup_engine score modifiers fired vs. did not."""
    print()
    print("-" * 72)
    print("Setup Score Modifier Impact (setup_engine)")
    print("-" * 72)
    with_mod: list[float] = []
    without_mod: list[float] = []
    for r in rows:
        rationale = r["setup_rationale"] or ""
        pnl = float(r["realized_pnl_pct"])
        if "[modifiers:" in rationale:
            with_mod.append(pnl)
        else:
            without_mod.append(pnl)

    def _fmt(label, vals):
        if not vals:
            return f"  {label:<28} n=0  (no data)"
        wins = sum(1 for v in vals if v > 0)
        wr = wins / len(vals) * 100
        note = "" if len(vals) >= MIN_BUCKET_SAMPLE else "  [low_sample]"
        return f"  {label:<28} n={len(vals):>4}  avg={mean(vals):>+.3f}%  win={wr:.0f}%{note}"

    print(_fmt("modifiers_fired", with_mod))
    print(_fmt("no_modifiers", without_mod))


def report(target_date: str | None, all_history: bool = False) -> int:
    if all_history:
        rows = _rows_all()
        header_date = "ALL HISTORY"
    else:
        rows = _rows(target_date or "")
        header_date = target_date or ""

    print("=" * 72)
    print(f"Entry Quality Report - {header_date}")
    print("=" * 72)
    print("Read-only: no gates are enforced by this report.")
    print(f"Matched approved BUY entries: {len(rows)}")
    print(f"Minimum sample per claim: {MIN_BUCKET_SAMPLE}")

    if not rows:
        print("[INFO] No matched BUY outcomes available yet.")
        return 0

    # ── existing segments ────────────────────────────────────────────────────
    _print_bucket_table(
        "Outcome By Momentum State",
        _summarize(rows, lambda r: r["momentum_state"] or "unknown"),
    )
    _print_bucket_table(
        "Outcome By Volume State",
        _summarize(rows, lambda r: r["volume_state"] or "unknown"),
    )
    _print_bucket_table(
        "Outcome By Extension From Recent Base",
        _summarize(rows, lambda r: _bucket_extension(r["extension_from_recent_base_pct"])),
    )
    _print_bucket_table(
        "Outcome By Prior Session Return",
        _summarize(rows, lambda r: _bucket_prior(r["prior_session_return_pct"])),
    )
    _print_bucket_table(
        "Strong Prior Session + Pullback In Uptrend",
        _summarize(
            rows,
            lambda r: (
                "prior>3 + pullback"
                if (r["prior_session_return_pct"] is not None)
                and float(r["prior_session_return_pct"]) > 3.0
                and "pullback_in_uptrend" in str(r["rolling_special_labels"] or "")
                else "other"
            ),
        ),
    )

    # ── new segments using setup_label / setup_score / exit_reason ───────────
    _print_bucket_table(
        "Outcome By Setup Label (setup_engine)",
        _summarize(rows, lambda r: r["setup_label"] or "unknown"),
    )
    _print_bucket_table(
        "Outcome By Setup Score Bucket",
        _summarize(rows, lambda r: _bucket_setup_score(r["setup_score"])),
    )
    _print_bucket_table(
        "Outcome By Tape Label At Signal",
        _summarize(rows, lambda r: r["tape_label_at_signal"] or "unknown"),
    )
    _print_exit_reason_table(rows)
    _print_modifier_table(rows)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="Market date YYYY-MM-DD")
    group.add_argument("--all", action="store_true", help="All history")
    args = parser.parse_args()
    return report(target_date=args.date, all_history=args.all)


if __name__ == "__main__":
    raise SystemExit(main())
