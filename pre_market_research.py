#!/usr/bin/env python3
"""
Pre-market research — robust batched Claude/web_search runner.

Design goals:
- A stuck Claude/web_search batch cannot hang the whole job.
- Each Claude batch runs in a child process and is killed on timeout.
- One retry max by default.
- Failed batches default only their symbols to conservative neutral entries.
- --template-fallback can turn fatal/interrupt paths into full conservative output.
- --build-output /tmp/... never overwrites live market_context.json.
- Production market_context.json is only written when --build-output is omitted
  or explicitly points to market_context.json.
"""

import argparse
import json
import logging
import multiprocessing as mp
import os
import sys
import time
import traceback
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST
from market_intelligence.raw_research_template import build_template
from market_intelligence.research_output import raw_research_summary
from market_intelligence.market_brief_builder import (
    build_market_brief,
    write_market_context,
    summary_for_brief,
)

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "market_context.json"
ENV_FILE = Path("/etc/trading-bot.env")
BATCH_LOG_DIR = SCRIPT_DIR / "logs" / "research_batches"

SYMBOLS = APPROVED_SYMBOLS_LIST

DEFAULT_MODEL = os.getenv("PRE_MARKET_MODEL", "claude-sonnet-4-6")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("PRE_MARKET_TIMEOUT_SECONDS", "75"))
DEFAULT_BATCH_SIZE = int(os.getenv("PRE_MARKET_BATCH_SIZE", "6"))
DEFAULT_WEB_SEARCH_MAX_USES = int(os.getenv("PRE_MARKET_WEB_SEARCH_MAX_USES", "2"))
DEFAULT_MAX_TOKENS = int(os.getenv("PRE_MARKET_MAX_TOKENS", "2500"))
DEFAULT_BATCH_RETRIES = int(os.getenv("PRE_MARKET_BATCH_RETRIES", "1"))

VALID_BIAS = {"buy", "avoid", "neutral"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_FUNDAMENTAL = {"strong_bullish", "bullish", "neutral", "bearish", "strong_bearish"}
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("pre_market_research")


def _load_env_if_needed():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return

    if not ENV_FILE.exists():
        logger.error(f"ANTHROPIC_API_KEY not set and {ENV_FILE} not found")
        sys.exit(1)

    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    logger.info(f"Loaded env from {ENV_FILE}")


def _chunks(items, size):
    if size <= 0:
        raise ValueError("--batch-size must be > 0")
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _clean_enum(value, valid_values, default=None):
    if value is None:
        return default
    normalized = str(value).lower().strip().replace(" ", "_").replace("-", "_")
    return normalized if normalized in valid_values else default


def _normalize_symbol_entry(entry):
    entry = entry or {}

    bias = _clean_enum(entry.get("bias"), VALID_BIAS, "neutral")
    confidence = _clean_enum(entry.get("confidence"), VALID_CONFIDENCE, "low")
    fundamental_score = _clean_enum(entry.get("fundamental_score"), VALID_FUNDAMENTAL, None)
    risk_level = _clean_enum(entry.get("risk_level"), VALID_RISK, "medium")
    entry_quality = _clean_enum(entry.get("entry_quality"), VALID_ENTRY_QUALITY, "conditional")
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


def _fallback_symbol(reason="Research pending."):
    return {
        "bias": "neutral",
        "reason": reason,
        "confidence": "low",
        "fundamental_score": "neutral",
        "risk_level": "medium",
        "entry_quality": "conditional",
        "avoid_type": None,
    }


def _extract_final_text(message):
    parts = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def _parse_json_response(raw):
    cleaned = raw.strip()
    cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    candidates = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if candidates:
        cleaned = cleaned[min(candidates):]
    return json.loads(cleaned)


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def _batch_log_path(today, batch_num, suffix):
    BATCH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return BATCH_LOG_DIR / f"{today}_batch_{batch_num:02d}_{suffix}.json"


def _should_write_production_context(build_output):
    if not build_output:
        return True
    requested = Path(build_output)
    if not requested.is_absolute():
        requested = SCRIPT_DIR / requested
    return requested.resolve() == OUTPUT_FILE.resolve()


def _backup_live_context():
    if not OUTPUT_FILE.exists():
        return None
    backup = OUTPUT_FILE.with_name(
        f"{OUTPUT_FILE.name}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    backup.write_text(OUTPUT_FILE.read_text())
    return backup


def build_prompt(today, batch_symbols, batch_num, total_batches):
    batch_csv = ", ".join(batch_symbols)
    approved_csv = ", ".join(SYMBOLS)

    return f"""Respond with JSON only. No preamble, no explanation, no markdown fences.

Today is {today}. This is batch {batch_num} of {total_batches} for my approved trading-bot universe.

Approved universe:
{approved_csv}

For THIS batch only, research these symbols:
{batch_csv}

Bias rules:
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
- "hard" for earnings-day hard avoid, downgrade, major negative news, bearish fundamentals, credit warning, or severe gap-down risk.
- "soft" for weak price action, stretched/chasing risk, needs confirmation, or tactical pullback-only setup.
- null when bias is buy or neutral.

For ETFs SPY, QQQ, GLD, IWM, use index/sector/futures/pre-market context.

Use web_search efficiently. Prioritize earnings/guidance, analyst actions, pre-market price action/volume, company news, sector/macro context.

For symbols not mentioned in reliable current results, include them with bias="neutral", confidence="low", and reason="no significant pre-market signals found".

Return ONLY this JSON schema. Every symbol in THIS batch must be present. Do not include symbols outside this batch.

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


def _child_claude_call(queue, cfg):
    """Runs in a child process. Parent can terminate this process on timeout."""
    try:
        from anthropic import Anthropic

        client = Anthropic(max_retries=0)
        tool = {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": cfg["max_web_uses"],
        }

        system = (
            "You are a market research assistant for a risk-aware trading bot. "
            "Use web_search for current information. Respond ONLY with valid JSON."
        )

        if cfg["stream"]:
            with client.messages.stream(
                model=cfg["model"],
                max_tokens=cfg["max_tokens"],
                system=system,
                tools=[tool],
                messages=[{"role": "user", "content": cfg["prompt"]}],
                timeout=max(5.0, cfg["timeout"] - 5.0),
            ) as stream:
                streamed_chars = 0
                for chunk in stream.text_stream:
                    streamed_chars += len(chunk)
                message = stream.get_final_message()
        else:
            streamed_chars = 0
            message = client.messages.create(
                model=cfg["model"],
                max_tokens=cfg["max_tokens"],
                system=system,
                tools=[tool],
                messages=[{"role": "user", "content": cfg["prompt"]}],
                timeout=max(5.0, cfg["timeout"] - 5.0),
            )

        raw = _extract_final_text(message)
        parsed = _parse_json_response(raw)
        queue.put(
            {
                "ok": True,
                "raw": raw,
                "parsed": parsed,
                "streamed_chars": streamed_chars,
                "stop_reason": getattr(message, "stop_reason", None),
            }
        )
    except Exception as e:
        queue.put(
            {
                "ok": False,
                "error": repr(e),
                "traceback": traceback.format_exc(),
            }
        )


def call_claude_for_batch(args, today, batch_symbols, batch_num, total_batches):
    prompt = build_prompt(today, batch_symbols, batch_num, total_batches)
    mode = "stream" if args.stream else "non-stream"

    logger.info(
        f"Calling {args.model} for batch {batch_num}/{total_batches}: "
        f"{', '.join(batch_symbols)} "
        f"(mode={mode}, max_uses={args.max_web_uses}, timeout={args.timeout:.0f}s, "
        f"max_tokens={args.max_tokens})"
    )

    started = time.monotonic()
    ctx = mp.get_context("fork")
    queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(
        target=_child_claude_call,
        args=(
            queue,
            {
                "model": args.model,
                "max_tokens": args.max_tokens,
                "max_web_uses": args.max_web_uses,
                "timeout": args.timeout,
                "stream": args.stream,
                "prompt": prompt,
            },
        ),
    )

    proc.start()
    proc.join(args.timeout)

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        elapsed = time.monotonic() - started
        raise TimeoutError(
            f"batch {batch_num}/{total_batches} exceeded hard timeout "
            f"{args.timeout:.0f}s after {elapsed:.1f}s"
        )

    if queue.empty():
        raise RuntimeError(f"batch {batch_num}/{total_batches} exited without a result")

    result = queue.get()
    elapsed = time.monotonic() - started

    if not result.get("ok"):
        raise RuntimeError(
            f"batch {batch_num}/{total_batches} Claude error after {elapsed:.1f}s: "
            f"{result.get('error')}\n{result.get('traceback')}"
        )

    raw = result["raw"]
    parsed = result["parsed"]

    raw_path = _batch_log_path(today, batch_num, "raw")
    parsed_path = _batch_log_path(today, batch_num, "parsed")
    raw_path.write_text(raw)
    parsed_path.write_text(json.dumps(parsed, indent=2))

    logger.info(
        f"Batch {batch_num}/{total_batches} complete in {elapsed:.1f}s: "
        f"{result.get('streamed_chars', 0)} streamed chars, {len(raw)} final chars, "
        f"stop_reason={result.get('stop_reason')}; saved {raw_path}"
    )

    return parsed


def choose_macro_sentiment(batch_results):
    values = []
    for result in batch_results:
        raw = str(result.get("macro_sentiment", "")).lower().strip().replace("_", "-")
        if raw in ("risk-on", "risk-off", "mixed", "neutral"):
            values.append(raw)

    if not values:
        return "mixed"
    if "risk-off" in values:
        return "risk-off"

    return Counter(values).most_common(1)[0][0]


def _fallback_result(today, reason):
    logger.warning(f"Using conservative research fallback: {reason}")
    fallback = build_template(today)
    fallback["source"] = "pre_market_research_template_fallback"
    fallback["fallback_reason"] = reason
    fallback["macro_summary"] = (
        "Conservative template fallback generated because automated Claude research "
        f"did not complete: {reason}"
    )
    return fallback


def _merge_batch_result(batch_symbols, result_batch):
    raw_symbols = result_batch.get("symbols") or {}
    extras = sorted(set(raw_symbols) - set(batch_symbols))
    missing = sorted(set(batch_symbols) - set(raw_symbols))

    if extras:
        logger.warning(f"Ignoring symbols outside batch: {extras}")
    if missing:
        logger.warning(f"Defaulting missing symbols: {missing}")

    merged = {}
    for sym in batch_symbols:
        merged[sym] = _normalize_symbol_entry(raw_symbols.get(sym))
    return merged


def _print_summary(result, brief, args, started, total_batches, batch_errors, raw_path, built_path, production_written):
    elapsed = (datetime.now() - started).total_seconds()
    syms = result.get("symbols", {})
    bias_counts = Counter((e or {}).get("bias", "missing") for e in syms.values())
    built_summary = summary_for_brief(brief) if brief else None

    print()
    print("=== Pre-market research complete ===")
    print(f"  Date        : {result.get('market_date')}")
    print(f"  Elapsed     : {elapsed:.1f}s")
    print(f"  Batches     : {total_batches}")
    print(f"  Batch errors: {len(batch_errors)}")
    print(f"  Macro       : {result.get('macro_sentiment')}")
    print(f"  Bias counts : {dict(bias_counts)}")
    print(f"  Summary     : {result.get('macro_summary')}")
    if raw_path:
        print(f"  Raw output  : {raw_path}")
        print(f"  Raw summary : {raw_research_summary(result)}")
    if built_path:
        print(f"  Built output: {built_path}")
        print(f"  Built summary: {built_summary}")
    print(f"  Live output : {OUTPUT_FILE if production_written else '(not modified)'}")
    print()
    print(f"  {'Symbol':<7} {'Bias':<8} {'Conf':<7} {'Risk':<10} {'Entry':<22} Reason")
    print(f"  {'-'*7} {'-'*8} {'-'*7} {'-'*10} {'-'*22} {'-'*60}")
    for sym in SYMBOLS:
        e = syms.get(sym, {})
        print(
            f"  {sym:<7} "
            f"{e.get('bias', '-'):<8} "
            f"{e.get('confidence', '-'):<7} "
            f"{str(e.get('risk_level') or '-'):<10} "
            f"{str(e.get('entry_quality') or '-'):<22} "
            f"{(e.get('reason') or '')[:80]}"
        )

    if batch_errors:
        print()
        print("  Batch errors:")
        for err in batch_errors:
            print(f"   - {err}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Market date YYYY-MM-DD, default today")
    parser.add_argument("--raw-output", help="Optional path to write raw research JSON")
    parser.add_argument("--build-output", help="Optional path to write normalized rich market context JSON")
    parser.add_argument("--template-fallback", action="store_true", help="Fallback to conservative template on fatal/interrupt path")
    parser.add_argument("--skip-claude", action="store_true", help="Skip Claude/web research and generate conservative template")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Hard per-batch timeout seconds")
    parser.add_argument("--max-web-uses", type=int, default=DEFAULT_WEB_SEARCH_MAX_USES, help="web_search max_uses per batch")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Claude model name")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Symbols per Claude batch")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="Claude max output tokens per batch")
    parser.add_argument("--retries", type=int, default=DEFAULT_BATCH_RETRIES, help="Retries per failed batch")
    parser.add_argument("--stream", action="store_true", help="Use streaming mode. Default is non-streaming.")
    parser.add_argument("--no-stream", action="store_true", help="Accepted for compatibility; non-streaming is already default.")
    return parser.parse_args()


def main():
    _load_env_if_needed()
    args = parse_args()

    if args.timeout <= 0:
        raise SystemExit("ERROR: --timeout must be > 0")
    if args.batch_size <= 0:
        raise SystemExit("ERROR: --batch-size must be > 0")
    if args.max_web_uses < 0:
        raise SystemExit("ERROR: --max-web-uses must be >= 0")
    if args.retries < 0:
        raise SystemExit("ERROR: --retries must be >= 0")

    started = datetime.now()
    today = args.date or date.today().isoformat()

    batch_results = []
    batch_errors = []
    total_batches = 0

    try:
        if args.skip_claude:
            result = _fallback_result(today, "--skip-claude requested")
        else:
            batches = list(_chunks(SYMBOLS, args.batch_size))
            total_batches = len(batches)
            merged_symbols = {}

            for idx, batch_symbols in enumerate(batches, start=1):
                result_batch = None
                last_error = None

                for attempt in range(args.retries + 1):
                    try:
                        if attempt:
                            logger.warning(
                                f"Retrying batch {idx}/{total_batches}; "
                                f"attempt {attempt + 1}/{args.retries + 1}"
                            )
                        result_batch = call_claude_for_batch(args, today, batch_symbols, idx, total_batches)
                        break
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        last_error = e
                        logger.error(f"Batch {idx}/{total_batches} attempt {attempt + 1} failed: {e}")

                if result_batch is None:
                    msg = f"batch {idx}/{total_batches} failed for {batch_symbols}: {last_error}"
                    batch_errors.append(msg)
                    logger.error(msg)
                    for sym in batch_symbols:
                        merged_symbols[sym] = _fallback_symbol("Research pending.")
                    continue

                batch_results.append(result_batch)
                merged_symbols.update(_merge_batch_result(batch_symbols, result_batch))

            macro_sentiment = choose_macro_sentiment(batch_results)
            macro_summaries = [
                str(r.get("macro_summary", "")).strip()
                for r in batch_results
                if str(r.get("macro_summary", "")).strip()
            ]
            macro_summary = macro_summaries[0] if macro_summaries else "Batched automated research completed."

            result = {
                "market_date": today,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "macro_sentiment": macro_sentiment,
                "macro_regime": "caution" if macro_sentiment in ("mixed", "neutral") else (
                    "defensive" if macro_sentiment == "risk-off" else "risk_on"
                ),
                "macro_summary": macro_summary,
                "symbols": {sym: merged_symbols.get(sym, _fallback_symbol()) for sym in SYMBOLS},
                "source": "pre_market_research_claude_web_search_batched",
                "format": "raw_research_v1",
                "batch_errors": batch_errors,
            }

    except KeyboardInterrupt:
        if not args.template_fallback:
            raise
        result = _fallback_result(today, "KeyboardInterrupt during Claude research")
        batch_errors.append("KeyboardInterrupt during Claude research")

    except Exception as e:
        if not args.template_fallback:
            raise
        result = _fallback_result(today, f"fatal error: {e}")
        batch_errors.append(f"fatal error: {e}")

    raw_path = None
    if args.raw_output:
        raw_path = _write_json(args.raw_output, result)
        logger.info(f"Wrote raw research output {raw_path}")

    brief = build_market_brief(result)

    built_path = None
    if args.build_output:
        built_path = Path(args.build_output)
        if not built_path.is_absolute():
            built_path = SCRIPT_DIR / built_path
        built_path.parent.mkdir(parents=True, exist_ok=True)
        write_market_context(brief, built_path)
        logger.info(f"Wrote built market context {built_path}")

    production_written = False
    if _should_write_production_context(args.build_output):
        backup = _backup_live_context()
        if backup:
            logger.info(f"Backed up existing live context to {backup}")
        write_market_context(brief, OUTPUT_FILE)
        logger.info(f"Wrote live market context {OUTPUT_FILE}")
        production_written = True
    else:
        logger.info(
            f"Skipped live {OUTPUT_FILE} write because --build-output targets {args.build_output}"
        )

    _print_summary(result, brief, args, started, total_batches, batch_errors, raw_path, built_path, production_written)

    if batch_errors:
        logger.warning("One or more research batches failed; output contains safe neutral defaults or fallback")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
