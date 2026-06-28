#!/usr/bin/env python3
"""Off-hours historical-bar learning pipeline.

This is intended for weekends or market-closed windows. It is still
observe/report-only by default. Use --execute-retry only when you intentionally
want to launch the long Polygon retry job.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import Step, default_market_date, run_pipeline


def _build_steps(args: argparse.Namespace) -> list[Step]:
    retry_argv = [
        "historical-bar-retry-plan",
        args.start_date,
        "--end-date",
        args.end_date,
        "--max-symbols",
        str(args.max_symbols),
    ]
    if args.execute_retry:
        retry_argv.append("--execute")
    steps = [
        Step(
            name="historical_bar_retry_plan",
            module="ops_check",
            argv=retry_argv,
            critical=False,
            description="plan or execute focused historical-bar retry for empty/missing cache chunks",
        ),
        Step(
            name="historical_bar_readiness",
            module="ops_check",
            argv=[
                "historical-bar-readiness",
                args.start_date,
                "--end-date",
                args.end_date,
                "--include-db-quality",
                "--db-quality-mode",
                "sample",
                "--sample-rows-per-symbol",
                "250",
            ],
            critical=False,
            description="sample DB quality and coverage after retry",
        ),
    ]
    if args.train:
        for label in ("triple_barrier_label", "trend_scan_label"):
            steps.append(
                Step(
                    name=f"train_{label}",
                    module="pipeline.train_historical_bar_model",
                    argv=[
                        "--start-date",
                        args.start_date,
                        "--end-date",
                        args.end_date,
                        "--label-target",
                        label,
                        "--rows-per-symbol",
                        str(args.rows_per_symbol),
                        "--limit",
                        str(args.max_rows),
                        "--min-samples",
                        "500",
                        "--skip-suite",
                    ],
                    critical=False,
                    description=f"train observe-only historical-bar {label} model",
                )
            )
    steps.extend(
        [
            Step(
                name="historical_bar_models",
                module="ops_check",
                argv=["historical-bar-models"],
                critical=False,
                description="report latest observe-only model candidates",
            ),
            Step(
                name="historical_bar_validation_triple",
                module="ops_check",
                argv=[
                    "historical-bar-validation",
                    args.start_date,
                    "--end-date",
                    args.end_date,
                    "--label-target",
                    "triple_barrier_label",
                    "--rows-per-symbol",
                    "250",
                    "--max-rows",
                    "20000",
                ],
                critical=False,
                description="validate triple-barrier label buckets",
            ),
            Step(
                name="historical_bar_validation_trend",
                module="ops_check",
                argv=[
                    "historical-bar-validation",
                    args.start_date,
                    "--end-date",
                    args.end_date,
                    "--label-target",
                    "trend_scan_label",
                    "--rows-per-symbol",
                    "250",
                    "--max-rows",
                    "20000",
                ],
                critical=False,
                description="validate trend-scan label buckets",
            ),
            Step(
                name="monday_readiness",
                module="ops_check",
                argv=["monday-readiness"],
                critical=False,
                description="summarize Monday readiness",
            ),
        ]
    )
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2024-06-01")
    parser.add_argument("--end-date", default=default_market_date())
    parser.add_argument("--max-symbols", type=int, default=10)
    parser.add_argument("--execute-retry", action="store_true")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--rows-per-symbol", type=int, default=250)
    parser.add_argument("--max-rows", type=int, default=20000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    steps = _build_steps(args)
    if args.dry_run:
        print(f"Off-hours historical-bar learning pipeline [DRY RUN] {args.start_date}..{args.end_date}")
        for idx, step in enumerate(steps, start=1):
            print(f"  {idx}. {step.name}: {step.module} {step.argv}")
        return 0
    result = run_pipeline("off_hours_historical_bar_learning", steps, args.end_date)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
