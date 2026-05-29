#!/usr/bin/env python3
"""
Intraday market-context refresh.

Two stages:
  Stage 1 — Collect fresh events via collect_and_score_events.py (max_per_symbol=1,
             deduplication on, --apply-context).  Fast: ~30-50 s for 59 symbols.
  Stage 2 — Re-classify every approved symbol against fresh Alpaca price data and
             the updated daily_symbol_context event scores, then atomically overwrite
             market_context.json so the bot's next signal pick-up uses fresh bias/risk.

Designed for cron use every 45 min during market hours (9–15 ET, Mon–Fri).
"""

import json
import logging
import os
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST
from market_intelligence.market_brief_builder import build_market_brief, write_market_context
from alerts import send_alert

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "market_context.json"
ENV_FILE = Path("/etc/trading-bot.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("intraday_context_refresh")


def _load_env_if_needed():
    if os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY"):
        return
    if not ENV_FILE.exists():
        raise SystemExit(f"ERROR: Alpaca env vars missing and {ENV_FILE} not found")
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_if_needed()

from broker import api  # noqa: E402
from pre_market_research_data import (  # noqa: E402
    get_recent_bars,
    classify_macro,
    classify_symbol,
    build_symbol_evidence,
    build_index_state,
    build_sector_state,
    load_event_enrichment,
    apply_event_enrichment,
    safe_round,
    PRE_MARKET_ALPACA_SYMBOL_SLEEP_SECONDS,
)
import time  # noqa: E402


def _collect_events(market_date: str) -> int:
    """Run Stage 1: collect fresh events via subprocess, return exit code."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "collect_and_score_events.py"),
        "--date", market_date,
        "--max-per-symbol", "1",
        "--apply-context",
    ]
    logger.info(f"Stage 1: collecting fresh events — {' '.join(cmd[2:])}")
    result = subprocess.run(cmd, cwd=SCRIPT_DIR, timeout=180)
    return result.returncode


def _fetch_market_data(symbols: list[str]) -> dict:
    """Fetch fresh Alpaca bars for all symbols, same as pre_market_research_data."""
    market_data = {}
    for i, sym in enumerate(symbols):
        if i > 0 and PRE_MARKET_ALPACA_SYMBOL_SLEEP_SECONDS > 0:
            time.sleep(PRE_MARKET_ALPACA_SYMBOL_SLEEP_SECONDS)
        market_data[sym] = get_recent_bars(sym)
    return market_data


def _rebuild_symbols(
    existing_context: dict,
    market_data: dict,
    event_enrichment: dict,
    macro_sentiment: str,
    macro_regime: str,
) -> dict:
    """Re-classify each symbol; return updated symbols dict."""
    symbols_out = existing_context.get("symbols") or {}

    for sym in APPROVED_SYMBOLS_LIST:
        if sym not in market_data:
            continue
        data = market_data[sym]
        classification = classify_symbol(sym, data, macro_sentiment)
        entry = dict(symbols_out.get(sym) or {})
        entry.update(classification)
        entry.update(
            build_symbol_evidence(data, classification, macro_sentiment, macro_regime)
        )
        entry["data_snapshot"] = {
            "daily_pct": safe_round(data.get("daily_pct")),
            "intraday_pct": safe_round(data.get("intraday_pct")),
            "momentum_30m_pct": safe_round(data.get("momentum_30m_pct")),
            "last_price": safe_round(data.get("last_price"), 4),
            "bar_count_1m": data.get("bar_count_1m", 0),
        }
        apply_event_enrichment(entry, event_enrichment.get(sym) or {})
        symbols_out[sym] = entry

    return symbols_out


def rebuild_market_context(market_date: str) -> dict:
    """Stage 2: fetch fresh prices, re-classify, atomically overwrite market_context.json."""
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(
            f"market_context.json not found at {OUTPUT_FILE}; "
            "pre_market_research_data.py must run first."
        )

    existing = json.loads(OUTPUT_FILE.read_text())

    event_enrichment = load_event_enrichment(market_date)
    logger.info(f"Loaded event enrichment for {len(event_enrichment)} symbols")

    logger.info(f"Fetching fresh Alpaca bars for {len(APPROVED_SYMBOLS_LIST)} symbols")
    market_data = _fetch_market_data(APPROVED_SYMBOLS_LIST)

    macro_sentiment, macro_regime, risk_multiplier, max_new_positions, block_new_buys, macro_summary = classify_macro(market_data)
    logger.info(f"Macro: {macro_sentiment}/{macro_regime} risk_multiplier={risk_multiplier}")

    updated_symbols = _rebuild_symbols(
        existing,
        market_data,
        event_enrichment,
        macro_sentiment,
        macro_regime,
    )

    now_et_str = datetime.now(timezone(timedelta(hours=-4))).isoformat(timespec="seconds")

    existing["symbols"] = updated_symbols
    existing["macro_sentiment"] = macro_sentiment
    existing["macro_regime"] = macro_regime
    existing["risk_multiplier"] = risk_multiplier
    existing["max_new_positions"] = max_new_positions
    existing["block_new_buys"] = block_new_buys
    existing["macro_summary"] = macro_summary
    existing["index_state"] = build_index_state(market_data)
    existing["sector_state"] = build_sector_state(market_data)
    existing["intraday_refresh_at"] = now_et_str
    existing["source_quality"] = "event_enriched" if event_enrichment else "data_only"
    existing["event_enrichment_count"] = len(event_enrichment)

    brief = build_market_brief(existing)

    tmp = OUTPUT_FILE.with_suffix(".json.tmp")
    write_market_context(brief, tmp)
    tmp.rename(OUTPUT_FILE)
    logger.info(f"Wrote refreshed market_context.json ({len(updated_symbols)} symbols)")

    bias_counts = Counter(
        (v or {}).get("bias", "missing") for v in updated_symbols.values()
    )
    return {
        "macro_sentiment": macro_sentiment,
        "macro_regime": macro_regime,
        "risk_multiplier": risk_multiplier,
        "symbols_refreshed": len(updated_symbols),
        "event_enrichment_count": len(event_enrichment),
        "bias_counts": dict(bias_counts),
        "intraday_refresh_at": now_et_str,
    }


def main():
    market_date = date.today().isoformat()
    started = datetime.now()

    print()
    print("=== Intraday context refresh ===")
    print(f"  Date    : {market_date}")
    print(f"  Started : {started.strftime('%H:%M:%S')}")
    print()

    # Stage 1 — collect fresh events
    stage1_rc = _collect_events(market_date)
    if stage1_rc != 0:
        logger.warning(f"collect_and_score_events exited with code {stage1_rc}; continuing to Stage 2")

    # Stage 2 — rebuild market_context.json
    try:
        summary = rebuild_market_context(market_date)
    except Exception as exc:
        logger.error(f"rebuild_market_context failed: {exc}")
        try:
            send_alert(
                title="Intraday context refresh failed",
                message=str(exc),
                severity="error",
                source="intraday_context_refresh.py",
                payload={"market_date": market_date, "error": str(exc)},
            )
        except Exception:
            pass
        raise SystemExit(1)

    elapsed = (datetime.now() - started).total_seconds()

    print()
    print(f"  Macro            : {summary['macro_sentiment']} / {summary['macro_regime']}")
    print(f"  Risk multiplier  : {summary['risk_multiplier']}")
    print(f"  Symbols refreshed: {summary['symbols_refreshed']}")
    print(f"  Event enrichment : {summary['event_enrichment_count']} symbols")
    print(f"  Bias counts      : {summary['bias_counts']}")
    print(f"  Elapsed          : {elapsed:.1f}s")
    print()
    print(f"Intraday context refresh complete — {summary['intraday_refresh_at']}")

    try:
        send_alert(
            title="Intraday context refreshed",
            message=(
                f"market_context.json updated at {summary['intraday_refresh_at']}: "
                f"{summary['macro_sentiment']}/{summary['macro_regime']}, "
                f"{summary['symbols_refreshed']} symbols"
            ),
            severity="info",
            source="intraday_context_refresh.py",
            payload=summary,
        )
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        try:
            send_alert(
                title="Intraday context refresh crashed",
                message=str(exc),
                severity="error",
                source="intraday_context_refresh.py",
                payload={"error": str(exc)},
            )
        except Exception:
            pass
        raise
