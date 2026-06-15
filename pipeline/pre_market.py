#!/usr/bin/env python3
"""Pre-market intelligence pipeline.

Replaces four independent fixed-time cron entries with a single sequential
pipeline that enforces the correct dependency order:

  1. cot_positioning_context   → current weekly CFTC COT macro context
  2. webull_context            → Webull screener-derived context evidence
  3. pre_market_research_data  → market_context.json + daily_symbol_context
  4. build_historical_trend_context → 5-day trend context from rolling_momentum
  5. collect_and_score_events  → daily_symbol_events + daily_symbol_predictions
  6. refresh_market_context_json → rewrite market_context.json from event-enriched context
  7. validate_predictions      → warn on flat/negative prediction correlation
  8. shadow_predictions        → score candidate model without live authority
  9. archive_context_state     → point-in-time snapshot
 10. prediction_cache preload  → warm in-memory prediction cache

Run via job_runner.py so each execution is recorded in job_runs:

  python3 job_runner.py \\
      --job-name pre_market_pipeline \\
      --lock-file /tmp/tradingbot_pre_market_pipeline.lock \\
      --log-file /home/tradingbot/trading-bot/pre_market_pipeline.log \\
      -- python3 pipeline/pre_market.py

Or directly (no job ledger entry):

  source venv/bin/activate
  set -a && . /etc/trading-bot.env && set +a
  python3 pipeline/pre_market.py [--date YYYY-MM-DD] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
for path in (BASE_DIR, BASE_DIR / "scripts", BASE_DIR / "src"):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from market_time import expected_market_context_date  # noqa: E402

from pipeline import Step, run_pipeline  # noqa: E402


def _build_steps(target_date: str, *, dry_run: bool = False) -> list[Step]:
    raw_output = f"/tmp/raw_market_research_{target_date}.data.json"
    events_output = f"/tmp/events_{target_date}.pipeline.json"

    return [
        Step(
            name="cot_positioning_context",
            module="cot_positioning_fetch",
            argv=[],
            critical=False,
            description="mirror current CFTC COT financial-futures report and normalize macro positioning state",
        ),
        Step(
            name="webull_context",
            module="webull_context_collect",
            argv=["--date", target_date],
            critical=False,
            description="collect Webull screener-derived morning/context evidence with no trade authority",
        ),
        Step(
            name="research_data",
            module="pre_market_research_data",
            argv=[
                "--raw-output",
                raw_output,
                "--build-output",
                "market_context.json",
                "--ingest-context",
            ],
            critical=True,
            description="fetch Alpaca bars, build market_context.json, populate daily_symbol_context",
        ),
        Step(
            name="historical_trend_context",
            module="build_historical_trend_context",
            argv=["--date", target_date],
            critical=False,
            description="persist rolling_momentum 5-day trend context for DB-backed intelligence",
        ),
        Step(
            name="collect_events",
            module="collect_and_score_events",
            argv=[
                "--date",
                target_date,
                "--max-per-symbol",
                "2",
                "--apply-context",
                "--predict",
                "--ai-interpret-events",
                "--ai-event-provider",
                "deterministic",
                "--output",
                events_output,
            ],
            critical=True,
            description="collect news events, score, apply context, generate daily_symbol_predictions",
        ),
        Step(
            name="refresh_market_context_json",
            module="intraday_context_refresh",
            argv=[
                "--date",
                target_date,
                "--skip-collect",
                "--reuse-existing-market-data",
            ],
            critical=True,
            description=(
                "rewrite market_context.json from event-enriched daily context without "
                "collecting events twice or refetching bars already built by research_data"
            ),
        ),
        Step(
            name="validate_predictions",
            module="pipeline.validate_predictions",
            argv=[
                "--date",
                target_date,
                "--sessions",
                "5",
                "--threshold",
                "0.0",
                "--bad-session-limit",
                "3",
            ],
            critical=False,
            description="warn if recent prediction_score correlation is flat or negative",
        ),
        Step(
            name="shadow_predictions",
            module="pipeline.shadow_predictions",
            argv=["--date", target_date],
            critical=False,
            description="write candidate model shadow_predictions with no live authority",
        ),
        Step(
            name="archive_context",
            module="archive_context_state",
            argv=["--reason", "premarket_pipeline"],
            critical=False,
            description="snapshot market_context.json + override hashes for replay",
        ),
        Step(
            name="prediction_cache_preload",
            module="prediction_cache",
            argv=["preload", "--date", target_date],
            critical=False,
            description="warm the in-memory prediction cache before market open",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        help="Override target market date YYYY-MM-DD (default: derived from expected_market_context_date)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print step plan without executing",
    )
    args = parser.parse_args()

    if args.date:
        target_date = args.date
    else:
        target_date = expected_market_context_date(None).isoformat()

    steps = _build_steps(target_date, dry_run=args.dry_run)

    if args.dry_run:
        print(f"Pre-market pipeline — target_date={target_date}  [DRY RUN]")
        print()
        for i, step in enumerate(steps, 1):
            crit = "CRITICAL" if step.critical else "warn-only"
            print(f"  {i}. [{crit}] {step.name}")
            print(f"       module : {step.module}")
            print(f"       argv   : {step.argv}")
            if step.description:
                print(f"       desc   : {step.description}")
        return 0

    result = run_pipeline("pre_market", steps, target_date)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
