#!/usr/bin/env python3
"""Research-only post-earnings drift ingestion and scans."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from analyze_ml_edge import EdgeRow, feature_lift_scan, feature_lift_scan_by_regime  # noqa: E402
from repositories.external_signal_feature_repo import (  # noqa: E402
    ExternalSignalFeature,
    ExternalSignalFeatureRepository,
)

from trading_bot.research.expected_value import (  # noqa: E402
    ExpectedValueAssumptions,
    evaluate_expected_value,
)

REPORT_VERSION = "post_earnings_drift_research_v1"
RUNTIME_EFFECT = "research_only_no_trade_authority"
REQUIRED_EVENT_FIELDS = ("symbol", "available_at", "source")
EVENT_TIMESTAMP_FIELDS = ("earnings_ts", "event_ts", "feature_ts")
RESERVED_EVENT_FIELDS = {
    "symbol",
    "earnings_ts",
    "event_ts",
    "feature_ts",
    "available_at",
    "source",
    "source_url",
    "source_url_or_ref",
    "revision_policy",
    "raw_json",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(payload)
    return rows


def _clean_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    return symbol


def _required_ts(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    raise ValueError(f"one of {', '.join(keys)} is required")


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _scalar_items(payload: dict[str, Any]) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for key, value in payload.items():
        if key in RESERVED_EVENT_FIELDS or value in (None, ""):
            continue
        if isinstance(value, str | int | float | bool):
            items.append((key, value))
    return items


def validate_earnings_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    symbols: set[str] = set()
    sources: set[str] = set()
    scalar_feature_names: set[str] = set()
    rows_with_surprise = 0
    for idx, payload in enumerate(payloads, start=1):
        row_errors: list[str] = []
        for field in REQUIRED_EVENT_FIELDS:
            if str(payload.get(field) or "").strip() == "":
                row_errors.append(f"missing_{field}")
        if not any(str(payload.get(field) or "").strip() for field in EVENT_TIMESTAMP_FIELDS):
            row_errors.append("missing_event_timestamp")
        feature_ts = next(
            (
                str(payload.get(field) or "").strip()
                for field in EVENT_TIMESTAMP_FIELDS
                if str(payload.get(field) or "").strip()
            ),
            "",
        )
        available_at = str(payload.get("available_at") or "").strip()
        revision_policy = str(payload.get("revision_policy") or "point_in_time_as_reported")
        if (
            feature_ts
            and available_at
            and available_at < feature_ts
            and revision_policy
            not in {"scheduled_known_before_event", "calendar_known_before_event"}
        ):
            row_errors.append("available_at_before_event_timestamp")
        scalar_items = _scalar_items(payload)
        if not scalar_items:
            warnings.append({"row": idx, "warning": "no_scalar_earnings_features"})
        if any("surprise" in key.lower() for key, _value in scalar_items):
            rows_with_surprise += 1
        scalar_feature_names.update(key for key, _value in scalar_items)
        if payload.get("symbol"):
            symbols.add(str(payload["symbol"]).upper())
        if payload.get("source"):
            sources.add(str(payload["source"]))
        if row_errors:
            errors.append({"row": idx, "errors": row_errors})

    return {
        "report_version": "post_earnings_drift_input_validation_v1",
        "runtime_effect": RUNTIME_EFFECT,
        "rows": len(payloads),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "symbols": len(symbols),
        "sources": sorted(sources),
        "scalar_feature_names": sorted(scalar_feature_names),
        "rows_with_surprise_fields": rows_with_surprise,
    }


def earnings_payload_to_features(payload: dict[str, Any]) -> list[ExternalSignalFeature]:
    symbol = _clean_symbol(payload.get("symbol"))
    feature_ts = _required_ts(payload, "earnings_ts", "event_ts", "feature_ts")
    available_at = _required_ts(payload, "available_at")
    source = str(payload.get("source") or "earnings_event_jsonl")
    source_ref = payload.get("source_url_or_ref") or payload.get("source_url")
    revision_policy = str(payload.get("revision_policy") or "point_in_time_as_reported")
    raw_json = dict(payload)
    features = [
        ExternalSignalFeature(
            symbol=symbol,
            feature_ts=feature_ts,
            available_at=available_at,
            source=source,
            feature_family="earnings",
            feature_name="event_observed",
            feature_value_numeric=1.0,
            source_url_or_ref=str(source_ref) if source_ref else None,
            revision_policy=revision_policy,
            raw_json=raw_json,
        )
    ]
    for key, value in _scalar_items(payload):
        numeric = _float(value)
        features.append(
            ExternalSignalFeature(
                symbol=symbol,
                feature_ts=feature_ts,
                available_at=available_at,
                source=source,
                feature_family="earnings",
                feature_name=key,
                feature_value_numeric=numeric,
                feature_value_text=None if numeric is not None else str(value),
                source_url_or_ref=str(source_ref) if source_ref else None,
                revision_policy=revision_policy,
                raw_json=raw_json,
            )
        )
    return features


def _connect_ro(db_path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _has_table(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _bar_price_rows(
    con: sqlite3.Connection, symbol: str, available_at: str
) -> list[dict[str, Any]]:
    if not _has_table(con, "bar_pattern_features"):
        return []
    rows = con.execute(
        """
        SELECT symbol, bar_timestamp, open, close
        FROM bar_pattern_features
        WHERE symbol = ?
          AND timeframe = '1m'
          AND bar_timestamp >= ?
          AND close IS NOT NULL
        ORDER BY bar_timestamp ASC
        """,
        (symbol, available_at),
    ).fetchall()
    return [dict(row) for row in rows]


def _prior_close(con: sqlite3.Connection, symbol: str, available_at: str) -> float | None:
    if not _has_table(con, "bar_pattern_features"):
        return None
    row = con.execute(
        """
        SELECT close
        FROM bar_pattern_features
        WHERE symbol = ?
          AND timeframe = '1m'
          AND bar_timestamp < ?
          AND close IS NOT NULL
        ORDER BY bar_timestamp DESC
        LIMIT 1
        """,
        (symbol, available_at),
    ).fetchone()
    return _float(row["close"]) if row else None


def _market_date(timestamp: Any) -> str | None:
    text = str(timestamp or "")
    return text[:10] if len(text) >= 10 else None


def _close_by_session(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        market_date = _market_date(row.get("bar_timestamp"))
        if not market_date:
            continue
        by_date[market_date] = row
    return [by_date[key] for key in sorted(by_date)]


def _event_groups(repo: ExternalSignalFeatureRepository, start: str | None, end: str | None):
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in repo.rows_between(start=start, end=end):
        if row.get("feature_family") != "earnings":
            continue
        key = (
            str(row.get("symbol") or "").upper(),
            str(row.get("feature_ts") or ""),
            str(row.get("available_at") or ""),
            str(row.get("source") or ""),
        )
        grouped[key].append(row)
    return grouped


def _edge_row_for_event(
    *,
    con: sqlite3.Connection,
    event_rows: list[dict[str, Any]],
    horizon_sessions: int,
) -> EdgeRow | None:
    first = event_rows[0]
    symbol = str(first["symbol"]).upper()
    available_at = str(first["available_at"])
    bars = _bar_price_rows(con, symbol, available_at)
    sessions = _close_by_session(bars)
    if len(sessions) < horizon_sessions:
        return None

    entry = bars[0]
    exit_bar = sessions[horizon_sessions - 1]
    entry_price = _float(entry.get("open")) or _float(entry.get("close"))
    exit_price = _float(exit_bar.get("close"))
    if entry_price is None or exit_price is None or entry_price <= 0:
        return None

    prior_close = _prior_close(con, symbol, available_at)
    forward_return = (exit_price - entry_price) / entry_price * 100.0
    numeric = {
        "earnings.event_observed": 1.0,
        "earnings.horizon_sessions": float(horizon_sessions),
        "earnings.entry_price": entry_price,
    }
    if prior_close and prior_close > 0:
        numeric["earnings.post_event_gap_pct"] = (entry_price - prior_close) / prior_close * 100.0
    categorical = {
        "decision_ts": available_at,
        "event_ts": str(first.get("feature_ts") or ""),
        "event_source": str(first.get("source") or ""),
        "market_date": _market_date(entry.get("bar_timestamp")) or "",
        "exit_market_date": _market_date(exit_bar.get("bar_timestamp")) or "",
    }
    for row in event_rows:
        name = str(row.get("feature_name") or "")
        if not name:
            continue
        numeric_value = _float(row.get("feature_value_numeric"))
        text_value = row.get("feature_value_text")
        key = f"earnings.{name}"
        if numeric_value is not None:
            numeric[key] = numeric_value
        elif text_value not in (None, ""):
            categorical[key] = str(text_value)

    return EdgeRow(
        source="post_earnings_drift_research",
        symbol=symbol,
        market_date=_market_date(entry.get("bar_timestamp")),
        decision="research_only",
        score=None,
        confluence_score=None,
        conviction_score=None,
        setup_score=None,
        probability_pct=None,
        probability_source=None,
        instruction="none",
        instruction_class="unknown",
        forward_return_pct=forward_return,
        forward_mfe_pct=None,
        numeric_features=numeric,
        categorical_features=categorical,
    )


def build_post_earnings_drift_payload(
    *,
    db_path: Path | str,
    start: str | None,
    end: str | None,
    horizon_sessions: int,
    min_rows: int,
    permutations: int,
    spread_pct: float,
    slippage_pct: float,
    account_equity: float | None,
    max_position_pct: float,
) -> tuple[dict[str, Any], list[EdgeRow]]:
    repo = ExternalSignalFeatureRepository(db_path)
    groups = _event_groups(repo, start, end)
    edge_rows: list[EdgeRow] = []
    with _connect_ro(db_path) as con:
        for rows in groups.values():
            edge_row = _edge_row_for_event(
                con=con,
                event_rows=rows,
                horizon_sessions=horizon_sessions,
            )
            if edge_row is not None:
                edge_rows.append(edge_row)

    assumptions = ExpectedValueAssumptions(
        spread_pct=spread_pct,
        slippage_pct=slippage_pct,
        account_equity=account_equity,
        max_position_pct=max_position_pct,
        reference_price=(
            sum(row.numeric_features["earnings.entry_price"] for row in edge_rows) / len(edge_rows)
            if edge_rows
            else None
        ),
    )
    returns = [row.forward_return_pct for row in edge_rows]
    payload = {
        "report_version": REPORT_VERSION,
        "runtime_effect": RUNTIME_EFFECT,
        "horizon_sessions": horizon_sessions,
        "events_seen": len(groups),
        "events_labeled": len(edge_rows),
        "ev": evaluate_expected_value(returns, assumptions=assumptions),
        "feature_scan": feature_lift_scan(
            edge_rows,
            min_rows=min_rows,
            permutations=permutations,
            permutation_block_field="market_date",
            min_unique_values=2,
        ),
        "regime_scan": feature_lift_scan_by_regime(
            edge_rows,
            regime_field="earnings.report_timing",
            min_rows=min_rows,
            permutations=permutations,
            permutation_block_field="market_date",
            min_unique_values=2,
        ),
    }
    return payload, edge_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(ROOT / "trades.db"))
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest-jsonl")
    ingest.add_argument("--input", required=True)

    validate = sub.add_parser("validate-jsonl")
    validate.add_argument("--input", required=True)
    validate.add_argument("--json-output")

    scan = sub.add_parser("scan")
    scan.add_argument("--start-date")
    scan.add_argument("--end-date")
    scan.add_argument("--horizon-sessions", type=int, default=5)
    scan.add_argument("--min-rows", type=int, default=30)
    scan.add_argument("--permutations", type=int, default=200)
    scan.add_argument("--spread-pct", type=float, default=0.05)
    scan.add_argument("--slippage-pct", type=float, default=0.03)
    scan.add_argument("--account-equity", type=float)
    scan.add_argument("--max-position-pct", type=float, default=1.0)
    scan.add_argument("--json-output")

    args = parser.parse_args(argv)
    repo = ExternalSignalFeatureRepository(args.db_path)
    if args.command == "validate-jsonl":
        payloads = _load_jsonl(Path(args.input))
        result = validate_earnings_payloads(payloads)
        if args.json_output:
            output = Path(args.json_output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1

    if args.command == "ingest-jsonl":
        payloads = _load_jsonl(Path(args.input))
        validation = validate_earnings_payloads(payloads)
        if not validation["valid"]:
            print(json.dumps(validation, indent=2, sort_keys=True), file=sys.stderr)
            return 1
        features = [
            feature for payload in payloads for feature in earnings_payload_to_features(payload)
        ]
        changed = repo.upsert_many(features)
        print(
            json.dumps(
                {
                    "report_version": "post_earnings_drift_ingest_v1",
                    "runtime_effect": RUNTIME_EFFECT,
                    "events_read": len(payloads),
                    "features_written": changed,
                    "leakage_violations": repo.leakage_violations(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    payload, _rows = build_post_earnings_drift_payload(
        db_path=args.db_path,
        start=args.start_date,
        end=args.end_date,
        horizon_sessions=args.horizon_sessions,
        min_rows=args.min_rows,
        permutations=args.permutations,
        spread_pct=args.spread_pct,
        slippage_pct=args.slippage_pct,
        account_equity=args.account_equity,
        max_position_pct=args.max_position_pct,
    )
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
