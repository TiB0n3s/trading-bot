#!/usr/bin/env python3
"""
Collect, score, insert, and aggregate market intelligence events.

This is the automated replacement for manually maintaining event JSON.

Current collectors:
- company_news_collector.py: public Google News RSS headline search

Future collectors can be added here:
- earnings_event_collector.py
- analyst_action_collector.py
- sec_event_collector.py
- macro_event_collector.py

Usage:
  python3 collect_and_score_events.py --date 2026-05-26 --dry-run
  python3 collect_and_score_events.py --date 2026-05-26 --symbol AAPL --dry-run
  python3 collect_and_score_events.py --date 2026-05-26 --apply-context
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST
from market_intelligence.news_event_model import score_event
from market_intelligence.intelligence_store import (
    init_intelligence_tables,
    insert_daily_symbol_event,
    update_daily_context_from_events,
)
from market_intelligence.event_collectors.company_news_collector import (
    collect_company_news_events,
)
from market_intelligence.experience_model import predict_all_symbols
from repositories.market_intelligence_repo import MarketIntelligenceRepository
from alerts import send_alert


def short(v, width):
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def existing_event_keys(market_date: str) -> set[tuple]:
    """Return keys for idempotent same-day import."""
    init_intelligence_tables()
    return MarketIntelligenceRepository().daily_symbol_event_keys(market_date)


def event_key(event: dict) -> tuple:
    return (
        event.get("symbol"),
        event.get("event_type"),
        event.get("event_summary") or "",
        event.get("source_url") or "",
    )


def print_table(events):
    print()
    print(f"  {'#':>3} {'Sym':<7} {'Type':<22} {'Impact':<20} {'Relevance':<22} {'Net':>7} Summary")
    print(f"  {'-'*3} {'-'*7} {'-'*22} {'-'*20} {'-'*22} {'-'*7} {'-'*70}")

    for idx, e in enumerate(events, start=1):
        print(
            f"  {idx:>3} "
            f"{short(e.get('symbol'), 7):<7} "
            f"{short(e.get('event_type'), 22):<22} "
            f"{short(e.get('expected_market_impact'), 20):<20} "
            f"{short(e.get('trade_relevance'), 22):<22} "
            f"{str(e.get('net_event_score', '-')):>7} "
            f"{short(e.get('event_summary'), 70)}"
        )


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol", action="append", help="Optional symbol filter; can repeat")
    parser.add_argument("--max-per-symbol", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-context", action="store_true")
    parser.add_argument("--output", help="Optional JSON output path for collected/scored events")
    parser.add_argument("--no-dedupe", action="store_true", help="Insert duplicates instead of skipping existing same-day events")
    parser.add_argument("--predict", action="store_true", help="Generate observe-only symbol predictions after event/context updates")
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbol] if args.symbol else APPROVED_SYMBOLS_LIST
    invalid = sorted(set(symbols) - set(APPROVED_SYMBOLS_LIST))
    if invalid:
        raise SystemExit(f"ERROR: non-approved symbols requested: {invalid}")

    print()
    print("=== Collect and score events ===")
    print(f"  Date          : {args.date}")
    print(f"  Symbols       : {len(symbols)}")
    print(f"  Max/symbol    : {args.max_per_symbol}")
    print(f"  Dry run       : {args.dry_run}")
    print(f"  Apply context : {args.apply_context}")

    init_intelligence_tables()

    raw_events = collect_company_news_events(
        market_date=args.date,
        symbols=symbols,
        max_per_symbol=args.max_per_symbol,
        timeout=args.timeout,
    )

    scored = []
    errors = []

    for e in raw_events:
        try:
            scored.append(score_event(e))
        except Exception as exc:
            errors.append(f"{e.get('symbol')} {e.get('event_summary')}: {exc}")

    existing = existing_event_keys(args.date) if not args.no_dedupe else set()
    new_events = []
    duplicates = 0

    for e in scored:
        if event_key(e) in existing:
            duplicates += 1
            continue
        new_events.append(e)

    print()
    print(f"  Raw collected : {len(raw_events)}")
    print(f"  Scored        : {len(scored)}")
    print(f"  Duplicates    : {duplicates}")
    print(f"  New events    : {len(new_events)}")
    print(f"  Errors        : {len(errors)}")

    if errors:
        print()
        print("Errors:")
        for e in errors[:20]:
            print(f"  - {e}")
        if len(errors) > 20:
            print(f"  ... {len(errors) - 20} more")

        send_alert(
            title="Event scoring warnings",
            message=f"{len(errors)} event scoring errors for {args.date}",
            severity="warning",
            source="collect_and_score_events.py",
            payload={
                "market_date": args.date,
                "error_count": len(errors),
                "sample_errors": errors[:20],
            },
        )

    by_type = Counter(e.get("event_type") for e in new_events)
    by_impact = Counter(e.get("expected_market_impact") for e in new_events)
    by_relevance = Counter(e.get("trade_relevance") for e in new_events)
    by_symbol = Counter(e.get("symbol") for e in new_events)

    print()
    print(f"  Event types   : {dict(by_type)}")
    print(f"  Impacts       : {dict(by_impact)}")
    print(f"  Relevance     : {dict(by_relevance)}")
    print(f"  Top symbols   : {dict(by_symbol.most_common(15))}")

    print_table(new_events)

    if args.output:
        write_json(args.output, {
            "market_date": args.date,
            "source": "collect_and_score_events",
            "events": new_events,
            "duplicates_skipped": duplicates,
            "errors": errors,
        })
        print()
        print(f"Wrote scored events to {args.output}")

    if args.dry_run:
        print()
        print("Dry run only; no rows inserted.")
        return 0

    inserted = []
    for e in new_events:
        event_id = insert_daily_symbol_event(e)
        inserted.append((event_id, e))

    print()
    print(f"Inserted {len(inserted)} daily_symbol_events rows.")

    updated_symbols_by_date = defaultdict(set)

    if args.apply_context:
        by_date_symbol = defaultdict(set)
        for _, e in inserted:
            by_date_symbol[e["market_date"]].add(e["symbol"])

        updated = 0
        skipped = 0
        for market_date, syms in sorted(by_date_symbol.items()):
            for sym in sorted(syms):
                result = update_daily_context_from_events(market_date, sym)
                updated += int(result.get("updated", 0))
                skipped += int(result.get("skipped_no_events", 0))
                if int(result.get("updated", 0)) > 0:
                    updated_symbols_by_date[market_date].add(sym)

        print(f"Applied event aggregates to daily_symbol_context: updated={updated}, skipped={skipped}")

    if args.predict:
        prediction_count = 0

        if args.apply_context and updated_symbols_by_date:
            for market_date, syms in sorted(updated_symbols_by_date.items()):
                for sym in sorted(syms):
                    preds = predict_all_symbols(market_date, symbol=sym, write=True)
                    prediction_count += len(preds)
        else:
            # If no new events were inserted or --apply-context was not used,
            # still generate predictions for the requested symbol set/date.
            for sym in symbols:
                try:
                    preds = predict_all_symbols(args.date, symbol=sym, write=True)
                    prediction_count += len(preds)
                except Exception as e:
                    print(f"[WARN] prediction failed for {args.date} {sym}: {e}")
                    send_alert(
                        title="Prediction generation failed",
                        message=f"Prediction failed for {args.date} {sym}: {e}",
                        severity="warning",
                        source="collect_and_score_events.py",
                        symbol=sym,
                        payload={"market_date": args.date, "symbol": sym, "error": str(e)},
                    )

        if prediction_count <= 0:
            send_alert(
                title="No predictions generated",
                message=f"collect_and_score_events generated 0 predictions for {args.date}",
                severity="warning",
                source="collect_and_score_events.py",
                payload={
                    "market_date": args.date,
                    "symbols": symbols,
                    "apply_context": args.apply_context,
                    "new_events": len(new_events),
                    "inserted": len(inserted),
                },
            )

        print(f"Generated observe-only predictions: {prediction_count}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        try:
            send_alert(
                title="Event collection failed",
                message=str(exc),
                severity="error",
                source="collect_and_score_events.py",
                payload={"error": str(exc)},
            )
        except Exception:
            pass
        raise
