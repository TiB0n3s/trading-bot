#!/usr/bin/env python3
"""
Fundamental research — deep per-symbol analysis via Claude Sonnet 4.6 with web_search.

Researches the 15 approved symbols in two streaming batches (8 + 7) and produces
a per-symbol fundamental score (strong_bullish / bullish / neutral / bearish /
strong_bearish) plus business model, financials, recent earnings, analyst
consensus, and a one-sentence reason.

Writes the combined result to fundamental_analysis.json next to this file.
Designed to run weekly (Monday morning cron).
"""
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "fundamental_analysis.json"
ENV_FILE = Path("/etc/trading-bot.env")

SYMBOLS = ["AAPL", "SPY", "QQQ", "MSFT", "NVDA", "ORCL", "TSCO", "TSLA",
           "META", "AMD", "CVX", "XOM", "GOOGL", "GLD", "IWM"]

MODEL = "claude-sonnet-4-6"
TIMEOUT_SECONDS = 180.0
WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 5,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("fundamental_research")


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


def build_prompt(today, batch):
    symbols_csv = ", ".join(batch)
    return f"""Respond with JSON only. No preamble, no explanation, no markdown fences.

Today is {today}. Produce a fundamental analysis for each of the following {len(batch)} US stocks/ETFs: {symbols_csv}.

For each symbol, use web_search to gather and assess these fields. Prioritize accuracy on the four MOST IMPACTFUL fields — fundamental_score, q1_earnings beat/miss, debt_level, demand_outlook. The remaining fields are supporting context — fill them in based on what your broad searches reveal plus established knowledge about each company; do not burn search budget chasing them.

- Business model: how the company makes money (one sentence)
- Demand outlook: strong/moderate/weak with brief reason  [HIGH PRIORITY]
- Historical performance over the past 3–5 years
- Management quality: strong/adequate/weak
- Growth outlook: high/moderate/low
- Profitability: high/moderate/low
- Debt level: low/moderate/high, plus debt-to-equity ratio (number)  [HIGH PRIORITY]
- Liquidity: strong/adequate/weak, plus current ratio (number)
- Q1 2026 earnings: beat/miss/inline, EPS surprise %, revenue surprise %, forward guidance summary  [HIGH PRIORITY]
- Q2 2026 projection: consensus EPS estimate (number), analyst consensus (buy/hold/sell), avg price target (number)
- Fundamental score: strong_bullish / bullish / neutral / bearish / strong_bearish, with one-sentence reason  [HIGH PRIORITY]

ETF handling (SPY, QQQ, GLD, IWM): substitute index/sector context. Use the underlying index or commodity exposure for "business_model" (e.g. "S&P 500 broad-market exposure via SPDR ETF wrapper"). For company-specific fields that don't apply (q1_earnings sub-fields, debt_to_equity, current_ratio, eps_estimate), use null. The fundamental_score should reflect the broad outlook for the underlying index/asset.

Search efficiently — you have a hard budget of 5 web searches total. DO NOT search per-symbol. Use BROAD multi-symbol/multi-topic searches like:
- "Q1 2026 earnings results mega-cap tech" (covers AAPL, MSFT, NVDA, META, GOOGL, AMD, ORCL)
- "Q1 2026 earnings energy sector" (covers CVX, XOM)
- "Q1 2026 retail consumer earnings" (covers TSCO, TSLA delivery)
- "S&P 500 outlook 2026 analyst targets" (covers SPY, QQQ, IWM via correlation)
- "gold outlook 2026" or "commodity outlook 2026" (covers GLD)
Synthesize all 15 symbols from these few broad searches; for any non-impact field where data isn't surfaced, use a reasonable default (e.g. "moderate", "adequate") rather than burning a search.

Return ONLY this JSON schema. All {len(batch)} symbols must be present as top-level keys:
{{
  "{batch[0]}": {{
    "business_model": "one sentence",
    "demand_outlook": "strong | moderate | weak — one sentence",
    "historical_performance": "one sentence 3-5 year summary",
    "management_quality": "strong | adequate | weak — one sentence",
    "growth_outlook": "high | moderate | low",
    "profitability": "high | moderate | low",
    "debt_level": "low | moderate | high",
    "debt_to_equity": 1.8,
    "liquidity": "strong | adequate | weak",
    "current_ratio": 1.07,
    "q1_earnings": {{"beat_miss": "beat | miss | inline", "eps_surprise_pct": 7.2, "revenue_surprise_pct": 1.4, "guidance": "one sentence"}},
    "q2_projection": {{"eps_estimate": 1.48, "analyst_consensus": "buy | hold | sell", "price_target_avg": 245}},
    "fundamental_score": "strong_bullish | bullish | neutral | bearish | strong_bearish",
    "score_reason": "one sentence"
  }},
  ... one entry per symbol in {batch}
}}"""


def research_batch(batch, today):
    label = f"batch[{','.join(batch)}]"
    system = (
        "You are a fundamental research analyst. Use web_search to gather current information for each ticker. "
        "Respond ONLY with valid JSON matching the requested schema."
    )
    user_prompt = build_prompt(today, batch)

    logger.info(
        f"[{label}] calling {MODEL} with web_search "
        f"(max_uses={WEB_SEARCH_TOOL['max_uses']}, idle_timeout={TIMEOUT_SECONDS:.0f}s) ..."
    )

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=4096,
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
        logger.error(f"[{label}] stream idle timeout (no chunks for {TIMEOUT_SECONDS:.0f}s)")
        return None
    except Exception as e:
        logger.error(f"[{label}] call failed: {e}")
        return None

    raw = _extract_final_text(message)
    logger.info(
        f"[{label}] {streamed_chars} text chars streamed, "
        f"{len(raw)} final chars, stop_reason={message.stop_reason}"
    )

    try:
        return _parse_json_response(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[{label}] JSON parse failed: {e} | raw[:500]={raw[:500]!r}")
        return None


def main():
    started = datetime.now()
    today = date.today().isoformat()
    errors = []

    result = research_batch(SYMBOLS, today)
    if result is None:
        errors.append("single-call research failed")
        all_symbols = {s: None for s in SYMBOLS}
    else:
        all_symbols = {}
        for s in SYMBOLS:
            all_symbols[s] = result.get(s)
            if all_symbols[s] is None:
                errors.append(f"symbol {s} missing from response")

    output = {
        "research_date": today,
        "generated_at": started.isoformat(timespec="seconds"),
        "symbols": all_symbols,
        "errors": errors,
    }

    try:
        OUTPUT_FILE.write_text(json.dumps(output, indent=2))
        logger.info(f"Wrote {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"Failed to write {OUTPUT_FILE}: {e}")
        sys.exit(2)

    elapsed = (datetime.now() - started).total_seconds()
    all_syms = SYMBOLS
    researched = sum(1 for v in all_symbols.values() if v is not None)

    print()
    print("=== Fundamental research complete ===")
    print(f"  Date    : {today}")
    print(f"  Elapsed : {elapsed:.1f}s")
    print(f"  Symbols : {researched}/{len(all_syms)} researched")
    print(f"  Errors  : {len(errors)}")
    for e in errors:
        print(f"    - {e}")
    print()
    print(f"  {'Symbol':<7} {'Score':<16}  Reason")
    print(f"  {'-'*7} {'-'*16}  {'-'*60}")
    for sym in all_syms:
        s = all_symbols.get(sym) or {}
        score = s.get("fundamental_score", "-")
        reason = (s.get("score_reason") or "")[:70]
        print(f"  {sym:<7} {score:<16}  {reason}")
    print()
    print(f"  Output  : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
