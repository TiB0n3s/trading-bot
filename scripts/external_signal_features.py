#!/usr/bin/env python3
"""Point-in-time external signal feature ingestion and research scans."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from analyze_ml_edge import (  # noqa: E402
    EdgeRow,
    feature_lift_scan,
    load_candidate_universe,
    load_rejected_outcomes,
)
from repositories.external_signal_feature_repo import (  # noqa: E402
    ExternalSignalFeatureRepository,
    feature_from_mapping,
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                loaded = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(loaded, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(loaded)
    return rows


def enrich_rows_with_external_features(
    rows: list[EdgeRow],
    repo: ExternalSignalFeatureRepository,
) -> list[EdgeRow]:
    enriched: list[EdgeRow] = []
    for row in rows:
        if not row.symbol:
            enriched.append(row)
            continue
        decision_ts = row.categorical_features.get("decision_ts") or row.market_date
        if not decision_ts:
            enriched.append(row)
            continue
        as_of = repo.as_of_features(symbol=row.symbol, decision_ts=decision_ts)
        numeric = dict(row.numeric_features)
        categorical = dict(row.categorical_features)
        for key, feature in as_of.items():
            if feature.get("feature_value_numeric") is not None:
                numeric[key] = float(feature["feature_value_numeric"])
            if feature.get("feature_value_text") not in (None, ""):
                categorical[key] = str(feature["feature_value_text"])
            categorical[f"{key}.source"] = str(feature.get("source") or "")
            categorical[f"{key}.revision_policy"] = str(feature.get("revision_policy") or "")
        enriched.append(replace(row, numeric_features=numeric, categorical_features=categorical))
    return enriched


def _connect_ro(db_path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(ROOT / "trades.db"))
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest-jsonl")
    ingest.add_argument("--input", required=True)

    scan = sub.add_parser("scan-candidates")
    scan.add_argument("--start-date")
    scan.add_argument("--end-date")
    scan.add_argument("--limit", type=int, default=0)
    scan.add_argument("--min-rows", type=int, default=100)
    scan.add_argument("--permutations", type=int, default=200)
    scan.add_argument("--max-features", type=int, default=25)
    scan.add_argument("--json-output")

    args = parser.parse_args(argv)
    repo = ExternalSignalFeatureRepository(args.db_path)

    if args.command == "ingest-jsonl":
        payloads = _load_jsonl(Path(args.input))
        features = [feature_from_mapping(payload) for payload in payloads]
        changed = repo.upsert_many(features)
        result = {
            "report_version": "external_signal_feature_ingest_v1",
            "runtime_effect": "research_feature_ingest_no_trade_authority",
            "input": args.input,
            "features_read": len(features),
            "rows_changed": changed,
            "leakage_violations": repo.leakage_violations(),
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    with _connect_ro(args.db_path) as con:
        rows = load_candidate_universe(
            con,
            args.start_date,
            args.end_date,
            args.limit or None,
        ) + load_rejected_outcomes(
            con,
            args.start_date,
            args.end_date,
            args.limit or None,
        )
    enriched = enrich_rows_with_external_features(rows, repo)
    results = feature_lift_scan(
        enriched,
        min_rows=args.min_rows,
        permutations=args.permutations,
        permutation_block_field="market_date",
    )[: args.max_features]
    payload = {
        "report_version": "external_signal_feature_candidate_scan_v1",
        "runtime_effect": "research_scan_no_trade_authority",
        "rows": len(rows),
        "rows_with_outcome": sum(1 for row in enriched if row.forward_return_pct is not None),
        "external_feature_rows": len(repo.rows_between(start=args.start_date, end=args.end_date)),
        "leakage_violations": repo.leakage_violations(),
        "feature_scan": results,
    }
    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
