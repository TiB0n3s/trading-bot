#!/usr/bin/env python3
"""After-close quant learning pipeline.

This recurring pipeline turns the quant stack into an operational loop:
complete outcomes, export research datasets, compare observe-only models, and
surface readiness. It is analysis-only and cannot change live trade authority.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import Step, run_pipeline


def _build_steps(target_date: str) -> list[Step]:
    return [
        Step(
            name="trade_matcher",
            module="trade_matcher",
            argv=[],
            critical=True,
            description="rebuild matched trades before outcome attribution",
        ),
        Step(
            name="rejected_signal_outcomes",
            module="rejected_signal_outcome_builder",
            argv=["--date", target_date],
            critical=False,
            description="complete rejected-signal forward outcomes",
        ),
        Step(
            name="candidate_outcome_backfill",
            module="ops_check",
            argv=["candidate-outcome-backfill", target_date],
            critical=False,
            description="complete candidate-universe forward outcomes for missed-buy learning",
        ),
        Step(
            name="exit_snapshot_backfill",
            module="ops_check",
            argv=["exit-snapshot-backfill", target_date],
            critical=False,
            description="link approved trades to canonical exit snapshots",
        ),
        Step(
            name="research_export",
            module="ops_check",
            argv=["research-export", target_date],
            critical=False,
            description="export lifecycle/candidate/rejected data to Parquet and DuckDB",
        ),
        Step(
            name="pattern_learning_inputs",
            module="ops_check",
            argv=["pattern-learning-inputs", target_date],
            critical=False,
            description="summarize executed, missed, and EFI/PVT pattern learning inputs",
        ),
        Step(
            name="feature_attribution",
            module="ops_check",
            argv=["feature-attribution", target_date],
            critical=False,
            description="rank feature-family evidence and promotion guardrails",
        ),
        Step(
            name="post_trade_learning",
            module="ops_check",
            argv=["post-trade-learning", target_date],
            critical=False,
            description="summarize expectancy by setup/regime/session/execution buckets",
        ),
        Step(
            name="learning_readiness",
            module="ops_check",
            argv=["learning-readiness", target_date],
            critical=False,
            description="report outcome coverage, calibration, active learning, and blockers",
        ),
        Step(
            name="paper_learning_authority",
            module="ops_check",
            argv=["paper-learning-authority", target_date],
            critical=False,
            description="audit paper-only learning overrides against linked lifecycle outcomes",
        ),
        Step(
            name="automated_retraining",
            module="pipeline.retrain",
            argv=["--date", target_date, "--sessions", "5", "--bad-session-limit", "3"],
            critical=False,
            description="run guarded observe-only retraining and quant model comparison",
        ),
        Step(
            name="point_in_time_archive",
            module="archive_context_state",
            argv=["--reason", "after_close_quant_learning_pipeline"],
            critical=False,
            description="archive replay-safe market/context/artifact state",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    steps = _build_steps(args.date)
    if args.dry_run:
        print(f"After-close quant learning pipeline — target_date={args.date}  [DRY RUN]")
        print()
        for i, step in enumerate(steps, 1):
            crit = "CRITICAL" if step.critical else "warn-only"
            print(f"  {i}. [{crit}] {step.name}")
            print(f"       module : {step.module}")
            print(f"       argv   : {step.argv}")
            if step.description:
                print(f"       desc   : {step.description}")
        return 0

    result = run_pipeline("after_close_quant_learning", steps, args.date)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
