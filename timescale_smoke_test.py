#!/usr/bin/env python3
"""Smoke test the optional TimescaleDB tick writer."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json

from services.timescale_tick_writer_service import ensure_timescale_schema, write_ticks


async def _run(args):
    schema = await ensure_timescale_schema(args.db_uri)
    if not schema.ok:
        return {"schema": schema.to_dict(), "write": None}
    write = await write_ticks(
        [
            {
                "timestamp": datetime.now(timezone.utc),
                "ticker": args.symbol.upper(),
                "price": args.price,
                "volume": args.volume,
            }
        ],
        db_uri=args.db_uri,
    )
    return {"schema": schema.to_dict(), "write": write.to_dict()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-uri")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--price", type=float, default=100.0)
    parser.add_argument("--volume", type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
