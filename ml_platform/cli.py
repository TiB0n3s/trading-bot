#!/usr/bin/env python3
"""ML platform CLI.

All commands are research/artifact commands. Nothing here affects broker/order
behavior or live paper-trading decisions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ml_platform.brain_features import (
    brain_feature_manifest,
    build_brain_feature_rows,
    write_brain_features_csv,
)
from ml_platform.config import DEFAULT_DB_PATH
from ml_platform.datasets import dataset_profile, write_profile
from ml_platform.experiments import create_experiment
from ml_platform.evaluation import default_evaluation_plan
from ml_platform.governance import (
    ENV_KILL_SWITCH_DEFAULTS,
    build_dataset_manifest,
    governance_contract,
    label_taxonomy,
    model_card_template,
)
from ml_platform.integration_contract import default_contract
from ml_platform.registry import load_registry, register_model
from ml_platform.readiness import retraining_readiness_report
from ml_platform.replay import replay_decisions_scaffold, replay_decisions_v1
from ml_platform.serving import SQLitePredictionProvider
from ml_platform.staged import staged_ml_integration_report, write_staged_report
from ml_platform.pit_context import get_archive_root, pit_coverage_for_range, select_pit_context
from ml_platform.validation import (
    EMBARGO_DEFAULT_DAYS,
    N_FOLDS_DEFAULT,
    PURGE_DEFAULT_DAYS,
    walk_forward_split_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ml_platform")
    sub = parser.add_subparsers(dest="command", required=True)

    profile = sub.add_parser("profile-dataset", help="Summarize ML table coverage")
    profile.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    profile.add_argument("--start-date")
    profile.add_argument("--end-date")
    profile.add_argument("--output")

    brain = sub.add_parser("export-brain-features", help="Export existing bot-brain features")
    brain.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    brain.add_argument("--date")
    brain.add_argument("--start-date")
    brain.add_argument("--end-date")
    brain.add_argument("--output", required=True)
    brain.add_argument("--manifest-output")

    create = sub.add_parser("create-experiment", help="Create an experiment scaffold")
    create.add_argument("name")
    create.add_argument("--dataset-start")
    create.add_argument("--dataset-end")
    create.add_argument("--target", default="ret_fwd_15m")
    create.add_argument("--notes", default="Research scaffold only. No runtime use.")

    register = sub.add_parser("register-model", help="Register model metadata")
    register.add_argument("--model-id", required=True)
    register.add_argument("--artifact-path", required=True)
    register.add_argument("--metrics-path", required=True)
    register.add_argument("--feature-version", required=True)
    register.add_argument("--target", required=True)
    register.add_argument("--training-window", required=True)
    register.add_argument("--validation-window", required=True)
    register.add_argument("--status", default="research")
    register.add_argument("--notes", default="Research only. No runtime use.")

    sub.add_parser("list-models", help="List registry contents")
    sub.add_parser("integration-contract", help="Print ML/brain promotion contract")
    sub.add_parser("evaluation-plan", help="Print default evaluation requirements")
    readiness = sub.add_parser("retraining-readiness", help="Print manual retraining readiness evidence")
    readiness.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    readiness.add_argument("--start-date")
    readiness.add_argument("--end-date")
    readiness.add_argument("--trading-sessions-observed", type=int, default=0)
    readiness.add_argument("--output")
    sub.add_parser("governance-contract", help="Print ML governance requirements")
    sub.add_parser("label-taxonomy", help="Print label taxonomy v1")
    sub.add_parser("env-policy", help="Print ML kill-switch defaults")

    manifest = sub.add_parser("dataset-manifest", help="Build a read-only dataset manifest")
    manifest.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    manifest.add_argument("--start-date")
    manifest.add_argument("--end-date")
    manifest.add_argument("--query-version", default="brain_features_query_v1")
    manifest.add_argument("--label-version", default="label_taxonomy_v1")
    manifest.add_argument("--output")

    model_card = sub.add_parser("model-card-template", help="Print a model-card template")
    model_card.add_argument("--model-id", default="candidate_model")

    replay = sub.add_parser("replay-decisions", help="Re-run decision_policy against stored snapshots (read-only)")
    replay.add_argument("--start-date", required=True)
    replay.add_argument("--end-date", required=True)
    replay.add_argument("--policy", default="current")
    replay.add_argument("--candidate-model", default="similarity_v0")
    replay.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    replay.add_argument("--friction-bps", type=float, default=10.0)
    replay.add_argument("--max-changed-rows", type=int, default=50)
    replay.add_argument("--output")

    staged = sub.add_parser("staged-readiness", help="Print staged observe-only ML integration report")
    staged.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    staged.add_argument("--start-date", required=True)
    staged.add_argument("--end-date", required=True)
    staged.add_argument("--policy", default="current")
    staged.add_argument("--candidate-model", required=True)
    staged.add_argument("--prediction-symbol")
    staged.add_argument("--output")

    pred = sub.add_parser("get-prediction", help="Read one observe-only prediction")
    pred.add_argument("--date", required=True)
    pred.add_argument("--symbol", required=True)

    pit = sub.add_parser(
        "pit-context-coverage",
        help="Show point-in-time context archive coverage for a date range",
    )
    pit.add_argument("--start-date", required=True)
    pit.add_argument("--end-date", required=True)
    pit.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    pit.add_argument("--output")

    wf = sub.add_parser(
        "walk-forward-splits",
        help="Build purged walk-forward fold specs and row counts",
    )
    wf.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    wf.add_argument("--start-date", required=True)
    wf.add_argument("--end-date", required=True)
    wf.add_argument("--n-folds", type=int, default=N_FOLDS_DEFAULT)
    wf.add_argument("--purge-days", type=int, default=PURGE_DEFAULT_DAYS)
    wf.add_argument("--embargo-days", type=int, default=EMBARGO_DEFAULT_DAYS)
    wf.add_argument("--min-train-days", type=int, default=15)
    wf.add_argument("--output")

    leak = sub.add_parser(
        "leakage-report",
        help="Symbol/date leakage audit for walk-forward splits",
    )
    leak.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    leak.add_argument("--start-date", required=True)
    leak.add_argument("--end-date", required=True)
    leak.add_argument("--n-folds", type=int, default=N_FOLDS_DEFAULT)
    leak.add_argument("--purge-days", type=int, default=PURGE_DEFAULT_DAYS)
    leak.add_argument("--embargo-days", type=int, default=EMBARGO_DEFAULT_DAYS)
    leak.add_argument("--min-train-days", type=int, default=15)
    leak.add_argument("--output")

    args = parser.parse_args()

    if args.command == "profile-dataset":
        result = dataset_profile(
            db_path=args.db_path,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        if args.output:
            path = write_profile(result, args.output)
            print(f"Wrote dataset profile to {path}")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "export-brain-features":
        rows = build_brain_feature_rows(
            db_path=args.db_path,
            date_arg=args.date,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        path = write_brain_features_csv(rows, args.output)
        manifest = brain_feature_manifest(rows)
        print(f"Wrote brain feature CSV to {path}")
        if args.manifest_output:
            manifest_path = Path(args.manifest_output)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            print(f"Wrote brain feature manifest to {manifest_path}")
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    if args.command == "create-experiment":
        path = create_experiment(
            args.name,
            dataset_start=args.dataset_start,
            dataset_end=args.dataset_end,
            target=args.target,
            notes=args.notes,
        )
        print(f"Created experiment scaffold: {path}")
        return 0

    if args.command == "register-model":
        entry = register_model(
            model_id=args.model_id,
            artifact_path=args.artifact_path,
            metrics_path=args.metrics_path,
            feature_version=args.feature_version,
            target=args.target,
            training_window=args.training_window,
            validation_window=args.validation_window,
            status=args.status,
            notes=args.notes,
        )
        print(json.dumps(entry, indent=2, sort_keys=True))
        return 0

    if args.command == "list-models":
        print(json.dumps(load_registry(), indent=2, sort_keys=True))
        return 0

    if args.command == "integration-contract":
        print(json.dumps(default_contract(), indent=2, sort_keys=True))
        return 0

    if args.command == "evaluation-plan":
        print(json.dumps(default_evaluation_plan(), indent=2, sort_keys=True))
        return 0

    if args.command == "retraining-readiness":
        profile_result = dataset_profile(
            db_path=args.db_path,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        manifest_result = build_dataset_manifest(
            db_path=args.db_path,
            start_date=args.start_date,
            end_date=args.end_date,
            query_version="retraining_readiness_v1",
        )
        result = retraining_readiness_report(
            dataset_profile=profile_result,
            dataset_manifest=manifest_result,
            trading_sessions_observed=args.trading_sessions_observed,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(f"Wrote retraining readiness report to {output_path}")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "governance-contract":
        print(json.dumps(governance_contract(), indent=2, sort_keys=True))
        return 0

    if args.command == "label-taxonomy":
        print(json.dumps(label_taxonomy(), indent=2, sort_keys=True))
        return 0

    if args.command == "env-policy":
        print(json.dumps(ENV_KILL_SWITCH_DEFAULTS, indent=2, sort_keys=True))
        return 0

    if args.command == "dataset-manifest":
        result = build_dataset_manifest(
            db_path=args.db_path,
            start_date=args.start_date,
            end_date=args.end_date,
            query_version=args.query_version,
            label_version=args.label_version,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(f"Wrote dataset manifest to {output_path}")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "model-card-template":
        print(json.dumps(model_card_template(args.model_id), indent=2, sort_keys=True))
        return 0

    if args.command == "replay-decisions":
        result = replay_decisions_v1(
            start_date=args.start_date,
            end_date=args.end_date,
            policy=args.policy,
            db_path=args.db_path,
            max_changed_rows=args.max_changed_rows,
            friction_bps=args.friction_bps,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(f"Wrote replay decisions report to {output_path}")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "staged-readiness":
        result = staged_ml_integration_report(
            db_path=args.db_path,
            start_date=args.start_date,
            end_date=args.end_date,
            policy=args.policy,
            candidate_model=args.candidate_model,
            prediction_symbol=args.prediction_symbol,
        )
        if args.output:
            path = write_staged_report(result, args.output)
            print(f"Wrote staged readiness report to {path}")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "get-prediction":
        provider = SQLitePredictionProvider()
        prediction = provider.get_prediction(args.date, args.symbol)
        print(json.dumps(prediction.to_dict() if prediction else None, indent=2, sort_keys=True))
        return 0

    if args.command == "pit-context-coverage":
        result = pit_coverage_for_range(
            args.start_date,
            args.end_date,
            archive_root=get_archive_root(Path(args.db_path).parent),
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(f"Wrote PIT context coverage to {output_path}")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command in ("walk-forward-splits", "leakage-report"):
        result = walk_forward_split_report(
            db_path=args.db_path,
            start_date=args.start_date,
            end_date=args.end_date,
            n_folds=args.n_folds,
            purge_days=args.purge_days,
            embargo_days=args.embargo_days,
            min_train_days=args.min_train_days,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(f"Wrote walk-forward split report to {output_path}")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
