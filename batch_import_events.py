#!/usr/bin/env python3
"""
Batch import structured symbol events.

Reads a JSON file containing either:
  1. A list of event objects:
     [
       {"market_date": "2026-05-26", "symbol": "AAPL", "event_type": "product_launch", ...}
     ]

  2. A wrapper object:
     {
       "market_date": "2026-05-26",
       "source": "manual_batch",
       "events": [
         {"symbol": "AAPL", "event_type": "product_launch", ...}
       ]
     }

Each event is scored through market_intelligence.news_event_model.score_event()
and inserted into daily_symbol_events.

Optional:
  --apply-context updates daily_symbol_context aggregate event scores afterward.

Usage:
  python3 batch_import_events.py /tmp/events_2026-05-26.json
  python3 batch_import_events.py /tmp/events_2026-05-26.json --dry-run
  python3 batch_import_events.py /tmp/events_2026-05-26.json --apply-context
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS
from market_intelligence.news_event_model import score_event
from market_intelligence.intelligence_store import (
    init_intelligence_tables,
    insert_daily_symbol_event,
    update_daily_context_from_events,
)


def load_events(path: Path):
    raw = json.loads(path.read_text())

    wrapper_market_date = None
    wrapper_source = None

    if isinstance(raw, list):
        events = raw
    elif isinstance(raw, dict):
        wrapper_market_date = raw.get("market_date")
        wrapper_source = raw.get("source")
        events = raw.get("events")
        if not isinstance(events, list):
            raise ValueError("JSON object input must contain an 'events' list")
    else:
        raise ValueError("Input JSON must be a list or an object with an events list")

    normalized = []
    for idx, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            raise ValueError(f"event #{idx} is not an object")

        e = dict(event)

        if wrapper_market_date and not e.get("market_date"):
            e["market_date"] = wrapper_market_date

        if wrapper_source and not e.get("source"):
            e["source"] = wrapper_source

        if e.get("symbol"):
            e["symbol"] = str(e["symbol"]).upper().strip()

        normalized.append(e)

    return normalized


def validate_event(event, idx):
    missing = []
    for key in ("market_date", "symbol", "event_type"):
        if not event.get(key):
            missing.append(key)

    if missing:
        return f"event #{idx} missing required fields: {missing}"

    symbol = str(event["symbol"]).upper()
    if symbol not in APPROVED_SYMBOLS:
        return f"event #{idx} has non-approved symbol: {symbol}"

    if not event.get("event_summary") and not event.get("summary"):
        return f"event #{idx} missing event_summary/summary"

    return None


def short(v, width):
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def print_event_table(scored_events):
    print()
    print(f"  {'#':>3} {'Date':<11} {'Sym':<7} {'Type':<22} {'Impact':<20} {'Relevance':<22} {'Net':>7} Summary")
    print(f"  {'-'*3} {'-'*11} {'-'*7} {'-'*22} {'-'*20} {'-'*22} {'-'*7} {'-'*54}")

    for i, e in enumerate(scored_events, start=1):
        print(
            f"  {i:>3} "
            f"{short(e.get('market_date'), 11):<11} "
            f"{short(e.get('symbol'), 7):<7} "
            f"{short(e.get('event_type'), 22):<22} "
            f"{short(e.get('expected_market_impact'), 20):<20} "
            f"{short(e.get('trade_relevance'), 22):<22} "
            f"{str(e.get('net_event_score', '-')):>7} "
            f"{short(e.get('event_summary') or e.get('summary'), 54)}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to JSON event batch")
    parser.add_argument("--dry-run", action="store_true", help="Score and validate without inserting")
    parser.add_argument("--apply-context", action="store_true", help="Update daily_symbol_context aggregate event scores after insert")
    parser.add_argument("--details", action="store_true", help="Print full scored event JSON after summary")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f"ERROR: input file not found: {path}")

    init_intelligence_tables()

    try:
        events = load_events(path)
    except Exception as e:
        raise SystemExit(f"ERROR: failed to load events: {e}")

    errors = []
    scored_events = []

    for idx, event in enumerate(events, start=1):
        err = validate_event(event, idx)
        if err:
            errors.append(err)
            continue

        try:
            scored_events.append(score_event(event))
        except Exception as e:
            errors.append(f"event #{idx} scoring failed: {e}")

    print()
    print("=== Batch event import preview ===")
    print(f"  Input          : {path}")
    print(f"  Events loaded  : {len(events)}")
    print(f"  Valid/scored   : {len(scored_events)}")
    print(f"  Errors         : {len(errors)}")
    print(f"  Dry run        : {args.dry_run}")

    if errors:
        print()
        print("Errors:")
        for e in errors:
            print(f"  - {e}")

    if scored_events:
        by_type = Counter(e.get("event_type") for e in scored_events)
        by_impact = Counter(e.get("expected_market_impact") for e in scored_events)
        by_relevance = Counter(e.get("trade_relevance") for e in scored_events)
        by_symbol = Counter(e.get("symbol") for e in scored_events)

        print()
        print(f"  Event types    : {dict(by_type)}")
        print(f"  Impacts        : {dict(by_impact)}")
        print(f"  Relevance      : {dict(by_relevance)}")
        print(f"  Symbols        : {dict(by_symbol)}")

        print_event_table(scored_events)

    if args.details:
        print()
        print("Full scored events:")
        print(json.dumps(scored_events, indent=2))

    if errors:
        print()
        print("Import aborted because one or more events failed validation.")
        return 2

    if args.dry_run:
        print()
        print("Dry run only; no rows inserted.")
        return 0

    inserted = []
    for event in scored_events:
        event_id = insert_daily_symbol_event(event)
        inserted.append((event_id, event))

    print()
    print(f"Inserted {len(inserted)} daily_symbol_events rows.")

    context_results = []
    if args.apply_context:
        by_date = defaultdict(set)
        for _, event in inserted:
            by_date[event["market_date"]].add(event["symbol"])

        for market_date, symbols in sorted(by_date.items()):
            for symbol in sorted(symbols):
                result = update_daily_context_from_events(market_date, symbol)
                context_results.append(result)

        updated = sum(r.get("updated", 0) for r in context_results)
        skipped = sum(r.get("skipped_no_events", 0) for r in context_results)

        print(f"Applied event aggregates to daily_symbol_context: updated={updated}, skipped={skipped}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
