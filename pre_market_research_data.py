#!/usr/bin/env python3
"""
No-Claude pre-market research.

Builds market_context.json-compatible research from Alpaca market data only.
No Anthropic calls. No web_search. No model dependency.

Designed for reliable cron use:
- deterministic
- fast
- conservative on missing data
- writes /tmp samples safely
- only writes live market_context.json when explicitly targeted or when no
  --build-output is provided
"""

import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST
from market_intelligence.raw_research_template import build_template
from market_intelligence.research_output import raw_research_summary
from market_intelligence.market_brief_builder import (
    build_market_brief,
    write_market_context,
    summary_for_brief,
)
from market_intelligence.intelligence_store import ingest_market_context

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "market_context.json"
ENV_FILE = Path("/etc/trading-bot.env")

SYMBOLS = APPROVED_SYMBOLS_LIST
INDEX_SYMBOLS = ("SPY", "QQQ", "IWM", "GLD")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("pre_market_research_data")


def load_env_if_needed():
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

    logger.info(f"Loaded env from {ENV_FILE}")


load_env_if_needed()

from broker import api  # noqa: E402


def pct_change(old, new):
    try:
        old = float(old)
        new = float(new)
        if old <= 0:
            return None
        return (new - old) / old * 100
    except Exception:
        return None


def safe_round(v, digits=3):
    return None if v is None else round(float(v), digits)


def get_recent_bars(symbol):
    """Return lightweight recent data from Alpaca IEX feed."""
    out = {
        "symbol": symbol,
        "daily_pct": None,
        "intraday_pct": None,
        "momentum_30m_pct": None,
        "last_price": None,
        "bar_count_1m": 0,
        "error": None,
    }

    now = datetime.now(timezone.utc)

    try:
        daily_start = (now - timedelta(days=10)).isoformat()
        daily_bars = list(api.get_bars(symbol, "1Day", start=daily_start, feed="iex"))
        if len(daily_bars) >= 2:
            prev = daily_bars[-2]
            last = daily_bars[-1]
            out["daily_pct"] = pct_change(float(prev.c), float(last.c))
            out["last_price"] = float(last.c)
        elif len(daily_bars) == 1:
            out["last_price"] = float(daily_bars[-1].c)
    except Exception as e:
        out["error"] = f"daily bars failed: {e}"

    try:
        minute_start = (now - timedelta(hours=8)).isoformat()
        minute_bars = list(api.get_bars(symbol, "1Min", start=minute_start, feed="iex"))
        minute_bars = minute_bars[-120:]
        out["bar_count_1m"] = len(minute_bars)

        if len(minute_bars) >= 2:
            first = float(minute_bars[0].c)
            last = float(minute_bars[-1].c)
            out["intraday_pct"] = pct_change(first, last)
            out["last_price"] = last

        if len(minute_bars) >= 30:
            first_30 = float(minute_bars[-30].c)
            last_30 = float(minute_bars[-1].c)
            out["momentum_30m_pct"] = pct_change(first_30, last_30)

    except Exception as e:
        if out["error"]:
            out["error"] += f"; minute bars failed: {e}"
        else:
            out["error"] = f"minute bars failed: {e}"

    return out


def classify_macro(market):
    spy = market.get("SPY", {})
    qqq = market.get("QQQ", {})
    iwm = market.get("IWM", {})
    gld = market.get("GLD", {})

    spy_mom = spy.get("intraday_pct")
    qqq_mom = qqq.get("intraday_pct")
    iwm_mom = iwm.get("intraday_pct")
    gld_mom = gld.get("intraday_pct")

    risk_assets = [v for v in (spy_mom, qqq_mom, iwm_mom) if v is not None]
    risk_avg = sum(risk_assets) / len(risk_assets) if risk_assets else 0.0

    if risk_avg >= 0.35 and (gld_mom is None or gld_mom < 0.5):
        return "risk-on", "risk_on", 1.0, 8, False, "Index momentum is positive across risk assets."
    if risk_avg <= -0.35:
        return "risk-off", "defensive", 0.5, 4, False, "Index momentum is negative; using defensive sizing."
    if risk_avg <= -0.15:
        return "mixed", "caution", 0.75, 6, False, "Index momentum is mildly negative/mixed; using caution sizing."

    return "mixed", "caution", 0.75, 6, False, "Index context is mixed or incomplete; using caution defaults."


def classify_symbol(symbol, data, macro_sentiment):
    daily = data.get("daily_pct")
    intra = data.get("intraday_pct")
    mom30 = data.get("momentum_30m_pct")
    bars = data.get("bar_count_1m", 0)

    reason_bits = []

    if data.get("error") and daily is None and intra is None:
        return {
            "bias": "neutral",
            "reason": f"No reliable Alpaca market-data read; {data.get('error')}",
            "confidence": "low",
            "fundamental_score": "neutral",
            "risk_level": "medium",
            "entry_quality": "conditional",
            "avoid_type": None,
        }

    if daily is not None:
        reason_bits.append(f"daily={daily:+.2f}%")
    if intra is not None:
        reason_bits.append(f"intraday={intra:+.2f}%")
    if mom30 is not None:
        reason_bits.append(f"30m={mom30:+.2f}%")

    reason = ", ".join(reason_bits) if reason_bits else "Limited Alpaca data; conservative neutral."

    # Conservative avoid rules.
    if intra is not None and intra <= -1.0:
        return {
            "bias": "avoid",
            "reason": f"Negative pre-market/intraday tape: {reason}",
            "confidence": "medium",
            "fundamental_score": "neutral",
            "risk_level": "high",
            "entry_quality": "conditional",
            "avoid_type": "soft",
        }

    if daily is not None and daily <= -2.0:
        return {
            "bias": "avoid",
            "reason": f"Weak recent daily trend: {reason}",
            "confidence": "medium",
            "fundamental_score": "neutral",
            "risk_level": "high",
            "entry_quality": "conditional",
            "avoid_type": "soft",
        }

    # Chase-prevention: big move up but short-term momentum fading.
    if daily is not None and daily >= 3.0 and mom30 is not None and mom30 < 0:
        return {
            "bias": "avoid",
            "reason": f"Extended daily move with fading short-term tape: {reason}",
            "confidence": "medium",
            "fundamental_score": "neutral",
            "risk_level": "high",
            "entry_quality": "avoid_chasing",
            "avoid_type": "soft",
        }

    # Buy rules: only if broader tape is not risk-off.
    if macro_sentiment != "risk-off":
        if intra is not None and intra >= 0.45 and (mom30 is None or mom30 >= 0.10):
            return {
                "bias": "buy",
                "reason": f"Positive live tape and short-term momentum: {reason}",
                "confidence": "medium" if bars >= 20 else "low",
                "fundamental_score": "neutral",
                "risk_level": "medium",
                "entry_quality": "good_if_holds_gap",
                "avoid_type": None,
            }

        if daily is not None and daily >= 1.25 and (intra is None or intra >= -0.20):
            return {
                "bias": "buy",
                "reason": f"Positive recent trend without major tape weakness: {reason}",
                "confidence": "low",
                "fundamental_score": "neutral",
                "risk_level": "medium",
                "entry_quality": "good_on_pullbacks",
                "avoid_type": None,
            }

    return {
        "bias": "neutral",
        "reason": f"No decisive data-only edge: {reason}",
        "confidence": "low",
        "fundamental_score": "neutral",
        "risk_level": "medium",
        "entry_quality": "conditional",
        "avoid_type": None,
    }


def should_write_live(build_output):
    if not build_output:
        return True

    requested = Path(build_output)
    if not requested.is_absolute():
        requested = SCRIPT_DIR / requested

    return requested.resolve() == OUTPUT_FILE.resolve()


def backup_live_context():
    if not OUTPUT_FILE.exists():
        return None

    backup = OUTPUT_FILE.with_name(
        f"{OUTPUT_FILE.name}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    backup.write_text(OUTPUT_FILE.read_text())
    return backup


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Market date YYYY-MM-DD, default today")
    parser.add_argument("--raw-output", help="Optional raw research output path")
    parser.add_argument("--build-output", help="Optional built market context output path")
    parser.add_argument("--max-symbols", type=int, help="Debug: limit symbols processed")
    parser.add_argument("--ingest-context", action="store_true", help="Store built context in daily_symbol_context")
    args = parser.parse_args()

    started = datetime.now()
    today = args.date or date.today().isoformat()

    symbols = SYMBOLS[: args.max_symbols] if args.max_symbols else SYMBOLS

    logger.info(f"Running no-Claude data research for {len(symbols)} symbols")

    market_data = {}
    for sym in symbols:
        market_data[sym] = get_recent_bars(sym)

    macro_sentiment, macro_regime, risk_multiplier, max_new_positions, block_new_buys, macro_summary = classify_macro(market_data)

    template = build_template(today)
    template["source"] = "pre_market_research_data_only"
    template["format"] = "raw_research_v1"
    template["generated_at"] = datetime.now().isoformat(timespec="seconds")
    template["macro_sentiment"] = macro_sentiment
    template["macro_regime"] = macro_regime
    template["risk_multiplier"] = risk_multiplier
    template["max_new_positions"] = max_new_positions
    template["block_new_buys"] = block_new_buys
    template["macro_summary"] = macro_summary
    template["data_only"] = True

    symbols_out = template.get("symbols", {})

    for sym in SYMBOLS:
        if sym in market_data:
            symbols_out[sym].update(classify_symbol(sym, market_data[sym], macro_sentiment))
            symbols_out[sym]["data_snapshot"] = {
                "daily_pct": safe_round(market_data[sym].get("daily_pct")),
                "intraday_pct": safe_round(market_data[sym].get("intraday_pct")),
                "momentum_30m_pct": safe_round(market_data[sym].get("momentum_30m_pct")),
                "last_price": safe_round(market_data[sym].get("last_price"), 4),
                "bar_count_1m": market_data[sym].get("bar_count_1m", 0),
            }
        else:
            symbols_out[sym].update({
                "bias": "neutral",
                "reason": "Not processed in debug-limited data run.",
                "confidence": "low",
                "fundamental_score": "neutral",
                "risk_level": "medium",
                "entry_quality": "conditional",
                "avoid_type": None,
            })

    template["symbols"] = symbols_out

    raw_path = None
    if args.raw_output:
        raw_path = write_json(args.raw_output, template)
        logger.info(f"Wrote raw data-only research {raw_path}")

    brief = build_market_brief(template)

    built_path = None
    if args.build_output:
        built_path = Path(args.build_output)
        if not built_path.is_absolute():
            built_path = SCRIPT_DIR / built_path
        built_path.parent.mkdir(parents=True, exist_ok=True)
        write_market_context(brief, built_path)
        logger.info(f"Wrote built data-only market context {built_path}")

    live_written = False
    ingest_summary = None
    if should_write_live(args.build_output):
        backup = backup_live_context()
        if backup:
            logger.info(f"Backed up live context to {backup}")
        write_market_context(brief, OUTPUT_FILE)
        logger.info(f"Wrote live market context {OUTPUT_FILE}")
        live_written = True
    else:
        logger.info(f"Skipped live {OUTPUT_FILE} write because --build-output targets {args.build_output}")

    if args.ingest_context:
        ingest_target = built_path if built_path else OUTPUT_FILE
        ingest_summary = ingest_market_context(ingest_target)
        logger.info(
            f"Ingested market context into daily_symbol_context: "
            f"{ingest_summary['symbols']} symbols for {ingest_summary['market_date']}"
        )

    elapsed = (datetime.now() - started).total_seconds()
    bias_counts = Counter((e or {}).get("bias", "missing") for e in template["symbols"].values())

    print()
    print("=== No-Claude pre-market research complete ===")
    print(f"  Date        : {today}")
    print(f"  Elapsed     : {elapsed:.1f}s")
    print(f"  Macro       : {macro_sentiment} / {macro_regime}")
    print(f"  Risk mult   : {risk_multiplier}")
    print(f"  Max pos     : {max_new_positions}")
    print(f"  Bias counts : {dict(bias_counts)}")
    print(f"  Raw output  : {raw_path or '(not written)'}")
    print(f"  Raw summary : {raw_research_summary(template)}")
    print(f"  Built output: {built_path or '(not written)'}")
    print(f"  Built summary: {summary_for_brief(brief)}")
    print(f"  Live output : {OUTPUT_FILE if live_written else '(not modified)'}")
    print(f"  DB ingest   : {ingest_summary if ingest_summary else '(not requested)'}")
    print()
    print(f"  {'Symbol':<7} {'Bias':<8} {'Conf':<7} {'Risk':<10} {'Entry':<22} Reason")
    print(f"  {'-'*7} {'-'*8} {'-'*7} {'-'*10} {'-'*22} {'-'*60}")

    for sym in SYMBOLS:
        e = template["symbols"].get(sym, {})
        print(
            f"  {sym:<7} "
            f"{e.get('bias', '-'):<8} "
            f"{e.get('confidence', '-'):<7} "
            f"{str(e.get('risk_level') or '-'):<10} "
            f"{str(e.get('entry_quality') or '-'):<22} "
            f"{(e.get('reason') or '')[:80]}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
