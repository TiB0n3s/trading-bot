#!/usr/bin/env python3
"""Audit historical candle coverage and run corrected feature checks.

This is read-only research tooling. It uses existing ``bar_pattern_features``
rows from the hot DB and optional cold archive DB to check whether historical
candle data spans enough symbols, dates, regimes, and forward labels to support
research claims. It can also export a flat CSV substrate and run the same
blocked/family-wise feature scan used by ``analyze_ml_edge.py``.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from analyze_ml_edge import EdgeRow, feature_lift_scan, feature_lift_scan_by_regime  # noqa: E402
from repositories.historical_bar_training_repo import (  # noqa: E402
    DEFAULT_HISTORICAL_BAR_ARCHIVE_DB,
    HISTORICAL_BAR_TRAINING_COLUMNS,
    fetch_historical_bar_training_rows,
)

DEFAULT_DB_PATH = ROOT / "trades.db"
DEFAULT_GROUP_FIELDS = (
    "symbol",
    "trend_scan_label",
    "pattern_label",
    "opportunity_action",
    "triple_barrier_reason",
    "day_of_week",
    "minute_bucket",
)
TARGET_COLUMNS = {
    "trend_scan_return_pct",
    "trend_scan_label",
    "triple_barrier_label",
    "triple_barrier_reason",
    "triple_barrier_bars_to_event",
    "triple_barrier_profit_pct",
    "triple_barrier_stop_pct",
}
IDENTITY_COLUMNS = {
    "symbol",
    "bar_timestamp",
    "feature_version",
    "pattern_label",
    "opportunity_action",
    "opportunity_quality",
    "triple_barrier_reason",
}


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _date(value: Any) -> str | None:
    text = str(value or "")
    return text[:10] if len(text) >= 10 else None


def _minute_bucket(value: Any) -> str:
    text = str(value or "")
    try:
        minute = int(text[14:16])
        hour = int(text[11:13])
    except (TypeError, ValueError):
        return "unknown"
    minute_of_day = hour * 60 + minute
    bucket = (minute_of_day // 30) * 30
    return f"{bucket:04d}-{bucket + 29:04d}"


def _outcome(row: dict[str, Any], target: str) -> float | None:
    if target == "trend_scan_return_pct":
        return _float(row.get("trend_scan_return_pct"))
    if target in {"triple_barrier_label", "triple_barrier"}:
        label = _float(row.get("triple_barrier_label"))
        if label is None:
            return None
        if label > 0:
            return _float(row.get("triple_barrier_profit_pct")) or 1.0
        if label < 0:
            stop = _float(row.get("triple_barrier_stop_pct"))
            return -abs(stop if stop is not None else 1.0)
        return 0.0
    return _float(row.get(target))


def _categorical_features(row: dict[str, Any]) -> dict[str, str]:
    features: dict[str, str] = {}
    for label_key in ("trend_scan_label", "triple_barrier_label"):
        if row.get(label_key) not in (None, ""):
            features[label_key] = str(row[label_key])
    for key, value in row.items():
        if value in (None, ""):
            continue
        if key in {"symbol", "bar_timestamp"}:
            continue
        if _float(value) is not None:
            continue
        features[key] = str(value)
    features["minute_bucket"] = _minute_bucket(row.get("bar_timestamp"))
    market_date = _date(row.get("bar_timestamp"))
    if market_date:
        features["market_date"] = market_date
    return features


def _numeric_features(row: dict[str, Any], *, target: str) -> dict[str, float]:
    features: dict[str, float] = {}
    excluded = set(TARGET_COLUMNS)
    excluded.add(target)
    for key, value in row.items():
        if key in excluded or key in IDENTITY_COLUMNS:
            continue
        number = _float(value)
        if number is not None:
            features[key] = number
    return features


def rows_to_edge_rows(rows: list[dict[str, Any]], *, target: str) -> list[EdgeRow]:
    edge_rows: list[EdgeRow] = []
    for row in rows:
        outcome = _outcome(row, target)
        if outcome is None:
            continue
        edge_rows.append(
            EdgeRow(
                source="historical_bar_pattern_features",
                symbol=str(row.get("symbol") or "").upper() or None,
                market_date=_date(row.get("bar_timestamp")),
                decision="historical_bar_research",
                score=None,
                confluence_score=None,
                conviction_score=None,
                setup_score=_float(row.get("pattern_score")),
                probability_pct=None,
                probability_source=None,
                instruction="none",
                instruction_class="unknown",
                forward_return_pct=outcome,
                forward_mfe_pct=_float(row.get("triple_barrier_profit_pct")),
                numeric_features=_numeric_features(row, target=target),
                categorical_features=_categorical_features(row),
            )
        )
    return edge_rows


def _summary_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "win_pct": None, "mean_return_pct": None, "median_return_pct": None}
    return {
        "n": len(values),
        "win_pct": round(100.0 * sum(1 for value in values if value > 0) / len(values), 2),
        "mean_return_pct": round(statistics.mean(values), 6),
        "median_return_pct": round(statistics.median(values), 6),
    }


def baseline_by_group(
    edge_rows: list[EdgeRow],
    *,
    group_field: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in edge_rows:
        if row.forward_return_pct is None:
            continue
        if group_field == "symbol":
            value = row.symbol or "unknown"
        elif group_field == "market_date":
            value = row.market_date or "unknown"
        else:
            value = row.categorical_features.get(group_field)
            if value is None and group_field in row.numeric_features:
                value = str(row.numeric_features[group_field])
            value = value or "unknown"
        grouped[str(value)].append(float(row.forward_return_pct))
    result = [{"group": group, **_summary_stats(values)} for group, values in grouped.items()]
    result.sort(key=lambda item: (-int(item["n"]), item["group"]))
    return result[:limit]


def coverage_summary(rows: list[dict[str, Any]], edge_rows: list[EdgeRow]) -> dict[str, Any]:
    dates = sorted({row.market_date for row in edge_rows if row.market_date})
    symbols = sorted({row.symbol for row in edge_rows if row.symbol})
    labels = Counter(
        str(row.get("triple_barrier_label"))
        for row in rows
        if row.get("triple_barrier_label") is not None
    )
    trend_labels = Counter(
        str(row.get("trend_scan_label")) for row in rows if row.get("trend_scan_label") is not None
    )
    patterns = Counter(str(row.get("pattern_label") or "unknown") for row in rows)
    return {
        "rows": len(rows),
        "labeled_rows": len(edge_rows),
        "symbols": len(symbols),
        "market_dates": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "triple_barrier_labels": dict(sorted(labels.items())),
        "trend_scan_labels": dict(sorted(trend_labels.items())),
        "top_patterns": dict(patterns.most_common(12)),
    }


def write_flat_csv(rows: list[dict[str, Any]], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(HISTORICAL_BAR_TRAINING_COLUMNS)
    with output.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})
    return output


def build_historical_market_view_payload(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    archive_db_path: Path | str | None = DEFAULT_HISTORICAL_BAR_ARCHIVE_DB,
    start_date: str | None = None,
    end_date: str | None = None,
    symbol: str | None = None,
    target: str = "trend_scan_return_pct",
    limit: int = 50000,
    rows_per_symbol: int = 0,
    feature_min_rows: int = 100,
    feature_permutations: int = 200,
    regime_field: str = "trend_scan_label",
    max_features: int = 15,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    label_target = (
        "triple_barrier_label"
        if target in {"triple_barrier", "triple_barrier_label"}
        else "trend_scan_label"
    )
    rows = fetch_historical_bar_training_rows(
        db_path=db_path,
        archive_db_path=archive_db_path,
        start_date=start_date,
        end_date=end_date,
        symbol=symbol,
        label_target=label_target,
        limit=limit,
        rows_per_symbol=rows_per_symbol,
    )
    edge_rows = rows_to_edge_rows(rows, target=target)
    groups = {
        field: baseline_by_group(edge_rows, group_field=field) for field in DEFAULT_GROUP_FIELDS
    }
    feature_scan = feature_lift_scan(
        edge_rows,
        min_rows=feature_min_rows,
        permutations=feature_permutations,
        permutation_block_field="market_date",
    )[:max_features]
    regime_scan = feature_lift_scan_by_regime(
        edge_rows,
        regime_field=regime_field,
        min_rows=feature_min_rows,
        permutations=feature_permutations,
        permutation_block_field="market_date",
    )[:10]
    payload = {
        "report_version": "historical_market_view_v1",
        "runtime_effect": "read_only_research_no_live_authority",
        "db_path": str(db_path),
        "archive_db_path": str(archive_db_path) if archive_db_path else None,
        "start_date": start_date,
        "end_date": end_date,
        "symbol": symbol.upper() if symbol else None,
        "target": target,
        "coverage": coverage_summary(rows, edge_rows),
        "overall_baseline": _summary_stats(
            [
                float(row.forward_return_pct)
                for row in edge_rows
                if row.forward_return_pct is not None
            ]
        ),
        "baselines": groups,
        "feature_scan": feature_scan,
        "regime_feature_scan": regime_scan,
        "promotion_note": (
            "Historical candle breadth can validate coverage and test hypotheses, "
            "but this report does not grant auto-buy authority."
        ),
    }
    return payload, rows


def compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the operator-facing summary without large decile bucket payloads."""
    return {
        "report_version": payload.get("report_version"),
        "runtime_effect": payload.get("runtime_effect"),
        "target": payload.get("target"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "symbol": payload.get("symbol"),
        "coverage": payload.get("coverage"),
        "overall_baseline": payload.get("overall_baseline"),
        "top_baselines": {
            key: values[:5] for key, values in (payload.get("baselines") or {}).items()
        },
        "top_features": [
            {
                "feature": item.get("feature"),
                "n": item.get("n"),
                "lift_pct": item.get("lift_pct"),
                "monotonicity": item.get("monotonicity"),
                "verdict": item.get("verdict"),
                "null_verdict": item.get("null_verdict"),
                "family_verdict": item.get("family_verdict"),
                "family_p_value": item.get("family_p_value"),
            }
            for item in (payload.get("feature_scan") or [])[:10]
        ],
        "regime_feature_counts": [
            {
                "regime": item.get("regime"),
                "n": item.get("n"),
                "mean_return_pct": item.get("mean_return_pct"),
                "features": len(item.get("features") or []),
            }
            for item in (payload.get("regime_feature_scan") or [])
        ],
        "promotion_note": payload.get("promotion_note"),
        "flat_output": payload.get("flat_output"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--archive-db-path", default=str(DEFAULT_HISTORICAL_BAR_ARCHIVE_DB))
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--symbol")
    parser.add_argument(
        "--target",
        default="trend_scan_return_pct",
        choices=("trend_scan_return_pct", "triple_barrier_label", "triple_barrier"),
    )
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--rows-per-symbol", type=int, default=0)
    parser.add_argument("--feature-min-rows", type=int, default=100)
    parser.add_argument("--feature-permutations", type=int, default=200)
    parser.add_argument("--regime-field", default="trend_scan_label")
    parser.add_argument("--max-features", type=int, default=15)
    parser.add_argument("--flat-output", help="Optional CSV export for the flat research substrate")
    parser.add_argument("--json-output", help="Optional JSON report output")
    parser.add_argument(
        "--print-full-json",
        action="store_true",
        help="Print the full report, including all decile buckets. Default prints a compact summary.",
    )
    args = parser.parse_args(argv)

    archive_db_path = None if args.no_archive else args.archive_db_path
    payload, rows = build_historical_market_view_payload(
        db_path=args.db_path,
        archive_db_path=archive_db_path,
        start_date=args.start_date,
        end_date=args.end_date,
        symbol=args.symbol,
        target=args.target,
        limit=args.limit,
        rows_per_symbol=args.rows_per_symbol,
        feature_min_rows=args.feature_min_rows,
        feature_permutations=args.feature_permutations,
        regime_field=args.regime_field,
        max_features=args.max_features,
    )
    if args.flat_output:
        payload["flat_output"] = str(write_flat_csv(rows, Path(args.flat_output)))
    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    printed_payload = payload if args.print_full_json else compact_payload(payload)
    print(json.dumps(printed_payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
