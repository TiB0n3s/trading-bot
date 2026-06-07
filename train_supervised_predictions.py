#!/usr/bin/env python3
"""Train/evaluate the observe-only supervised prediction scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from repositories.historical_bar_coverage_repo import HistoricalBarCoverageRepository
from services.supervised_prediction_training_service import (
    DEFAULT_FEATURE_COLUMNS,
    fetch_training_rows,
    train_quant_model_suite,
    train_supervised_prediction_model,
)
from symbols_config import APPROVED_SYMBOLS_LIST


HISTORICAL_BAR_CACHE_DIR = Path("data") / "historical_bars" / "polygon_1min"
DEFAULT_DB_PATH = Path("trades.db")
DIRECT_BAR_FEATURE_COLUMNS = tuple(
    column for column in DEFAULT_FEATURE_COLUMNS
    if column not in {
        "ret_1m",
        "ret_5m",
        "ret_15m",
        "range_pos_15m",
        "distance_from_vwap",
        "volume_ratio_5m",
        "relative_strength_5m",
        "spread_pct",
        "setup_score",
    }
)


def _coverage_scope(
    *,
    start_date: str | None,
    end_date: str | None,
    min_symbol_days: int,
) -> dict:
    cache_scope = _coverage_scope_from_cache(
        start_date=start_date,
        end_date=end_date,
        min_symbol_days=min_symbol_days,
    )
    if cache_scope.get("coverage_available"):
        return cache_scope

    payload = HistoricalBarCoverageRepository().symbol_progress_payload(
        start_date=start_date,
        end_date=end_date,
        symbols=APPROVED_SYMBOLS_LIST,
    )
    if not payload or not payload.get("table_exists"):
        return {
            "coverage_available": False,
            "ready_symbols": [],
            "excluded_symbols": [],
            "symbols_ready": 0,
            "symbols_seen": 0,
            "min_symbol_days": min_symbol_days,
        }

    symbol_rows = payload.get("symbol_rows") or []
    ready = sorted(
        str(row.get("symbol") or "").upper()
        for row in symbol_rows
        if int(row.get("market_dates") or 0) >= min_symbol_days
    )
    seen = sorted(
        str(row.get("symbol") or "").upper()
        for row in symbol_rows
        if str(row.get("symbol") or "").strip()
    )
    return {
        "coverage_available": True,
        "ready_symbols": ready,
        "excluded_symbols": sorted(set(seen) - set(ready)),
        "symbols_ready": len(ready),
        "symbols_seen": len(seen),
        "min_symbol_days": min_symbol_days,
        "coverage_start_date": start_date,
        "coverage_end_date": end_date,
        "coverage_basis": "bar_pattern_features_db",
    }


def _coverage_scope_from_cache(
    *,
    start_date: str | None,
    end_date: str | None,
    min_symbol_days: int,
) -> dict:
    base = HISTORICAL_BAR_CACHE_DIR
    if not base.exists():
        return {"coverage_available": False}

    row_counts = {symbol: 0 for symbol in APPROVED_SYMBOLS_LIST}
    chunk_counts = {symbol: 0 for symbol in APPROVED_SYMBOLS_LIST}
    for path in base.glob("*_1min_rth_*.csv"):
        name = path.name
        symbol = name.split("_1min_rth_", 1)[0].upper()
        if symbol not in row_counts:
            continue
        try:
            _prefix, dates = name.split("_1min_rth_", 1)
            chunk_start, chunk_end = dates.removesuffix(".csv").split("_", 1)
        except ValueError:
            chunk_start = chunk_end = None
        if start_date and chunk_end and chunk_end < start_date:
            continue
        if end_date and chunk_start and chunk_start > end_date:
            continue
        try:
            with path.open() as fh:
                rows = max(0, sum(1 for _ in fh) - 1)
        except Exception:
            rows = 0
        row_counts[symbol] += rows
        chunk_counts[symbol] += 1

    # RTH equity sessions have at most 390 one-minute bars. Using 350 keeps
    # the scope conservative while tolerating exchange holidays/short sessions.
    row_floor = int(min_symbol_days) * 350
    ready = sorted(symbol for symbol, rows in row_counts.items() if rows >= row_floor)
    seen = sorted(symbol for symbol, chunks in chunk_counts.items() if chunks > 0)
    return {
        "coverage_available": bool(seen),
        "ready_symbols": ready,
        "excluded_symbols": sorted(set(APPROVED_SYMBOLS_LIST) - set(ready)),
        "symbols_ready": len(ready),
        "symbols_seen": len(APPROVED_SYMBOLS_LIST),
        "min_symbol_days": min_symbol_days,
        "row_floor": row_floor,
        "coverage_start_date": start_date,
        "coverage_end_date": end_date,
        "coverage_basis": "polygon_csv_cache_row_floor",
    }


def _fetch_direct_bar_pattern_rows(
    *,
    symbols: list[str],
    horizon: str,
    per_symbol_limit: int,
    total_limit: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict]:
    if horizon in {"triple_barrier", "triple_barrier_label"}:
        label_column = "triple_barrier_label"
    elif horizon in {"trend_scan", "trend_scan_label"}:
        label_column = "trend_scan_label"
    else:
        raise ValueError(
            "--bar-pattern-direct currently supports triple_barrier or trend_scan horizons"
        )

    wanted = sorted(set(DIRECT_BAR_FEATURE_COLUMNS) | {
        "symbol",
        "bar_timestamp",
        "triple_barrier_label",
        "trend_scan_label",
    })
    return HistoricalBarCoverageRepository(db_path).direct_bar_pattern_rows(
        symbols=symbols,
        label_column=label_column,
        wanted_columns=wanted,
        per_symbol_limit=per_symbol_limit,
        total_limit=total_limit,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol")
    parser.add_argument(
        "--horizon",
        default="15m",
        choices=("5m", "15m", "30m", "triple_barrier", "triple_barrier_label", "trend_scan", "trend_scan_label"),
    )
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--min-samples", type=int, default=40)
    parser.add_argument("--artifact-output", default="ml/models/supervised_entry_v1/model.joblib")
    parser.add_argument("--artifact-dir", default="ml/models/partial_universe_entry_v1")
    parser.add_argument("--suite", action="store_true", help="Train the observe-only quant model suite")
    parser.add_argument("--model-id-prefix", default="partial_universe_entry_v1")
    parser.add_argument("--partial-universe", action="store_true")
    parser.add_argument(
        "--bar-pattern-direct",
        action="store_true",
        help="Train directly from historical bar_pattern_features instead of decision snapshots.",
    )
    parser.add_argument("--coverage-start-date")
    parser.add_argument("--coverage-end-date")
    parser.add_argument("--min-symbol-days", type=int, default=252)
    parser.add_argument("--per-symbol-limit", type=int, default=500)
    parser.add_argument("--metrics-output")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows = []
    scope = None
    if args.partial_universe:
        scope = _coverage_scope(
            start_date=args.coverage_start_date,
            end_date=args.coverage_end_date,
            min_symbol_days=args.min_symbol_days,
        )
        ready_symbols = set(scope.get("ready_symbols") or [])
        per_symbol_limit = max(1, int(args.per_symbol_limit))
        if args.bar_pattern_direct:
            rows = _fetch_direct_bar_pattern_rows(
                symbols=sorted(ready_symbols),
                horizon=args.horizon,
                per_symbol_limit=per_symbol_limit,
                total_limit=args.limit,
            )
        else:
            for symbol in sorted(ready_symbols):
                rows.extend(fetch_training_rows(symbol=symbol, limit=per_symbol_limit))
                if len(rows) >= args.limit:
                    rows = rows[: args.limit]
                    break
    else:
        rows = fetch_training_rows(symbol=args.symbol, limit=args.limit)

    if args.suite:
        result = train_quant_model_suite(
            rows=rows,
            horizon=args.horizon,
            feature_columns=list(DIRECT_BAR_FEATURE_COLUMNS) if args.bar_pattern_direct else None,
            min_samples=args.min_samples,
            artifact_dir=args.artifact_dir,
            model_id_prefix=args.model_id_prefix,
        ).to_dict()
        artifact = (result.get("best_model") or {}).get("artifact_path")
    else:
        result = train_supervised_prediction_model(
            rows=rows,
            horizon=args.horizon,
            feature_columns=list(DIRECT_BAR_FEATURE_COLUMNS) if args.bar_pattern_direct else None,
            min_samples=args.min_samples,
            artifact_path=args.artifact_output,
        ).to_dict()
        artifact = result.get("artifact_path")

    result["training_scope"] = (
        "partial_universe"
        if args.partial_universe
        else ("single_symbol" if args.symbol else "all_available_rows")
    )
    result["scope_metadata"] = scope or {}
    result["artifact_for_registry"] = artifact
    result["training_input"] = (
        "bar_pattern_features_direct"
        if args.bar_pattern_direct
        else "feature_snapshots_joined_to_bar_pattern_features"
    )

    if args.metrics_output:
        from pathlib import Path

        path = Path(args.metrics_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("=== Supervised Prediction Training ===")
        if args.suite:
            best = result.get("best_model") or {}
            print(f"provider       : {best.get('provider') or 'none'}")
            print(f"trained        : {bool(best)}")
        else:
            print(f"provider       : {result['provider']}")
            print(f"trained        : {result['trained']}")
        print(f"sample_size    : {result['sample_size']}")
        if args.suite:
            best = result.get("best_model") or {}
            print(f"accuracy       : {best.get('accuracy')}")
            print(f"positive_rate  : {best.get('baseline_positive_rate')}")
            print(f"reason         : {best.get('reason')}")
        else:
            print(f"accuracy       : {result['accuracy']}")
            print(f"positive_rate  : {result['baseline_positive_rate']}")
            print(f"reason         : {result['reason']}")
        print(f"scope          : {result['training_scope']}")
        if scope:
            print(f"symbols_ready  : {scope['symbols_ready']}/{scope['symbols_seen']}")
            print(f"min_days       : {scope['min_symbol_days']}")
        print(f"artifact       : {artifact}")
        if args.metrics_output:
            print(f"metrics        : {args.metrics_output}")
        missing = result["dependency_status"].get("missing") or []
        if missing:
            print(f"missing deps   : {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
