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
            name="excursion_memory",
            module="excursion_report",
            argv=["--date", target_date, "--limit", "100", "--write-memory"],
            critical=False,
            description="refresh trade excursion memory used by strategy policy context",
        ),
        Step(
            name="missed_opportunity_memory",
            module="missed_opportunity_report",
            argv=["--date", target_date, "--limit", "100", "--write-memory"],
            critical=False,
            description="refresh missed-opportunity memory for rejected-signal learning",
        ),
        Step(
            name="symbol_momentum_timing_memory",
            module="symbol_momentum_timing_report",
            argv=["--date", target_date, "--write-memory"],
            critical=False,
            description="refresh symbol momentum timing memory",
        ),
        Step(
            name="policy_backtest_summary",
            module="policy_backtest",
            argv=["--date", target_date, "--write-summary"],
            critical=False,
            description="refresh policy backtest recommendation artifact",
        ),
        Step(
            name="portfolio_replacement_memory",
            module="portfolio_replacement_report",
            argv=["--minutes", "390", "--top", "20", "--write-memory"],
            critical=False,
            description="refresh portfolio replacement memory",
        ),
        Step(
            name="strategy_memory_refresh",
            module="strategy_learner",
            argv=[],
            critical=False,
            description="refresh live strategy memory after report-memory artifacts exist",
        ),
        Step(
            name="strategy_brain_report",
            module="strategy_brain_report",
            argv=[],
            critical=False,
            description="summarize current strategy-brain memory state",
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
            name="advanced_alpha_comparison",
            module="ops_check",
            argv=["advanced-alpha-comparison", target_date],
            critical=False,
            description="compare standard thresholding with asymmetric false-positive guards",
        ),
        Step(
            name="advanced_alpha_readiness",
            module="ops_check",
            argv=["advanced-alpha-readiness", target_date],
            critical=False,
            description="score advanced alpha feed/schema/coverage/outcome/readiness gates",
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
            name="historical_bar_completion_training",
            module="pipeline.historical_bar_completion_hook",
            argv=["--date", target_date],
            critical=False,
            description="trigger guarded observe-only training when historical bar backfill crosses readiness floor",
        ),
        Step(
            name="historical_bar_models",
            module="ops_check",
            argv=["historical-bar-models"],
            critical=False,
            description="report observe-only historical-bar model readiness and artifact hygiene",
        ),
        Step(
            name="historical_bar_validation_triple",
            module="ops_check",
            argv=[
                "historical-bar-validation",
                "2024-06-01",
                "--end-date",
                target_date,
                "--label-target",
                "triple_barrier_label",
                "--rows-per-symbol",
                "250",
                "--max-rows",
                "20000",
            ],
            critical=False,
            description="validate historical-bar triple-barrier label buckets",
        ),
        Step(
            name="historical_bar_retry_plan",
            module="ops_check",
            argv=[
                "historical-bar-retry-plan",
                "2024-06-01",
                "--end-date",
                target_date,
                "--max-symbols",
                "10",
            ],
            critical=False,
            description="surface any remaining empty/missing historical bar cache chunks",
        ),
        Step(
            name="monday_readiness",
            module="ops_check",
            argv=["monday-readiness"],
            critical=False,
            description="summarize required/advisory readiness checks for next session",
        ),
        Step(
            name="external_symbol_candidate_refresh",
            module="pipeline.external_symbol_candidate_refresh",
            argv=["--date", target_date, "--lookback-days", "5", "--max-chunks", "3"],
            critical=False,
            description="discover repeated external symbols, queue research candidates, and backfill bounded Polygon history",
        ),
        Step(
            name="symbol_universe_retraining",
            module="pipeline.symbol_universe_retrain",
            argv=["--date", target_date],
            critical=False,
            description="force guarded observe-only retraining when approved symbols change",
        ),
        Step(
            name="automated_retraining",
            module="pipeline.retrain",
            argv=["--date", target_date, "--sessions", "5", "--bad-session-limit", "3"],
            critical=False,
            description="run guarded observe-only retraining and quant model comparison",
        ),
        Step(
            name="policy_artifact_register",
            module="policy_artifacts",
            argv=[
                "register",
                "--label",
                "after_close_learning",
                "--source",
                "pipeline/after_close_learning.py",
                "--known-good",
            ],
            critical=False,
            description="snapshot refreshed policy artifacts after the pipeline run",
        ),
        Step(
            name="point_in_time_archive",
            module="archive_context_state",
            argv=["--reason", "after_close_learning_policy_artifacts"],
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
