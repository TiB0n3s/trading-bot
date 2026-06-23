from __future__ import annotations

import os
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST

from repositories import auto_buy_repo


def _int_value(row, key: str) -> int:
    if row is None:
        return 0
    return int(row[key] or 0)


def _internal_signal_mode_active() -> bool:
    mode = os.getenv("AUTO_BUY_SIGNAL_MODE", "legacy_source_gate").strip().lower()
    deprecated = os.getenv("TRADINGVIEW_ALERTS_DEPRECATED", "false").strip().lower()
    return deprecated in {"1", "true", "yes", "on"} or mode in {
        "internal_all",
        "bar_all",
        "all_internal",
    }


def run_signal_source_readiness(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"

    print()
    print("=" * 78)
    print(f"  Signal Source Readiness - {target_date}")
    print("=" * 78)

    if not db_path.exists():
        print(f"[WARN] trades.db not found at {db_path}")
        return False

    if not auto_buy_repo.table_exists("auto_buy_candidates", db_path=db_path):
        print("[WARN] auto_buy_candidates table is missing; run auto_buy_manager.py first")
        return False

    mode = os.getenv("AUTO_BUY_SIGNAL_MODE", "legacy_source_gate").strip().lower()
    deprecated = os.getenv("TRADINGVIEW_ALERTS_DEPRECATED", "false").strip().lower()
    allow_tv_live = os.getenv("AUTO_BUY_ALLOW_TRADINGVIEW_LIVE", "false").strip().lower()
    internal_active = _internal_signal_mode_active()

    print("Configuration")
    print(f"  approved symbols                 {len(APPROVED_SYMBOLS_LIST):>8}")
    print(f"  legacy TradingView cohort         {len(TRADINGVIEW_ALERT_SYMBOLS_LIST):>8}")
    print(f"  AUTO_BUY_SIGNAL_MODE              {mode}")
    print(f"  TRADINGVIEW_ALERTS_DEPRECATED     {deprecated}")
    print(f"  AUTO_BUY_ALLOW_TRADINGVIEW_LIVE   {allow_tv_live}")
    print(f"  internal all-symbol execution     {str(internal_active).lower()}")
    print()

    summary = auto_buy_repo.signal_source_readiness_summary(target_date, db_path=db_path)
    print("Candidate coverage")
    print(f"  candidate rows                    {_int_value(summary, 'rows'):>8}")
    print(f"  internal-source rows              {_int_value(summary, 'internal_rows'):>8}")
    print(f"  legacy-tv-source rows             {_int_value(summary, 'legacy_tv_rows'):>8}")
    print(f"  internal strong candidates        {_int_value(summary, 'internal_strong'):>8}")
    print(f"  legacy-tv strong candidates       {_int_value(summary, 'legacy_tv_strong'):>8}")
    print(f"  internal submitted                {_int_value(summary, 'internal_submitted'):>8}")
    print(f"  legacy-tv submitted               {_int_value(summary, 'legacy_tv_submitted'):>8}")
    print()

    print("Candidate distribution by source")
    source_rows = auto_buy_repo.signal_source_decision_rows(target_date, db_path=db_path)
    if source_rows:
        for row in source_rows:
            max_score = row["max_score"]
            max_s = f"{max_score:.2f}" if max_score is not None else "-"
            print(
                f"  {row['signal_source']:<22} {row['decision']:<24} "
                f"{int(row['n'] or 0):>6} submitted={int(row['submitted'] or 0):>4} "
                f"max={max_s:>7}"
            )
    else:
        print("  none")
    print()

    print("Live block reasons")
    block_rows = auto_buy_repo.live_block_reason_rows(target_date, db_path=db_path)
    source_gate_blocks = 0
    if block_rows:
        for row in block_rows:
            reason = str(row["live_block_reason"] or "")
            n = int(row["n"] or 0)
            if "tradingview alert symbol requires webhook approval path" in reason:
                source_gate_blocks += n
            print(f"  {row['signal_source']:<22} {n:>6} {reason}")
    else:
        print("  none")
    print()

    print("[OK] signal-source readiness check completed")
    return True
