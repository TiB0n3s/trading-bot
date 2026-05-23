#!/usr/bin/env python3
"""
Pre-market research — batched Claude Sonnet web_search.

Researches all approved symbols in batches and produces a per-symbol trading
bias (buy / avoid / neutral) plus macro sentiment. Writes market_context.json
next to this file.

Safety goals:
- Output exactly the bot-approved symbol universe.
- Never include non-approved symbols in market_context.json.
- Default any omitted approved symbol to neutral/low.
- Keep one normalized schema consumed by app.py.
"""

import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST
from market_intelligence.research_output import write_raw_research, raw_research_summary
from market_intelligence.market_brief_builder import build_market_brief, write_market_context, summary_for_brief

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "market_context.json"
ENV_FILE = Path("/etc/trading-bot.env")

SYMBOLS = APPROVED_SYMBOLS_LIST

MODEL = os.getenv("PRE_MARKET_MODEL", "claude-sonnet-4-6")
TIMEOUT_SECONDS = float(os.getenv("PRE_MARKET_TIMEOUT_SECONDS", "180"))
BATCH_SIZE = int(os.getenv("PRE_MARKET_BATCH_SIZE", "8"))
WEB_SEARCH_MAX_USES = int(os.getenv("PRE_MARKET_WEB_SEARCH_MAX_USES", "4"))

WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": WEB_SEARCH_MAX_USES,
}

VALID_BIAS = {"buy", "avoid", "neutral"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_FUNDAMENTAL = {
    "strong_bullish", "bullish", "neutral", "bearish", "strong_bearish"
}
VALID_RISK = {"low", "medium", "high", "very_high"}
VALID_ENTRY_QUALITY = {
    "excellent",
    "good_on_pullbacks",
    "good_if_holds_gap",
    "good_if_breadth_holds",
    "tactical_only",
    "hedge_only",
    "do_not_chase",
    "avoid_chasing",
    "conditional",
}
VALID_AVOID_TYPE = {"hard", "soft"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("pre_market_research")


def _load_env_if_needed():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return

    if not ENV_FILE.exists():
        logger.error(f"ANTHROPIC_API_KEY not set and {ENV_FILE} not found")
        sys.exit(1)

    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        logger.info(f"Loaded env from {ENV_FILE}")
    except Exception as e:
        logger.error(f"Failed to read {ENV_FILE}: {e}")
        sys.exit(1)


_load_env_if_needed()
from anthropic import Anthropic, APITimeoutError  # noqa: E402

client = Anthropic()


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _extract_final_text(message) -> str:
    parts = []
    for block in message.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def _parse_json_response(raw: str) -> dict:
    cleaned = raw.strip()
    cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    candidates = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if candidates:
        cleaned = cleaned[min(candidates):]
    return json.loads(cleaned)


def _clean_enum(value, valid_values, default=None):
    if value is None:
        return default
    normalized = str(value).lower().strip().replace(" ", "_").replace("-", "_")
    return normalized if normalized in valid_values else default


def _normalize_symbol_entry(entry: dict | None) -> dict:
    entry = entry or {}

    bias = _clean_enum(entry.get("bias"), VALID_BIAS, "neutral")
    confidence = _clean_enum(entry.get("confidence"), VALID_CONFIDENCE, "low")
    fundamental_score = _clean_enum(entry.get("fundamental_score"), VALID_FUNDAMENTAL, None)
    risk_level = _clean_enum(entry.get("risk_level"), VALID_RISK, None)
    entry_quality = _clean_enum(entry.get("entry_quality"), VALID_ENTRY_QUALITY, None)
    avoid_type = _clean_enum(entry.get("avoid_type"), VALID_AVOID_TYPE, None)

    if bias != "avoid":
        avoid_type = None

    return {
        "bias": bias,
        "reason": entry.get("reason") or "no significant pre-market signals found",
        "confidence": confidence,
        "fundamental_score": fundamental_score,
        "risk_level": risk_level,
        "entry_quality": entry_quality,
        "avoid_type": avoid_type,
    }


def build_prompt(today: str, batch_symbols: list[str], batch_num: int, total_batches: int) -> str:
    batch_csv = ", ".join(batch_symbols)
    approved_csv = ", ".join(SYMBOLS)

    return f"""Respond with JSON only. No preamble, no explanation, no markdown fences.

Today is {today}. This is batch {batch_num} of {total_batches} for my approved trading-bot universe.

Approved universe:
{approved_csv}

For THIS batch only, research these symbols:
{batch_csv}

Bias rules — apply consistently:
- "avoid": earnings reported today, recent analyst downgrade, major negative news, pre-market down more than 1%, debt or credit warning, severe gap-down risk, or very poor tactical entry.
- "buy": strong pre-market move up, recent analyst upgrade, positive earnings beat, strong guidance, clear sector tailwind, or market-leading relative strength.
- "neutral": no significant news, flat pre-market, mixed signals, or insufficient edge.

Confidence:
- "high": clear directional signal with multiple supporting datapoints.
- "medium": one or two supporting datapoints.
- "low": sparse data or conflicting signals.

Fundamental score:
- "strong_bullish": major positive earnings/guidance/news or very strong institutional/analyst support.
- "bullish": positive but not decisive.
- "neutral": no fundamental edge.
- "bearish": negative but not catastrophic.
- "strong_bearish": major negative earnings/guidance/news/downgrade/credit issue.

Risk level:
- "low": broad ETF or stable liquid large-cap with clean context.
- "medium": normal liquid large-cap/ETF risk.
- "high": high beta, event risk, choppy tape, or tactical-only setup.
- "very_high": earnings today, extreme volatility, speculative biotech/space/high-beta names, or chasing risk.

Entry quality:
Use one of:
excellent, good_on_pullbacks, good_if_holds_gap, good_if_breadth_holds,
tactical_only, hedge_only, do_not_chase, avoid_chasing, conditional, null.

Avoid type:
- avoid_type="hard" for earnings-day hard avoid, analyst downgrade, major negative news, bearish/strong_bearish fundamentals, debt/credit warning, or severe gap-down risk.
- avoid_type="soft" for weak price action, stretched/chasing risk, needs confirmation, or tactical pullback-only setup.
- avoid_type=null when bias is buy or neutral.

For ETFs (SPY, QQQ, GLD, IWM), use index/sector/futures/pre-market context rather than company-specific news.

Use web_search efficiently for this batch. Prioritize:
1. earnings/guidance and earnings calendar,
2. analyst upgrades/downgrades/price target changes,
3. pre-market price action and volume,
4. company-specific news,
5. sector/macro context.

For symbols not mentioned in reliable current results, include them anyway with bias="neutral", confidence="low", and reason="no significant pre-market signals found".

Return ONLY this JSON schema. Every symbol in THIS batch must be present in the symbols object. Do not include symbols outside this batch.

{{
  "market_date": "{today}",
  "macro_sentiment": "risk-on | risk-off | mixed | neutral",
  "macro_summary": "one sentence on overall market context for today",
  "symbols": {{
    "AAPL": {{
      "bias": "buy | avoid | neutral",
      "reason": "one sentence",
      "confidence": "high | medium | low",
      "fundamental_score": "strong_bullish | bullish | neutral | bearish | strong_bearish | null",
      "risk_level": "low | medium | high | very_high | null",
      "entry_quality": "excellent | good_on_pullbacks | good_if_holds_gap | good_if_breadth_holds | tactical_only | hedge_only | do_not_chase | avoid_chasing | conditional | null",
      "avoid_type": "hard | soft | null"
    }}
  }}
}}"""


def call_claude_for_batch(today: str, batch_symbols: list[str], batch_num: int, total_batches: int) -> dict:
    system = (
        "You are a market research assistant for a risk-aware trading bot. "
        "Use web_search for current information. Respond ONLY with valid JSON."
    )
    user_prompt = build_prompt(today, batch_symbols, batch_num, total_batches)

    logger.info(
        f"Calling {MODEL} for batch {batch_num}/{total_batches}: "
        f"{', '.join(batch_symbols)} "
        f"(max_uses={WEB_SEARCH_TOOL['max_uses']}, timeout={TIMEOUT_SECONDS:.0f}s)"
    )

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=4000,
            system=system,
            tools=[WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": user_prompt}],
            timeout=TIMEOUT_SECONDS,
        ) as stream:
            streamed_chars = 0
            for chunk in stream.text_stream:
                streamed_chars += len(chunk)
            message = stream.get_final_message()
    except APITimeoutError:
        logger.error(f"Claude timeout on batch {batch_num}/{total_batches}")
        raise
    except Exception as e:
        logger.error(f"Claude call failed on batch {batch_num}/{total_batches}: {e}")
        raise

    raw = _extract_final_text(message)
    logger.info(
        f"Batch {batch_num}/{total_batches} complete: "
        f"{streamed_chars} streamed chars, {len(raw)} final chars, "
        f"stop_reason={message.stop_reason}"
    )

    return _parse_json_response(raw)


def choose_macro_sentiment(batch_results: list[dict]) -> str:
    values = []
    for result in batch_results:
        raw = str(result.get("macro_sentiment", "")).lower().strip().replace("_", "-")
        if raw in ("risk-on", "risk-off", "mixed", "neutral"):
            values.append(raw)

    if not values:
        return "neutral"

    # If any batch sees risk-off, respect that caution. Otherwise use majority.
    if "risk-off" in values:
        return "risk-off"

    counts = Counter(values)
    return counts.most_common(1)[0][0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Market date YYYY-MM-DD, default today")
    parser.add_argument(
        "--raw-output",
        help="Optional path to write raw research JSON before builder normalization",
    )
    parser.add_argument(
        "--build-output",
        help="Optional path to write normalized rich market context JSON using market_brief_builder",
    )
    args = parser.parse_args()

    started = datetime.now()
    today = args.date or date.today().isoformat()

    batches = list(_chunks(SYMBOLS, BATCH_SIZE))
    total_batches = len(batches)

    merged_symbols: dict[str, dict] = {}
    batch_results: list[dict] = []
    batch_errors: list[str] = []

    for idx, batch_symbols in enumerate(batches, start=1):
        try:
            result = call_claude_for_batch(today, batch_symbols, idx, total_batches)
            batch_results.append(result)

            raw_symbols = result.get("symbols") or {}
            extras = sorted(set(raw_symbols) - set(batch_symbols))
            missing = sorted(set(batch_symbols) - set(raw_symbols))

            if extras:
                logger.warning(f"Batch {idx}: ignoring symbols outside batch: {extras}")
            if missing:
                logger.warning(f"Batch {idx}: defaulting missing symbols: {missing}")

            for sym in batch_symbols:
                merged_symbols[sym] = _normalize_symbol_entry(raw_symbols.get(sym))

        except Exception as e:
            msg = f"batch {idx}/{total_batches} failed for {batch_symbols}: {e}"
            logger.error(msg)
            batch_errors.append(msg)

            # Fail safe for this batch instead of leaving symbols absent.
            for sym in batch_symbols:
                merged_symbols[sym] = _normalize_symbol_entry(None)

    macro_sentiment = choose_macro_sentiment(batch_results)
    macro_summaries = [
        str(r.get("macro_summary", "")).strip()
        for r in batch_results
        if str(r.get("macro_summary", "")).strip()
    ]

    if macro_summaries:
        macro_summary = " | ".join(macro_summaries[:3])
    else:
        macro_summary = "No macro summary available; using neutral defaults for missing context."

    # Final hard normalization to exactly approved universe.
    final_symbols = {}
    for sym in SYMBOLS:
        final_symbols[sym] = _normalize_symbol_entry(merged_symbols.get(sym))

    result = {
        "market_date": today,
        "generated_at": datetime.now().isoformat(),
        "macro_sentiment": macro_sentiment,
        "macro_summary": macro_summary[:1000],
        "symbols": final_symbols,
        "source": "pre_market_research",
        "format": "batched_normalized_approved_symbols",
        "batch_count": total_batches,
        "batch_size": BATCH_SIZE,
        "batch_errors": batch_errors,
    }

    try:
        OUTPUT_FILE.write_text(json.dumps(result, indent=2))
        logger.info(f"Wrote {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"Failed to write {OUTPUT_FILE}: {e}")
        sys.exit(2)

    if args.raw_output:
        try:
            write_raw_research(result, args.raw_output)
            logger.info(f"Wrote raw research output {args.raw_output}")
            print(f"  Raw output  : {args.raw_output}")
            print(f"  Raw summary : {raw_research_summary(result)}")
        except Exception as e:
            logger.error(f"Failed to write raw research output {args.raw_output}: {e}")
            sys.exit(2)

    if args.build_output:
        try:
            rich_context = build_market_brief(
                result,
                market_date=today,
                source="pre_market_research:builder",
            )
            write_market_context(rich_context, args.build_output)
            logger.info(f"Wrote built market context {args.build_output}")
            print(f"  Built output: {args.build_output}")
            print(f"  Built summary: {summary_for_brief(rich_context)}")
        except Exception as e:
            logger.error(f"Failed to build market context {args.build_output}: {e}")
            sys.exit(2)

    elapsed = (datetime.now() - started).total_seconds()
    syms = result.get("symbols", {})
    bias_counts = Counter((entry or {}).get("bias", "missing") for entry in syms.values())

    print()
    print("=== Pre-market research complete ===")
    print(f"  Date        : {today}")
    print(f"  Elapsed     : {elapsed:.1f}s")
    print(f"  Batches     : {total_batches}")
    print(f"  Batch errors: {len(batch_errors)}")
    print(f"  Macro       : {macro_sentiment}")
    print(f"  Bias counts : {dict(bias_counts)}")
    print(f"  Summary     : {macro_summary[:220]}")
    print()
    print(f"  {'Symbol':<7} {'Bias':<8} {'Conf':<7} {'Risk':<10} {'Entry':<22} Reason")
    print(f"  {'-'*7} {'-'*8} {'-'*7} {'-'*10} {'-'*22} {'-'*60}")
    for sym in SYMBOLS:
        s = syms.get(sym, {})
        print(
            f"  {sym:<7} "
            f"{s.get('bias', '-'):<8} "
            f"{s.get('confidence', '-'):<7} "
            f"{str(s.get('risk_level') or '-'):<10} "
            f"{str(s.get('entry_quality') or '-'):<22} "
            f"{(s.get('reason') or '')[:70]}"
        )
    print()
    print(f"  Output      : {OUTPUT_FILE}")

    if batch_errors:
        logger.warning("One or more research batches failed; output contains safe neutral defaults.")


if __name__ == "__main__":
    main()
