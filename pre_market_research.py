#!/usr/bin/env python3
"""
Pre-market research — single Claude Sonnet 4.6 call with web_search.

Researches all approved symbols in one shot and produces a per-symbol trading
bias (buy / avoid / neutral) plus a macro sentiment line. Writes the result to
market_context.json next to this file.
"""
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "market_context.json"
ENV_FILE = Path("/etc/trading-bot.env")

SYMBOLS = APPROVED_SYMBOLS_LIST

MODEL = "claude-sonnet-4-6"
TIMEOUT_SECONDS = 120.0
WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 6,
}

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


def build_prompt(today: str) -> str:
    symbols_csv = ", ".join(SYMBOLS)
    return f"""Respond with JSON only. No preamble, no explanation, no markdown fences.

Today is {today}. Use web_search to research US pre-market activity and assign a trading bias for today's session for each of these {len(SYMBOLS)} tickers:

Bias rules — apply consistently:
- "avoid":   earnings reported today, recent analyst downgrade, major negative news, pre-market down more than 1%, debt or credit warning
- "buy":     strong pre-market move up, recent analyst upgrade, positive earnings beat, clear sector tailwind
- "neutral": no significant news, flat pre-market, mixed signals

Confidence:
- "high":   clear directional signal with multiple supporting datapoints
- "medium": one or two supporting datapoints
- "low":    sparse data or conflicting signals

For ETFs (SPY, QQQ, GLD, IWM), use sector or index-level news and pre-market index moves rather than company-specific items.

Search efficiently. You have a hard budget of 6 web searches total — DO NOT search per-symbol. Use exactly these 3 broad searches to cover all symbols:
1. "pre-market movers today" — gives pre-market direction and magnitude for the most active names
2. "earnings calendar today" — identifies which symbols report today (drives the "avoid" rule)
3. "analyst upgrades downgrades today" — recent rating changes that affect bias
Synthesize the per-symbol output by attributing what each search reveals. For symbols not mentioned in any search result, default to bias "neutral" with confidence "low" and a reason like "no significant pre-market signals found".

Return ONLY this JSON schema. All {len(SYMBOLS)} symbols must be present in the "symbols" object:
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
      "entry_quality": "excellent | good_on_pullbacks | good_if_holds_gap | good_if_breadth_holds | tactical_only | hedge_only | do_not_chase | avoid_chasing | conditional | null"
    }}
  }}
}}"""


def main():
    started = datetime.now()
    today = date.today().isoformat()

    system = (
        "You are a market research assistant. Use web_search to gather current information. "
        "Respond ONLY with valid JSON matching the requested schema."
    )
    user_prompt = build_prompt(today)

    logger.info(
        f"Calling {MODEL} with web_search "
        f"(max_uses={WEB_SEARCH_TOOL['max_uses']}, timeout={TIMEOUT_SECONDS:.0f}s) ..."
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
        logger.error(
            f"Claude stream idle timeout (no chunks for {TIMEOUT_SECONDS:.0f}s) — exiting"
        )
        sys.exit(2)
    except Exception as e:
        logger.error(f"Claude call failed: {e}")
        sys.exit(2)

    raw = _extract_final_text(message)
    logger.info(
        f"Stream complete: {streamed_chars} text chars streamed, "
        f"{len(raw)} final chars, stop_reason={message.stop_reason}"
    )

    try:
        result = _parse_json_response(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e} | raw[:500]={raw[:500]!r}")
        sys.exit(2)

    if "symbols" not in result:
        logger.error(f"Response missing 'symbols' key: {result}")
        sys.exit(2)

    try:
        OUTPUT_FILE.write_text(json.dumps(result, indent=2))
        logger.info(f"Wrote {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"Failed to write {OUTPUT_FILE}: {e}")
        sys.exit(2)

    elapsed = (datetime.now() - started).total_seconds()
    syms = result.get("symbols", {})
    macro = result.get("macro_sentiment", "unknown")
    summary = result.get("macro_summary", "")
    missing = [s for s in SYMBOLS if s not in syms]

    print()
    print("=== Pre-market research complete ===")
    print(f"  Date    : {today}")
    print(f"  Elapsed : {elapsed:.1f}s")
    print(f"  Macro   : {macro}")
    print(f"  Summary : {summary}")
    if missing:
        print(f"  Missing : {missing}")
    print()
    print(f"  {'Symbol':<7} {'Bias':<8} {'Conf':<7}  Reason")
    print(f"  {'-'*7} {'-'*8} {'-'*7}  {'-'*60}")
    for sym in SYMBOLS:
        s = syms.get(sym, {})
        bias = s.get("bias", "-")
        conf = s.get("confidence", "-")
        reason = (s.get("reason") or "")[:70]
        print(f"  {sym:<7} {bias:<8} {conf:<7}  {reason}")
    print()
    print(f"  Output  : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
