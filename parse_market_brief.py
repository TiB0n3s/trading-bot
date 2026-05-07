#!/usr/bin/env python3
"""
Parse a manually-pasted market brief (e.g. from Claude in Chrome) into
market_context.json — the same shape pre_market_research.py produces, so the
bot's _load_market_context() picks it up unchanged.

Two input formats are accepted:
  1. JSON brief with structured per-symbol fields (preferred — most reliable):
     {"macro_summary": {...}, "symbols": [{"symbol": "AAPL", "trading_bias":
     "neutral", "fundamental_score": "bullish", "reason": "...", ...}, ...]}
  2. Free-text/table brief: regex-extracts bias keywords adjacent to ticker
     symbols (best-effort heuristic for prose or dense table dumps).
The format is auto-detected: input starting with `{` or `[` goes through the
JSON path; everything else goes through the regex path.

Output schema:
{
  "market_date":      "YYYY-MM-DD",
  "generated_at":     ISO timestamp,
  "macro_sentiment":  "risk-on" | "risk-off" | "mixed" | "neutral",
  "macro_summary":    "<one-sentence>",
  "symbols": {
    "AAPL": {
      "bias":              "buy" | "avoid" | "neutral",
      "reason":            "<brief reason or 'no signals found'>",
      "confidence":        "high" | "medium" | "low",
      "fundamental_score": "strong_bullish" | "bullish" | "neutral" |
                           "bearish" | "strong_bearish" | null,
    },
    ... one entry per approved symbol
  },
  "source": "manual_chrome_analysis"
}

The bot's _load_market_context() consumes bias / reason / confidence today.
fundamental_score is added for downstream wiring (e.g. a future fundamental gate
or an extra account_state injection for Claude).

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
_BIAS_FORMS = [s for s in _SYNONYM_TO_CANONICAL] + [s.title() for s in _SYNONYM_TO_CANONICAL]
BIAS_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(s) for s in _BIAS_FORMS) + r')(?![a-z])',
)

FUNDAMENTAL_SYNONYMS = {
    "strong_bullish": ["strong_bullish", "strong bullish"],
    "bullish":        ["bullish"],
    "neutral":        ["neutral"],
    "bearish":        ["bearish"],
    "strong_bearish": ["strong_bearish", "strong bearish"],
}
_FUNDAMENTAL_TO_CANONICAL = {syn: canon for canon, syns in FUNDAMENTAL_SYNONYMS.items() for syn in syns}
# Build pattern forms (lowercase + Title), longest first so 'strong bullish' beats 'bullish'
_FUNDAMENTAL_FORMS = []
for syn in _FUNDAMENTAL_TO_CANONICAL:
    _FUNDAMENTAL_FORMS.append(syn)
    _FUNDAMENTAL_FORMS.append(syn.title())
_FUNDAMENTAL_FORMS = sorted(set(_FUNDAMENTAL_FORMS), key=len, reverse=True)
FUNDAMENTAL_PATTERN = re.compile(
    r'(' + '|'.join(re.escape(s) for s in _FUNDAMENTAL_FORMS) + r')(?![a-z])',
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
    sym_pattern = re.compile(rf'(?<![A-Z]){re.escape(symbol)}(?![A-Z])')
    others_pattern = re.compile(
        r'(?<![A-Z])(' + '|'.join(re.escape(s) for s in SYMBOLS if s != symbol) + r')(?![A-Z])'
    )
    for m_sym in sym_pattern.finditer(text):
        window = text[m_sym.end() : m_sym.end() + 1500]
        nxt = others_pattern.search(window)
        scope = window[: nxt.start()] if nxt else window
        bm = BIAS_PATTERN.search(scope)
        if not bm:
            continue
        # Heuristic: prefer table-row matches over prose-context bias mentions.
        # A genuine table row has BOTH (A) a % sign or digit within 50 chars
        # before the bias word — the price/percent prefix in '$194.03-0.92%Neutral'
        # — AND (B) the bias word within 150 chars of the symbol. A long scope
        # (>400 chars) without both signals means the symbol was just name-dropped
        # in prose and the bias word belongs to something else nearby (e.g. ORCL
        # mentioned in passing, then 'hawkish hold' from a Fed paragraph 280
        # chars later).
        pre_bias = scope[max(0, bm.start() - 50) : bm.start()]
        has_table_signature = bool(re.search(r'[%\d]', pre_bias))
        is_close = bm.start() < 150
        if not (has_table_signature and is_close) and len(scope) > 400:
            continue
        matched_word = bm.group(1).lower()
        bias = _SYNONYM_TO_CANONICAL[matched_word]

        # Search the rest of the scope for a fundamental overlay keyword
        fund_match = FUNDAMENTAL_PATTERN.search(scope, bm.end())
        fundamental_score = None
        reason_start = bm.end()
        if fund_match:
            fundamental_score = _FUNDAMENTAL_TO_CANONICAL.get(fund_match.group(1).lower())
            # If the fundamental column is right next to the bias column, strip it
            # from the reason so the reason doesn't lead with "Bullish..."
            if fundamental_score and fund_match.start() - bm.end() < 3:
                reason_start = fund_match.end()

        reason_raw = scope[reason_start:]
        cleaned = reason_raw.replace('|', ' ')
        cleaned = re.sub(r'^[\s\-—:|.,#*$%+0-9]+', '', cleaned)
        cleaned = re.sub(r'[\s\-—:|.,]+$', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return {
            "bias": bias,
            "reason": cleaned or "no detail provided",
            "confidence": "medium",
            "fundamental_score": fundamental_score,
            "risk_level": None,
            "entry_quality": None,
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


def parse_json_brief(text):
    """Parse a structured-JSON brief into the script's standard output shape.

    Returns (symbols_out, parsed_count, macro_sentiment, macro_summary).
    Validates bias and fundamental_score against the canonical vocabularies
    and falls back to neutral/None for unknown values rather than passing
    untrusted strings through to the bot.
    """
    data = json.loads(text)

    macro = data.get("macro_summary") or {}
    raw_sent = (macro.get("market_sentiment") or "").lower().replace("_", "-")
    macro_sentiment = raw_sent if raw_sent in ("risk-on", "risk-off", "mixed", "neutral") else "neutral"
    macro_summary_text = (
        macro.get("marketwatch_summary")
        or macro.get("reuters_summary")
        or macro.get("benzinga_summary")
        or "no macro summary provided"
    )

    by_symbol = {
        e.get("symbol"): e
        for e in (data.get("symbols") or [])
        if isinstance(e, dict) and isinstance(e.get("symbol"), str)
    }

    valid_bias = ("buy", "avoid", "neutral")
    valid_fund = ("strong_bullish", "bullish", "neutral", "bearish", "strong_bearish")
    valid_risk = ("low", "medium", "high", "very_high")

    symbols_out = {}
    parsed_count = 0
    for sym in SYMBOLS:
        entry = by_symbol.get(sym)
        if entry:
            bias = (entry.get("trading_bias") or "neutral").lower()
            if bias not in valid_bias:
                bias = "neutral"
            fund = entry.get("fundamental_score")
            if isinstance(fund, str):
                fund_norm = fund.lower()
                fund = fund_norm if fund_norm in valid_fund else None
            else:
                fund = None
            risk = entry.get("risk_level")
            if isinstance(risk, str):
                risk_norm = risk.lower()
                risk = risk_norm if risk_norm in valid_risk else None
            else:
                risk = None
            entry_quality = entry.get("entry_quality")
            if not isinstance(entry_quality, str):
                entry_quality = None
            symbols_out[sym] = {
                "bias": bias,
                "reason": entry.get("reason") or "no detail provided",
                "confidence": "medium",
                "fundamental_score": fund,
                "risk_level": risk,
                "entry_quality": entry_quality,
            }
            parsed_count += 1
        else:
            symbols_out[sym] = {
                "bias": "neutral",
                "reason": "no signals found",
                "confidence": "low",
                "fundamental_score": None,
                "risk_level": None,
                "entry_quality": None,
            }

    return symbols_out, parsed_count, macro_sentiment, macro_summary_text


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

    # Auto-detect format: JSON if input starts with { or [, otherwise regex/text path
    text_stripped = text.lstrip()
    is_json = text_stripped.startswith("{") or text_stripped.startswith("[")

    if is_json:
        try:
            symbols_out, parsed_count, macro_sentiment, macro_summary = parse_json_brief(text)
            format_used = "json"
        except json.JSONDecodeError as e:
            print(f"ERROR: input looked like JSON but failed to parse: {e}", file=sys.stderr)
            sys.exit(1)
    else:
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
                    "fundamental_score": None,
                    "risk_level": None,
                    "entry_quality": None,
                }
        macro_sentiment = extract_macro_sentiment(text)
        macro_summary = extract_macro_summary(text)
        format_used = "table"

    output = {
        "market_date": market_date,
        "generated_at": datetime.now().isoformat(timespec='seconds'),
        "macro_sentiment": macro_sentiment,
        "macro_summary": macro_summary,
        "symbols": symbols_out,
        "source": "manual_chrome_analysis",
        "format": format_used,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    print("=== Manual market brief parsed ===")
    print(f"  Market date     : {market_date}")
    print(f"  Format          : {format_used}")
    print(f"  Macro sentiment : {output['macro_sentiment']}")
    print(f"  Macro summary   : {output['macro_summary'][:90]}")
    print(f"  Parsed symbols  : {parsed_count}/{len(SYMBOLS)} (rest defaulted to neutral/low)")
    print(f"  Output          : {OUTPUT_FILE}")
    print()
    print(f"  {'Symbol':<7} {'Bias':<8} {'Conf':<7} {'Fundamental':<15}  Reason")
    print(f"  {'-'*7} {'-'*8} {'-'*7} {'-'*15}  {'-'*55}")
    for sym in SYMBOLS:
        e = symbols_out[sym]
        reason = (e['reason'] or '')[:55]
        fund = e.get('fundamental_score') or '-'
        print(f"  {sym:<7} {e['bias']:<8} {e['confidence']:<7} {fund:<15}  {reason}")


if __name__ == "__main__":
    main()
