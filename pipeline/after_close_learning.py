#!/usr/bin/env python3
"""After-close quant learning pipeline.

This recurring pipeline turns the quant stack into an operational loop:
complete outcomes, export research datasets, compare observe-only models, and
surface readiness. It is analysis-only and cannot change live trade authority.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import Step, default_market_date, run_pipeline  # noqa: E402

MARKER_ROOT = BASE_DIR / "runtime_state" / "pipeline_step_markers" / "after_close_learning"
DEFAULT_DAILY_MEMORY_LIMIT_MB = 2048
DEFAULT_RESEARCH_MEMORY_LIMIT_MB = 4096
DEFAULT_DAILY_TIMEOUT_SECONDS = 900
DEFAULT_RESEARCH_TIMEOUT_SECONDS = 1800


def _apply_numeric_thread_defaults() -> None:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(name, "1")


def _marker_path(lane: str, target_date: str, step_name: str) -> Path:
    safe_date = str(target_date).replace("/", "-")
    return MARKER_ROOT / lane / safe_date / f"{step_name}.json"


def _step(
    *,
    lane: str,
    target_date: str,
    name: str,
    module: str,
    argv: list[str],
    critical: bool = False,
    description: str = "",
    memory_limit_mb: int | None = None,
    timeout_seconds: int | None = None,
    markers: bool = True,
) -> Step:
    is_research = lane == "research"
    default_memory = (
        DEFAULT_RESEARCH_MEMORY_LIMIT_MB if is_research else DEFAULT_DAILY_MEMORY_LIMIT_MB
    )
    default_timeout = (
        DEFAULT_RESEARCH_TIMEOUT_SECONDS if is_research else DEFAULT_DAILY_TIMEOUT_SECONDS
    )
    return Step(
        name=name,
        module=module,
        argv=argv,
        critical=critical,
        description=description,
        memory_limit_mb=default_memory if memory_limit_mb is None else memory_limit_mb,
        timeout_seconds=default_timeout if timeout_seconds is None else timeout_seconds,
        marker_path=_marker_path(lane, target_date, name) if markers else None,
    )


def _build_daily_steps(target_date: str) -> list[Step]:
    return [
        _step(
            lane="daily",
            target_date=target_date,
            name="db_workload_cleanup",
            module="scripts.db_workload_report",
            argv=["--checkpoint", "--checkpoint-mode", "PASSIVE"],
            critical=False,
            description="report database pressure and run a bounded passive WAL checkpoint",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="trade_matcher",
            module="trade_matcher",
            argv=[],
            critical=True,
            description="rebuild matched trades before outcome attribution",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="rejected_signal_outcomes",
            module="rejected_signal_outcome_builder",
            argv=["--date", target_date],
            critical=False,
            description="complete rejected-signal forward outcomes",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="learning_backfill_repair",
            module="pipeline.learning_backfill_repair",
            argv=[
                "--date",
                target_date,
                "--candidate-limit",
                "300",
                "--candidate-target-coverage",
                "0.95",
                "--max-candidate-passes",
                "5",
            ],
            critical=False,
            description="automatically complete candidate outcomes and approved exit snapshots",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="excursion_memory",
            module="excursion_report",
            argv=["--date", target_date, "--limit", "100", "--write-memory"],
            critical=False,
            description="refresh trade excursion memory used by strategy policy context",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="missed_opportunity_memory",
            module="missed_opportunity_report",
            argv=["--date", target_date, "--limit", "100", "--write-memory"],
            critical=False,
            description="refresh missed-opportunity memory for rejected-signal learning",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="symbol_momentum_timing_memory",
            module="symbol_momentum_timing_report",
            argv=["--date", target_date, "--write-memory"],
            critical=False,
            description="refresh symbol momentum timing memory",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="policy_backtest_summary",
            module="policy_backtest",
            argv=["--date", target_date, "--write-summary"],
            critical=False,
            description="refresh policy backtest recommendation artifact",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="portfolio_replacement_memory",
            module="portfolio_replacement_report",
            argv=["--minutes", "390", "--top", "20", "--write-memory"],
            critical=False,
            description="refresh portfolio replacement memory",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="historical_outcome_feedback",
            module="pipeline.historical_outcome_feedback",
            argv=["--date", target_date],
            critical=False,
            description="materialize prior-session outcome feedback for active paper intelligence",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="strategy_memory_refresh",
            module="strategy_learner",
            argv=[],
            critical=False,
            description="refresh live strategy memory after report-memory artifacts exist",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="strategy_brain_report",
            module="strategy_brain_report",
            argv=[],
            critical=False,
            description="summarize current strategy-brain memory state",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="learning_readiness",
            module="ops_check",
            argv=["learning-readiness", target_date],
            critical=False,
            description="report outcome coverage, calibration, active learning, and blockers",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="paper_learning_authority",
            module="ops_check",
            argv=["paper-learning-authority", target_date],
            critical=False,
            description="audit paper-only learning overrides against linked lifecycle outcomes",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="operator_intelligence",
            module="ops_check",
            argv=["operator-intelligence", target_date],
            critical=False,
            description="summarize core intelligence readiness and next operator checks",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="monday_readiness",
            module="ops_check",
            argv=["monday-readiness"],
            critical=False,
            description="summarize required/advisory readiness checks for next session",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="policy_artifact_register",
            module="policy_artifacts",
            argv=[
                "register",
                "--label",
                "after_close_learning_daily",
                "--source",
                "pipeline/after_close_learning.py",
                "--known-good",
            ],
            critical=False,
            description="snapshot refreshed daily policy artifacts after the pipeline run",
        ),
        _step(
            lane="daily",
            target_date=target_date,
            name="point_in_time_archive",
            module="archive_context_state",
            argv=["--reason", "after_close_learning_daily_policy_artifacts"],
            critical=False,
            description="archive replay-safe daily market/context/artifact state",
        ),
    ]


def _build_research_steps(target_date: str) -> list[Step]:
    return [
        _step(
            lane="research",
            target_date=target_date,
            name="research_export",
            module="ops_check",
            argv=["research-export", target_date],
            critical=False,
            description="export lifecycle/candidate/rejected data to Parquet and DuckDB",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="pattern_learning_inputs",
            module="ops_check",
            argv=["pattern-learning-inputs", target_date],
            critical=False,
            description="summarize executed, missed, and EFI/PVT pattern learning inputs",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="advanced_alpha_comparison",
            module="ops_check",
            argv=["advanced-alpha-comparison", target_date],
            critical=False,
            description="compare standard thresholding with asymmetric false-positive guards",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="advanced_alpha_readiness",
            module="ops_check",
            argv=["advanced-alpha-readiness", target_date],
            critical=False,
            description="score advanced alpha feed/schema/coverage/outcome/readiness gates",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="feature_attribution",
            module="ops_check",
            argv=["feature-attribution", target_date],
            critical=False,
            description="rank feature-family evidence and promotion guardrails",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="post_trade_learning",
            module="ops_check",
            argv=["post-trade-learning", target_date],
            critical=False,
            description="summarize expectancy by setup/regime/session/execution buckets",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="auto_sell_learning_health",
            module="ops_check",
            argv=["auto-sell", target_date],
            critical=False,
            description="summarize first-class auto-sell ML, pressure, and execution analytics",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="counterfactual_concept_drift",
            module="pipeline.counterfactual_concept_drift",
            argv=["--date", target_date],
            critical=False,
            description="write PSI drift guardrail for counterfactual veto relaxation",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="counterfactual_veto_relaxation",
            module="pipeline.counterfactual_veto_relaxation",
            argv=["--date", target_date, "--lookback-days", "5", "--limit", "500"],
            critical=False,
            description="train guarded paper-only false-negative veto-relaxation model from rejected outcomes",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="historical_bar_completion_training",
            module="pipeline.historical_bar_completion_hook",
            argv=["--date", target_date],
            critical=False,
            description="trigger guarded observe-only training when historical bar backfill crosses readiness floor",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="historical_bar_models",
            module="ops_check",
            argv=["historical-bar-models"],
            critical=False,
            description="report observe-only historical-bar model readiness and artifact hygiene",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="historical_bar_paper_strategy_spy",
            module="ops_check",
            argv=["historical-bar-paper-strategy", "SPY", "--action", "buy"],
            critical=False,
            description="journal paper-only historical-bar ensemble score for market benchmark",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="historical_bar_paper_validation",
            module="ops_check",
            argv=[
                "historical-bar-paper-validation",
                "2024-06-01",
                "--end-date",
                target_date,
                "--label-target",
                "triple_barrier_label",
                "--rows-per-symbol",
                "100",
                "--max-rows",
                "10000",
                "--thresholds",
                "55,60,65,70",
            ],
            critical=False,
            description="compare paper ensemble scoring with naive baseline over labeled bars",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="adversarial_simulation",
            module="scripts.adversarial_simulation",
            argv=["--symbol", "SPY"],
            critical=False,
            description="red-team model stack with telemetry, decay, noise, and sequence-risk perturbations",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="historical_bar_walk_forward",
            module="ops_check",
            argv=[
                "historical-bar-walk-forward",
                "2024-06-01",
                "--end-date",
                target_date,
                "--label-target",
                "triple_barrier_label",
                "--rows-per-symbol",
                "100",
                "--max-rows",
                "10000",
            ],
            critical=False,
            description="validate paper ensemble stability across chronological folds",
        ),
        _step(
            lane="research",
            target_date=target_date,
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
                "100",
                "--max-rows",
                "10000",
            ],
            critical=False,
            description="validate historical-bar triple-barrier label buckets",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="exit_intelligence",
            module="ops_check",
            argv=["exit-intelligence", target_date],
            critical=False,
            description="summarize missed upside, recovery, capture, and avoided drawdown by exit trigger",
        ),
        _step(
            lane="research",
            target_date=target_date,
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
        _step(
            lane="research",
            target_date=target_date,
            name="external_symbol_candidate_refresh",
            module="pipeline.external_symbol_candidate_refresh",
            argv=["--date", target_date, "--lookback-days", "5", "--max-chunks", "3"],
            critical=False,
            description="discover repeated external symbols, queue research candidates, and backfill bounded Polygon history",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="symbol_universe_retraining",
            module="pipeline.symbol_universe_retrain",
            argv=["--date", target_date],
            critical=False,
            description="force guarded observe-only retraining when approved symbols change",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="automated_retraining",
            module="pipeline.retrain",
            argv=[
                "--date",
                target_date,
                "--sessions",
                "5",
                "--bad-session-limit",
                "3",
                "--memory-limit-mb",
                str(DEFAULT_RESEARCH_MEMORY_LIMIT_MB),
            ],
            critical=False,
            description="run guarded observe-only retraining and quant model comparison",
            timeout_seconds=2400,
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="policy_artifact_register",
            module="policy_artifacts",
            argv=[
                "register",
                "--label",
                "after_close_learning_research",
                "--source",
                "pipeline/after_close_learning.py",
                "--known-good",
            ],
            critical=False,
            description="snapshot refreshed policy artifacts after the pipeline run",
        ),
        _step(
            lane="research",
            target_date=target_date,
            name="point_in_time_archive",
            module="archive_context_state",
            argv=["--reason", "after_close_learning_research_policy_artifacts"],
            critical=False,
            description="archive replay-safe market/context/artifact state",
        ),
    ]


def _build_steps(target_date: str, lane: str) -> list[Step]:
    if lane == "daily":
        return _build_daily_steps(target_date)
    if lane == "research":
        return _build_research_steps(target_date)
    if lane == "all":
        return _build_daily_steps(target_date) + _build_research_steps(target_date)
    raise ValueError(f"unknown after-close lane: {lane}")


def main() -> int:
    _apply_numeric_thread_defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=default_market_date())
    parser.add_argument("--lane", choices=["daily", "research", "all"], default="daily")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--rerun-completed",
        action="store_true",
        help="Ignore existing per-step completion markers for this target date.",
    )
    args = parser.parse_args()

    steps = _build_steps(args.date, args.lane)
    if args.rerun_completed:
        for step in steps:
            step.marker_path = None
    if args.dry_run:
        print(
            "After-close quant learning pipeline "
            f"— lane={args.lane} target_date={args.date}  [DRY RUN]"
        )
        print()
        for i, step in enumerate(steps, 1):
            crit = "CRITICAL" if step.critical else "warn-only"
            print(f"  {i}. [{crit}] {step.name}")
            print(f"       module : {step.module}")
            print(f"       argv   : {step.argv}")
            print(f"       memory : {step.memory_limit_mb or '-'} MB")
            print(f"       timeout: {step.timeout_seconds or '-'} sec")
            print(f"       marker : {step.marker_path or '-'}")
            if step.description:
                print(f"       desc   : {step.description}")
        return 0

    result = run_pipeline(f"after_close_{args.lane}", steps, args.date)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
