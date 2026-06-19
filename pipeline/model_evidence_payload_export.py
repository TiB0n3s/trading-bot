#!/usr/bin/env python3
"""Materialize the heavy model-promotion evidence payload as a cached export.

This is the slow half of the model-evidence pipeline, split out so it can run in
its own generously-timed dark-hours slot instead of inside the fast LLM review.
It runs the ~2-year diagnostics build that
``model_promotion_evidence_service.build_model_promotion_evidence_payload``
produces (from the DuckDB/PyArrow research exports and governance reports, plus
read-only historical-bar validation against ``trades.db``) and writes the result
to the columnar-style cache that ``pipeline/model_evidence_review.py`` reads.

Observe-only: it persists numeric diagnostics only. It cannot promote, size,
approve, block, or alter live authority, and it never opens the live SQLite
writer path -- only read connections for validation.

Scheduling (NOT installed automatically -- add it yourself). Run it BEFORE the
review's 03:50 slot so the cache is fresh, on a generous timeout and WITHOUT
``--ionice-idle`` (idle I/O scheduling under contention is what starved the old
in-review build). Example, 02:00 Tue-Sat:

  0 2 * * 2-6 cd /home/tradingbot/trading-bot && PYTHONPATH=/home/tradingbot/trading-bot:/home/tradingbot/trading-bot/scripts:/home/tradingbot/trading-bot/src /home/tradingbot/trading-bot/venv/bin/python scripts/job_runner.py --job-name model_evidence_payload_export --lock-file /tmp/tradingbot_model_evidence_payload_export.lock --log-file /home/tradingbot/trading-bot/model_evidence_payload_export.log --timeout-seconds 5400 --nice 10 -- bash /home/tradingbot/trading-bot/run_model_evidence_payload_export.sh
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
for _p in (BASE_DIR, BASE_DIR / "src", BASE_DIR / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from trading_bot.services.model_evidence_payload_cache_service import (  # noqa: E402
    CACHE_RUNTIME_EFFECT,
    historical_window,
    write_payload_cache,
)
from trading_bot.services.model_promotion_evidence_service import (  # noqa: E402
    build_model_promotion_evidence_payload,
)


def run(date: str, *, write: bool = True) -> dict[str, Any]:
    start_date, end_date = historical_window(date)
    t0 = time.monotonic()
    diagnostics = build_model_promotion_evidence_payload(
        base_dir=BASE_DIR,
        write=False,
        start_date=start_date,
        end_date=end_date,
    )
    duration = round(time.monotonic() - t0, 2)

    result: dict[str, Any] = {
        "runtime_effect": CACHE_RUNTIME_EFFECT,
        "target_date": date,
        "window": [start_date, end_date],
        "build_duration_seconds": duration,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready_count": diagnostics.get("ready_count"),
        "artifact_count": diagnostics.get("artifact_count"),
    }
    if write:
        cache_file = write_payload_cache(
            BASE_DIR,
            date,
            diagnostics=diagnostics,
            window=(start_date, end_date),
            build_duration_seconds=duration,
            generated_at=result["generated_at"],
        )
        result["cache_path"] = str(cache_file)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Target date label for the cached payload (default: today UTC).",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Build the payload but do not write the cache (diagnostic only).",
    )
    args = parser.parse_args(argv)

    result = run(args.date, write=not args.no_write)
    print(
        f"[model-evidence-payload-export] {args.date} "
        f"ready={result.get('ready_count')}/{result.get('artifact_count')} "
        f"build={result.get('build_duration_seconds')}s "
        f"cache={result.get('cache_path', 'NOT WRITTEN')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
