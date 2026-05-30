#!/usr/bin/env python3
"""
Bot event audit logging.

Structured DB-backed timeline of important bot decisions:
- intelligence context
- decision policy
- portfolio replacement
- position manager
- order submissions
- learning/report runs

This is intentionally lightweight and fail-open. Event logging should never
break trading execution.
"""

import argparse
import json

from services.bot_events_service import build_default_bot_events_service, now_s

_bot_events_service = None


def get_bot_events_service():
    global _bot_events_service
    if _bot_events_service is None:
        _bot_events_service = build_default_bot_events_service()
    return _bot_events_service


def init_bot_events_table():
    return get_bot_events_service().init_table()


def log_event(
    event_type,
    symbol=None,
    action=None,
    decision=None,
    severity=None,
    reason=None,
    source=None,
    payload=None,
):
    return get_bot_events_service().log_event(
        event_type=event_type,
        symbol=symbol,
        action=action,
        decision=decision,
        severity=severity,
        reason=reason,
        source=source,
        payload=payload,
    )


def fetch_events(limit=50, event_type=None, symbol=None, since=None):
    return get_bot_events_service().fetch_events(
        limit=limit,
        event_type=event_type,
        symbol=symbol,
        since=since,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="Initialize bot_events table")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--event-type")
    parser.add_argument("--symbol")
    parser.add_argument("--since", help="YYYY-MM-DD or timestamp lower bound")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init:
        init_bot_events_table()
        print("bot_events table initialized.")
        return

    rows = fetch_events(
        limit=args.limit,
        event_type=args.event_type,
        symbol=args.symbol,
        since=args.since,
    )

    if args.json:
        out = []
        for r in rows:
            item = dict(r)
            try:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            except Exception:
                item["payload"] = item.pop("payload_json")
            out.append(item)
        print(json.dumps(out, indent=2, sort_keys=True))
        return

    print("=" * 110)
    print("  Bot Events")
    print("=" * 110)
    print(f"{'ID':>6} {'Timestamp':<19} {'Type':<26} {'Sym':<6} {'Act':<6} {'Decision':<18} {'Severity':<8} Reason")
    print("-" * 140)

    for r in rows:
        print(
            f"{r['id']:>6} "
            f"{r['timestamp']:<19} "
            f"{str(r['event_type'] or ''):<26} "
            f"{str(r['symbol'] or ''):<6} "
            f"{str(r['action'] or ''):<6} "
            f"{str(r['decision'] or ''):<18} "
            f"{str(r['severity'] or ''):<8} "
            f"{str(r['reason'] or '')[:80]}"
        )


if __name__ == "__main__":
    main()
