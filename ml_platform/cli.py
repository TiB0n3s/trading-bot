#!/usr/bin/env python3
"""ML platform CLI.

All commands are research/artifact commands. Nothing here affects broker/order
behavior or live paper-trading decisions.
"""

from __future__ import annotations

import argparse
import json

from db import DB_PATH
from ml_platform.datasets import dataset_profile, write_profile
from ml_platform.experiments import create_experiment
from ml_platform.registry import load_registry, register_model


def main() -> int:
    parser = argparse.ArgumentParser(prog="ml_platform")
    sub = parser.add_subparsers(dest="command", required=True)

    profile = sub.add_parser("profile-dataset", help="Summarize ML table coverage")
    profile.add_argument("--db-path", default=str(DB_PATH))
    profile.add_argument("--start-date")
    profile.add_argument("--end-date")
    profile.add_argument("--output")

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

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
