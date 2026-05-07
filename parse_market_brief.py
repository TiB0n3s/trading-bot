#!/usr/bin/env python3
"""
Parse a manually-pasted market brief (e.g. from Claude in Chrome) into
market_context.json — the same shape pre_market_research.py produces, so the
bot's _load_market_context() picks it up unchanged.

Usage:
    python parse_market_brief.py                          # read stdin
    python parse_market_brief.py path/to/brief.txt        # read file
    python parse_market_brief.py --date 2026-05-11 brief.txt
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "market_context.json"

SYMBOLS = ["AAPL", "SPY", "QQQ", "MSFT", "NVDA", "ORCL", "TSCO", "TSLA",
           "META", "AMD", "CVX", "XOM", "GOOGL", "GLD", "IWM"]

BIAS_SYNONYMS = {
    "buy":     ["buy", "bullish", "long", "positive"],
    "avoid":   ["avoid", "bearish", "short", "negative", "sell"],
    "neutral": ["neutral", "hold", "flat", "mixed"],
}
_SYNONYM_TO_CANONICAL = {syn: canon for canon, syns in BIAS_SYNONYMS.items() for syn in syns}
BIAS_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(s) for s in _SYNONYM_TO_CANONICAL) + r')\b',
    re.IGNORECASE,
)
SENTIMENT_PATTERN = re.compile(r'\b(risk[-\s]?on|risk[-\s]?off|mixed|neutral)\b', re.IGNORECASE)
PRIORITY_SUMMARY_PATTERN = re.compile(r'\b(risk[-\s]?on|risk[-\s]?off|bullish|bearish|sentiment)\b', re.IGNORECASE)
GENERIC_SUMMARY_PATTERN = re.compile(r'\b(futures|sentiment|market|macro|overall|outlook|fed|cpi)\b', re.IGNORECASE)


def next_trading_day(d):
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:  # 5=Sat, 6=Sun — skips weekends, ignores holidays
        nxt += timedelta(days=1)
    return nxt


def extract_symbol_entry(text, symbol):
    """Find the next bias keyword that follows this symbol in the text.

    Resilient to single-line tables (e.g. AAPL$287.51-0.10%BuyQ2 FY26 blowout...SPY$...)
    by searching forward from each occurrence of `symbol` and bounding the search by
    the next ticker, so a bias for SYMBOL never bleeds in from a neighbor's row.
    Iterates over all occurrences of the symbol — the first occurrence with a
    bias word in scope wins. This skips early prose mentions that don't carry a
    decision and lands on the per-symbol table entry.
    """
    sym_pattern = re.compile(rf'\b{re.escape(symbol)}\b')
    others_pattern = re.compile(
        r'\b(' + '|'.join(re.escape(s) for s in SYMBOLS if s != symbol) + r')\b'
    )
    for m_sym in sym_pattern.finditer(text):
        window = text[m_sym.end() : m_sym.end() + 1500]
        nxt = others_pattern.search(window)
        scope = window[: nxt.start()] if nxt else window
        bm = BIAS_PATTERN.search(scope)
        if not bm:
            continue
        matched_word = bm.group(1).lower()
        bias = _SYNONYM_TO_CANONICAL[matched_word]
        reason_raw = scope[bm.end():]
        cleaned = reason_raw.replace('|', ' ')
        cleaned = re.sub(r'^[\s\-—:|.,#*$%+0-9]+', '', cleaned)
        cleaned = re.sub(r'[\s\-—:|.,]+$', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return {
            "bias": bias,
            "reason": cleaned or "no detail provided",
            "confidence": "medium",
        }
    return None


def extract_macro_sentiment(text):
    """Find a risk-on / risk-off / mixed / neutral mention on a line that isn't a symbol row."""
    for line in text.splitlines():
        if any(re.search(rf'\b{s}\b', line) for s in SYMBOLS):
            continue
        m = SENTIMENT_PATTERN.search(line)
        if m:
            normalized = m.group(1).lower().replace(' ', '-')
            if normalized in ('risk-on', 'risk-off', 'mixed', 'neutral'):
                return normalized
    return "neutral"


def extract_macro_summary(text):
    """Pick a macro summary line.

    Two-tier preference: lines mentioning 'risk-on/off', 'bullish/bearish', or
    'sentiment' win immediately over generic 'market'/'macro'/'overall'/etc.
    For paragraph-style lines longer than the cap, take just the first sentence
    so a sentiment statement embedded in a long paragraph still qualifies.
    The symbol-skip check is applied to the extracted snippet, not the whole
    line — so a sentiment paragraph that mentions specific tickers later on
    still has its lead sentence considered.
    """
    candidates = []
    for line in text.splitlines():
        cleaned = re.sub(r'[#*_`>]', '', line).strip()
        if not cleaned:
            continue
        snippet = re.split(r'(?<=[.!?])\s+', cleaned, maxsplit=1)[0]
        if any(re.search(rf'\b{s}\b', snippet) for s in SYMBOLS):
            continue
        if not (30 <= len(snippet) <= 300):
            continue
        if PRIORITY_SUMMARY_PATTERN.search(snippet):
            return snippet
        if GENERIC_SUMMARY_PATTERN.search(snippet):
            candidates.append(snippet)
    if candidates:
        return candidates[0]
    return "no macro summary provided"


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('input', nargs='?', help='Path to text file (omit to read stdin)')
    parser.add_argument('--date', help='Override market_date (YYYY-MM-DD). Default = next trading day.')
    args = parser.parse_args()

    if args.input:
        text = Path(args.input).read_text()
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("ERROR: no input text provided (stdin was empty and no file path given)", file=sys.stderr)
        sys.exit(1)

    if args.date:
        try:
            datetime.strptime(args.date, '%Y-%m-%d')
        except ValueError:
            print(f"ERROR: --date must be YYYY-MM-DD (got {args.date!r})", file=sys.stderr)
            sys.exit(1)
        market_date = args.date
    else:
        market_date = next_trading_day(date.today()).isoformat()

    symbols_out = {}
    parsed_count = 0
    for sym in SYMBOLS:
        entry = extract_symbol_entry(text, sym)
        if entry:
            symbols_out[sym] = entry
            parsed_count += 1
        else:
            symbols_out[sym] = {
                "bias": "neutral",
                "reason": "no signals found",
                "confidence": "low",
            }

    output = {
        "market_date": market_date,
        "generated_at": datetime.now().isoformat(timespec='seconds'),
        "macro_sentiment": extract_macro_sentiment(text),
        "macro_summary": extract_macro_summary(text),
        "symbols": symbols_out,
        "source": "manual_chrome_analysis",
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    print("=== Manual market brief parsed ===")
    print(f"  Market date     : {market_date}")
    print(f"  Macro sentiment : {output['macro_sentiment']}")
    print(f"  Macro summary   : {output['macro_summary'][:90]}")
    print(f"  Parsed symbols  : {parsed_count}/{len(SYMBOLS)} (rest defaulted to neutral/low)")
    print(f"  Output          : {OUTPUT_FILE}")
    print()
    print(f"  {'Symbol':<7} {'Bias':<8} {'Conf':<7}  Reason")
    print(f"  {'-'*7} {'-'*8} {'-'*7}  {'-'*60}")
    for sym in SYMBOLS:
        e = symbols_out[sym]
        reason = (e['reason'] or '')[:60]
        print(f"  {sym:<7} {e['bias']:<8} {e['confidence']:<7}  {reason}")


if __name__ == "__main__":
    main()
