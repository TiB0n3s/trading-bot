#!/usr/bin/env python3
"""Post-session review pipeline.

This replaces direct shell chaining in ``run_post_session_review.sh`` with
explicit critical/warn-only step semantics. Most review reports are diagnostic:
they should surface warnings without making the scheduled job look like a hard
runtime failure.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import Step, run_pipeline  # noqa: E402


def _build_steps(target_date: str) -> list[Step]:
    return [
        Step(
            name="post_session_operational_check",
            module="ops_check",
            argv=["post", target_date],
            critical=False,
            description="run post-session operational diagnostics",
        ),
        Step(
            name="rejected_signal_outcome_builder",
            module="rejected_signal_outcome_builder",
            argv=["--date", target_date],
            critical=False,
            description="complete rejected-signal forward outcomes",
        ),
        Step(
            name="rejected_outcomes_report",
            module="ops_check",
            argv=["rejected-outcomes", target_date],
            critical=False,
            description="summarize rejected outcome coverage",
        ),
        Step(
            name="decision_lifecycle_dashboard",
            module="ops_check",
            argv=["decision-lifecycle-dashboard", target_date],
            critical=False,
            description="join candidate, decision, execution, exit, and outcome evidence",
        ),
        Step(
            name="lifecycle_analysis",
            module="ops_check",
            argv=["lifecycle-analysis", target_date],
            critical=False,
            description="summarize approved/rejected lifecycle rows",
        ),
        Step(
            name="calibration_buckets",
            module="ops_check",
            argv=["calibration-buckets", target_date],
            critical=False,
            description="summarize realized calibration buckets",
        ),
        Step(
            name="post_trade_learning",
            module="ops_check",
            argv=["post-trade-learning", target_date],
            critical=False,
            description="summarize expectancy by learning buckets",
        ),
        Step(
            name="strong_day_participation",
            module="strong_day_participation_report",
            argv=["--date", target_date, "--write-db"],
            critical=False,
            description="write full-universe strong-day participation evidence",
        ),
        Step(
            name="tradingview_alert_coverage",
            module="tradingview_alert_coverage_report",
            argv=["--date", target_date],
            critical=False,
            description="audit legacy TradingView alert coverage",
        ),
        Step(
            name="historical_trend_context",
            module="build_historical_trend_context",
            argv=["--date", target_date],
            critical=False,
            description="refresh historical trend context",
        ),
        Step(
            name="predict_symbol_outcomes",
            module="predict_symbol_outcomes",
            argv=["--date", target_date],
            critical=False,
            description="refresh symbol outcome predictions",
        ),
        Step(
            name="prediction_validation",
            module="ops_check",
            argv=["prediction-validation", target_date],
            critical=False,
            description="validate cached predictions against outcomes",
        ),
        Step(
            name="automated_retraining",
            module="pipeline.retrain",
            argv=["--date", target_date, "--sessions", "5", "--bad-session-limit", "3"],
            critical=False,
            description="run guarded observe-only retraining",
        ),
        Step(
            name="auto_buy_report",
            module="ops_check",
            argv=["auto-buy", target_date],
            critical=False,
            description="summarize auto-buy candidates",
        ),
        Step(
            name="auto_buy_outcome_report",
            module="auto_buy_outcome_report",
            argv=["--date", target_date],
            critical=False,
            description="summarize auto-buy outcomes",
        ),
        Step(
            name="entry_quality_report",
            module="entry_quality_report",
            argv=["--date", target_date],
            critical=False,
            description="summarize entry quality evidence",
        ),
        Step(
            name="bar_timing_quality_report",
            module="bar_timing_quality_report",
            argv=["--date", target_date],
            critical=False,
            description="materialize and summarize best/good entry and exit bar timing labels",
        ),
        Step(
            name="decision_snapshots",
            module="ops_check",
            argv=["decision-snapshots", target_date],
            critical=False,
            description="audit decision snapshot persistence",
        ),
        Step(
            name="policy_artifacts",
            module="ops_check",
            argv=["policy-artifacts"],
            critical=False,
            description="audit policy artifact registry status",
        ),
        Step(
            name="analytics_report",
            module="analytics_report",
            argv=["--date", target_date],
            critical=False,
            description="summarize trade analytics",
        ),
        Step(
            name="filter_report",
            module="filter_report",
            argv=["--date", target_date],
            critical=False,
            description="summarize rejection filters",
        ),
        Step(
            name="learning_artifacts",
            module="ops_check",
            argv=["learning-artifacts", target_date],
            critical=False,
            description="audit learning artifact freshness",
        ),
        Step(
            name="historical_bar_coverage",
            module="ops_check",
            argv=["historical-bar-coverage", "--min-days", "252", "--min-symbols", "20"],
            critical=False,
            description="verify Polygon 1-minute bar ML history is deep enough for training claims",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    steps = _build_steps(args.date)
    if args.dry_run:
        print(f"Post-session review pipeline — target_date={args.date}  [DRY RUN]")
        print()
        for i, step in enumerate(steps, 1):
            crit = "CRITICAL" if step.critical else "warn-only"
            print(f"  {i}. [{crit}] {step.name}")
            print(f"       module : {step.module}")
            print(f"       argv   : {step.argv}")
            if step.description:
                print(f"       desc   : {step.description}")
        return 0

    result = run_pipeline("post_session_review", steps, args.date)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
