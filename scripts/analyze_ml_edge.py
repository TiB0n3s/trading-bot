#!/usr/bin/env python3
"""Measure whether layered ML has earned more paper authority.

The report is read-only and intentionally uses indexed timestamp filters plus
Python JSON parsing. Avoid SQLite JSON scans on the live DB; trades.db can be
large enough that JSON extraction in SQL becomes operationally expensive.

Sources:
  * candidate_universe: current candidate payloads plus any forward labels
    already materialized into candidate_json.
  * rejected_signal_outcomes + auto_buy_decision_snapshots: rejected/blocked
    signal forward outcomes joined back to the candidate snapshot by id.
  * auto_buy_decision_snapshots + historical_signal_outcomes: older daily
    realized-outcome join, useful only when date ranges overlap.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

APPROVE_INSTRUCTIONS = {"paper_approval", "size_increase", "pass"}
CAUTION_INSTRUCTIONS = {"watch", "veto"}
SYSTEM_PROBABILITY_SOURCES = {
    "probability_of_approval",
    "probability_of_order",
    "daily_symbol_predictions:probability_of_approval",
    "daily_symbol_predictions:probability_of_order",
}
PROBABILITY_KEYS = (
    "layered_ml_ensemble_probability_pct",
    "ensemble_probability_pct",
    "probability_pct",
    "probability_of_profit_pct",
    "probability_of_profit",
    "probability_of_approval_pct",
    "probability_of_approval",
    "probability_of_order_pct",
    "probability_of_order",
)
FORWARD_RETURN_KEYS = (
    "forward_return_pct",
    "return_60m",
    "return_30m",
    "return_eod",
    "realized_pnl_pct",
)
EXCLUDED_FEATURE_KEYS = {
    "ask",
    "bid",
    "feature_snapshot_id",
    "forward_mae_pct",
    "forward_mfe_pct",
    "forward_reference_price",
    "forward_return_pct",
    "last_price",
    "max_favorable_30m",
    "max_favorable_60m",
    "max_adverse_60m",
    "mid",
    "probability_of_approval",
    "probability_of_approval_pct",
    "probability_of_order",
    "probability_of_order_pct",
    "probability_of_profit",
    "probability_of_profit_pct",
    "probability_pct",
    "realized_pnl_pct",
    "reference_price",
    "return_30m",
    "return_15m",
    "return_5m",
    "return_60m",
    "return_eod",
}
_JSON_VALUE_RE_CACHE: dict[str, re.Pattern[str]] = {}


@dataclass(frozen=True)
class EdgeRow:
    source: str
    symbol: str | None
    market_date: str | None
    decision: str | None
    score: float | None
    confluence_score: float | None
    conviction_score: float | None
    setup_score: float | None
    probability_pct: float | None
    probability_source: str | None
    instruction: str
    instruction_class: str
    forward_return_pct: float | None
    forward_mfe_pct: float | None
    numeric_features: dict[str, float]
    categorical_features: dict[str, str]


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _has_table(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result * 100.0 if 0.0 <= result <= 1.0 else result


def _raw_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _json_value_pattern(key: str) -> re.Pattern[str]:
    pattern = _JSON_VALUE_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(
            rf'"{re.escape(key)}"\s*:\s*'
            r'("(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)'
        )
        _JSON_VALUE_RE_CACHE[key] = pattern
    return pattern


def _decode_json_scalar(raw_value: str | None) -> Any:
    if raw_value in (None, "null"):
        return None
    if raw_value == "true":
        return True
    if raw_value == "false":
        return False
    try:
        return json.loads(raw_value)
    except Exception:
        return raw_value


def _raw_json_value(raw_json: Any, keys: Iterable[str]) -> Any:
    raw = str(raw_json or "")
    if not raw:
        return None
    for key in keys:
        for match in _json_value_pattern(key).finditer(raw):
            value = _decode_json_scalar(match.group(1))
            if value is not None:
                return value
    return None


def _candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate")
    return candidate if isinstance(candidate, dict) else payload


def _flatten_numeric_features(
    value: Any,
    *,
    output: dict[str, float],
    prefix: str = "",
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_str = str(key)
            if key_str in EXCLUDED_FEATURE_KEYS or key_str == "canonical_signal_candidate":
                continue
            name = f"{prefix}.{key_str}" if prefix else key_str
            _flatten_numeric_features(child, output=output, prefix=name)
        return
    if isinstance(value, bool) or value in (None, ""):
        return
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return
    if numeric == numeric:
        output[prefix] = numeric


def _numeric_features(payload: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float]:
    features: dict[str, float] = {}
    _flatten_numeric_features(candidate, output=features)
    for key, value in payload.items():
        if key == "candidate" or key in EXCLUDED_FEATURE_KEYS:
            continue
        _flatten_numeric_features(value, output=features, prefix=str(key))
    return features


def _flatten_categorical_features(
    value: Any,
    *,
    output: dict[str, str],
    prefix: str = "",
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_str = str(key)
            if key_str in EXCLUDED_FEATURE_KEYS or key_str == "canonical_signal_candidate":
                continue
            name = f"{prefix}.{key_str}" if prefix else key_str
            _flatten_categorical_features(child, output=output, prefix=name)
        return
    if isinstance(value, bool) or value in (None, ""):
        return
    if isinstance(value, (int, float)):
        return
    output[prefix] = str(value)


def _categorical_features(payload: dict[str, Any], candidate: dict[str, Any]) -> dict[str, str]:
    features: dict[str, str] = {}
    _flatten_categorical_features(candidate, output=features)
    for key, value in payload.items():
        if key == "candidate" or key in EXCLUDED_FEATURE_KEYS:
            continue
        _flatten_categorical_features(value, output=features, prefix=str(key))
    return features


def _first_value(*sources: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        for source in sources:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


def _probability(
    payload: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float | None, str | None]:
    for key in PROBABILITY_KEYS:
        value = candidate.get(key)
        if value in (None, ""):
            value = payload.get(key)
        probability = _float(value)
        if probability is not None:
            source = str(
                candidate.get("probability_source") or payload.get("probability_source") or key
            )
            return probability, source
    return None, None


def _instruction(
    payload: dict[str, Any], candidate: dict[str, Any], reason: str | None
) -> tuple[str, str]:
    instruction = (
        str(
            candidate.get("layered_ml_final_instruction")
            or payload.get("layered_ml_final_instruction")
            or "none"
        )
        .strip()
        .lower()
    )
    if instruction in APPROVE_INSTRUCTIONS:
        return instruction, "approve"
    if instruction in CAUTION_INSTRUCTIONS:
        return instruction, "caution"

    blob = str(reason or candidate.get("reason") or payload.get("reason") or "").lower()
    if "layered_ml_approval" in blob or "layered_ml_pass" in blob:
        return instruction, "approve"
    if "layered_ml_watch" in blob or "layered_ml_veto" in blob:
        return instruction, "caution"
    return instruction, "unknown"


def _edge_row_from_payload(
    *,
    source: str,
    symbol: Any,
    market_date: Any,
    decision: Any,
    score: Any,
    reason: Any,
    payload: dict[str, Any],
    outcome_return: Any = None,
    outcome_mfe: Any = None,
) -> EdgeRow:
    candidate = _candidate_payload(payload)
    probability_pct, probability_source = _probability(payload, candidate)
    instruction, instruction_class = _instruction(payload, candidate, str(reason or ""))
    forward_return = _raw_float(outcome_return)
    if forward_return is None:
        forward_return = _raw_float(_first_value(candidate, payload, keys=FORWARD_RETURN_KEYS))
    forward_mfe = _raw_float(outcome_mfe)
    if forward_mfe is None:
        forward_mfe = _raw_float(
            _first_value(
                candidate,
                payload,
                keys=("forward_mfe_pct", "max_favorable_60m", "max_favorable_30m"),
            )
        )
    return EdgeRow(
        source=source,
        symbol=str(symbol or "").upper() or None,
        market_date=str(market_date or "")[:10] or None,
        decision=str(decision or "") or None,
        score=_raw_float(score),
        confluence_score=_raw_float(_first_value(candidate, payload, keys=("confluence_score",))),
        conviction_score=_raw_float(_first_value(candidate, payload, keys=("conviction_score",))),
        setup_score=_raw_float(_first_value(candidate, payload, keys=("setup_score",))),
        probability_pct=probability_pct,
        probability_source=probability_source,
        instruction=instruction,
        instruction_class=instruction_class,
        forward_return_pct=forward_return,
        forward_mfe_pct=forward_mfe,
        numeric_features=_numeric_features(payload, candidate),
        categorical_features=_categorical_features(payload, candidate),
    )


def _edge_row_from_raw_payload(
    *,
    source: str,
    symbol: Any,
    market_date: Any,
    decision: Any,
    score: Any,
    reason: Any,
    raw_payload: Any,
    outcome_return: Any = None,
    outcome_mfe: Any = None,
) -> EdgeRow:
    probability_pct = None
    probability_source = None
    for key in PROBABILITY_KEYS:
        probability_pct = _float(_raw_json_value(raw_payload, (key,)))
        if probability_pct is not None:
            probability_source = str(_raw_json_value(raw_payload, ("probability_source",)) or key)
            break

    instruction = (
        str(_raw_json_value(raw_payload, ("layered_ml_final_instruction",)) or "none")
        .strip()
        .lower()
    )
    if instruction in APPROVE_INSTRUCTIONS:
        instruction_class = "approve"
    elif instruction in CAUTION_INSTRUCTIONS:
        instruction_class = "caution"
    else:
        blob = str(reason or "").lower()
        if "layered_ml_approval" in blob or "layered_ml_pass" in blob:
            instruction_class = "approve"
        elif "layered_ml_watch" in blob or "layered_ml_veto" in blob:
            instruction_class = "caution"
        else:
            instruction_class = "unknown"

    forward_return = _raw_float(outcome_return)
    if forward_return is None:
        forward_return = _raw_float(_raw_json_value(raw_payload, FORWARD_RETURN_KEYS))
    forward_mfe = _raw_float(outcome_mfe)
    if forward_mfe is None:
        forward_mfe = _raw_float(
            _raw_json_value(
                raw_payload,
                ("forward_mfe_pct", "max_favorable_60m", "max_favorable_30m"),
            )
        )
    payload = _load_json(raw_payload)
    candidate = _candidate_payload(payload)

    return EdgeRow(
        source=source,
        symbol=str(symbol or "").upper() or None,
        market_date=str(market_date or "")[:10] or None,
        decision=str(decision or "") or None,
        score=_raw_float(score),
        confluence_score=_raw_float(_raw_json_value(raw_payload, ("confluence_score",))),
        conviction_score=_raw_float(_raw_json_value(raw_payload, ("conviction_score",))),
        setup_score=_raw_float(_raw_json_value(raw_payload, ("setup_score",))),
        probability_pct=probability_pct,
        probability_source=probability_source,
        instruction=instruction,
        instruction_class=instruction_class,
        forward_return_pct=forward_return,
        forward_mfe_pct=forward_mfe,
        numeric_features=_numeric_features(payload, candidate),
        categorical_features=_categorical_features(payload, candidate),
    )


def _load_prediction_map(
    con: sqlite3.Connection,
    start: str | None,
    end: str | None,
) -> dict[tuple[str, str], tuple[float, str]]:
    if not _has_table(con, "daily_symbol_predictions"):
        return {}
    columns = _columns(con, "daily_symbol_predictions")
    if not {"market_date", "symbol", "probability_of_profit"} <= columns:
        return {}
    source_expr = (
        "probability_of_profit_source"
        if "probability_of_profit_source" in columns
        else "'legacy_unknown_profit_probability'"
    )
    where, params = _date_where(
        "market_date", start[:10] if start else None, end[:10] if end else None
    )
    rows = con.execute(
        f"""
        SELECT market_date, symbol, probability_of_profit,
               {source_expr} AS probability_of_profit_source
        FROM daily_symbol_predictions
        {where}
          {"AND" if where else "WHERE"} probability_of_profit IS NOT NULL
        """,
        params,
    ).fetchall()
    result: dict[tuple[str, str], tuple[float, str]] = {}
    for row in rows:
        probability = _float(row["probability_of_profit"])
        if probability is None:
            continue
        source = row["probability_of_profit_source"] or "legacy_unknown_profit_probability"
        result[(str(row["market_date"])[:10], str(row["symbol"]).upper())] = (
            probability,
            f"daily_symbol_predictions:probability_of_profit:{source}",
        )
    return result


def _with_prediction_fallback(
    row: EdgeRow,
    predictions: dict[tuple[str, str], tuple[float, str]],
) -> EdgeRow:
    if row.probability_pct is not None:
        return row
    if not row.market_date or not row.symbol:
        return row
    fallback = predictions.get((row.market_date[:10], row.symbol.upper()))
    if fallback is None:
        return row
    probability, source = fallback
    return replace(row, probability_pct=probability, probability_source=source)


def _date_where(column: str, start: str | None, end: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append(f"{column} >= ?")
        params.append(start)
    if end:
        clauses.append(f"{column} < ?")
        params.append(end)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def load_candidate_universe(
    con: sqlite3.Connection,
    start: str | None,
    end: str | None,
    limit: int | None,
) -> list[EdgeRow]:
    if not _has_table(con, "candidate_universe"):
        return []
    predictions = _load_prediction_map(con, start, end)
    where, params = _date_where("candidate_ts", start, end)
    sql = f"""
        SELECT candidate_ts, symbol, candidate_status, score, reason, candidate_json
        FROM candidate_universe
        {where}
        ORDER BY candidate_ts
    """
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows: list[EdgeRow] = []
    for row in con.execute(sql, params):
        edge_row = _edge_row_from_raw_payload(
            source="candidate_universe",
            symbol=row["symbol"],
            market_date=row["candidate_ts"],
            decision=row["candidate_status"],
            score=row["score"],
            reason=row["reason"],
            raw_payload=row["candidate_json"],
        )
        rows.append(_with_prediction_fallback(edge_row, predictions))
    return rows


def load_rejected_outcomes(
    con: sqlite3.Connection,
    start: str | None,
    end: str | None,
    limit: int | None,
) -> list[EdgeRow]:
    if not _has_table(con, "rejected_signal_outcomes") or not _has_table(
        con, "auto_buy_decision_snapshots"
    ):
        return []
    where, params = _date_where("r.timestamp", start, end)
    sql = f"""
        SELECT r.timestamp,
               r.symbol,
               r.action,
               r.return_60m,
               r.return_30m,
               r.return_eod,
               r.max_favorable_60m,
               r.rejection_reason,
               s.decision,
               s.score,
               s.reason,
               s.candidate_json
        FROM rejected_signal_outcomes r
        JOIN auto_buy_decision_snapshots s
          ON s.id = r.decision_snapshot_id
        {where}
        ORDER BY r.timestamp
    """
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows: list[EdgeRow] = []
    for row in con.execute(sql, params):
        outcome = row["return_60m"]
        if outcome is None:
            outcome = row["return_30m"]
        if outcome is None:
            outcome = row["return_eod"]
        rows.append(
            _edge_row_from_raw_payload(
                source="rejected_signal_outcomes",
                symbol=row["symbol"],
                market_date=row["timestamp"],
                decision=row["decision"],
                score=row["score"],
                reason=row["reason"] or row["rejection_reason"],
                raw_payload=row["candidate_json"],
                outcome_return=outcome,
                outcome_mfe=row["max_favorable_60m"],
            )
        )
    return rows


def load_daily_outcome_join(
    con: sqlite3.Connection,
    start: str | None,
    end: str | None,
    limit: int | None,
) -> list[EdgeRow]:
    if not _has_table(con, "auto_buy_decision_snapshots") or not _has_table(
        con, "historical_signal_outcomes"
    ):
        return []
    if "realized_pnl_pct" not in _columns(con, "historical_signal_outcomes"):
        return []
    where = ["o.realized_pnl_pct IS NOT NULL"]
    params: list[Any] = []
    if start:
        where.append("s.candidate_timestamp >= ?")
        params.append(start)
    if end:
        where.append("s.candidate_timestamp < ?")
        params.append(end)
    sql = f"""
        SELECT s.candidate_timestamp,
               s.symbol,
               s.decision,
               s.score,
               s.reason,
               s.candidate_json,
               o.realized_pnl_pct
        FROM auto_buy_decision_snapshots s
        JOIN historical_signal_outcomes o
          ON o.symbol = s.symbol
         AND o.market_date = substr(s.candidate_timestamp, 1, 10)
        WHERE {" AND ".join(where)}
        ORDER BY s.candidate_timestamp
    """
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows: list[EdgeRow] = []
    for row in con.execute(sql, params):
        rows.append(
            _edge_row_from_raw_payload(
                source="daily_signal_outcome_join",
                symbol=row["symbol"],
                market_date=row["candidate_timestamp"],
                decision=row["decision"],
                score=row["score"],
                reason=row["reason"],
                raw_payload=row["candidate_json"],
                outcome_return=row["realized_pnl_pct"],
            )
        )
    return rows


def _win_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(100.0 * sum(1 for value in values if value > 0) / len(values), 1)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.mean(values), 4)


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def calibration(rows: list[EdgeRow], bins: int) -> list[dict[str, Any]]:
    bucketed: dict[int, list[EdgeRow]] = defaultdict(list)
    width = 100.0 / bins
    for row in rows:
        if row.probability_pct is None or row.forward_return_pct is None:
            continue
        idx = min(int(row.probability_pct // width), bins - 1)
        bucketed[idx].append(row)
    result = []
    for idx, bucket in sorted(bucketed.items()):
        returns = [row.forward_return_pct for row in bucket if row.forward_return_pct is not None]
        probs = [row.probability_pct for row in bucket if row.probability_pct is not None]
        pred = statistics.mean(probs)
        win = _win_rate(returns)
        result.append(
            {
                "bin": f"{idx * width:.0f}-{(idx + 1) * width:.0f}%",
                "n": len(bucket),
                "predicted_win_pct": round(pred, 1),
                "realized_win_pct": win,
                "gap": round(pred - (win or 0.0), 1) if win is not None else None,
                "mean_return_pct": _avg(returns),
            }
        )
    return result


def edge_by_group(rows: list[EdgeRow], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[EdgeRow]] = defaultdict(list)
    for row in rows:
        outcome = row.forward_return_pct
        if outcome is None:
            continue
        grouped[str(getattr(row, key) or "unknown")].append(row)
    result = []
    for group, bucket in grouped.items():
        returns = [row.forward_return_pct for row in bucket if row.forward_return_pct is not None]
        mfes = [row.forward_mfe_pct for row in bucket if row.forward_mfe_pct is not None]
        result.append(
            {
                "group": group,
                "n": len(bucket),
                "win_pct": _win_rate(returns),
                "mean_return_pct": _avg(returns),
                "avg_mfe_pct": _avg(mfes),
            }
        )
    result.sort(key=lambda item: (-int(item["n"]), item["group"]))
    return result


def probability_source_edge(rows: list[EdgeRow]) -> list[dict[str, Any]]:
    grouped: dict[str, list[EdgeRow]] = defaultdict(list)
    for row in rows:
        if row.probability_pct is None or row.forward_return_pct is None:
            continue
        grouped[str(row.probability_source or "missing")].append(row)
    result = []
    for source, bucket in grouped.items():
        returns = [row.forward_return_pct for row in bucket if row.forward_return_pct is not None]
        probs = [row.probability_pct for row in bucket if row.probability_pct is not None]
        pred = _avg(probs)
        win = _win_rate(returns)
        result.append(
            {
                "source": source,
                "n": len(bucket),
                "predicted_win_pct": pred,
                "realized_win_pct": win,
                "gap": round(pred - win, 4) if pred is not None and win is not None else None,
                "mean_return_pct": _avg(returns),
            }
        )
    result.sort(key=lambda item: (-int(item["n"]), item["source"]))
    return result


def decile_lift(
    rows: list[EdgeRow],
    *,
    n_buckets: int = 10,
    probability_source: str | None = None,
) -> dict[str, Any]:
    usable = [
        row
        for row in rows
        if row.probability_pct is not None
        and row.forward_return_pct is not None
        and (probability_source is None or row.probability_source == probability_source)
    ]
    usable.sort(key=lambda row: float(row.probability_pct or 0.0))
    n = len(usable)
    min_rows = n_buckets * 3
    if n < min_rows:
        return {
            "source": probability_source or "all",
            "n": n,
            "required_n": min_rows,
            "base_win_pct": None,
            "buckets": [],
            "lift_pct": None,
            "monotonicity": None,
            "verdict": "too_few_rows",
        }

    returns = [row.forward_return_pct for row in usable if row.forward_return_pct is not None]
    base_win = _win_rate(returns)
    size = n // n_buckets
    buckets = []
    wins_by_bucket = []
    for idx in range(n_buckets):
        lo = idx * size
        hi = n if idx == n_buckets - 1 else (idx + 1) * size
        bucket = usable[lo:hi]
        bucket_returns = [
            row.forward_return_pct for row in bucket if row.forward_return_pct is not None
        ]
        bucket_probs = [row.probability_pct for row in bucket if row.probability_pct is not None]
        win = _win_rate(bucket_returns)
        wins_by_bucket.append(win or 0.0)
        buckets.append(
            {
                "bucket": f"D{idx + 1}",
                "n": len(bucket),
                "prob_min": min(bucket_probs) if bucket_probs else None,
                "prob_max": max(bucket_probs) if bucket_probs else None,
                "win_pct": win,
                "mean_return_pct": _avg(bucket_returns),
            }
        )

    lift = round(wins_by_bucket[-1] - wins_by_bucket[0], 1)
    ups = sum(1 for idx in range(1, n_buckets) if wins_by_bucket[idx] >= wins_by_bucket[idx - 1])
    monotonicity = round(ups / (n_buckets - 1), 4)
    verdict = "rank_orders_outcomes" if lift >= 8.0 and monotonicity >= 0.6 else "weak_or_flat"
    return {
        "source": probability_source or "all",
        "n": n,
        "required_n": min_rows,
        "base_win_pct": base_win,
        "buckets": buckets,
        "lift_pct": lift,
        "monotonicity": monotonicity,
        "verdict": verdict,
    }


def metric_decile_lift(
    rows: list[EdgeRow],
    *,
    metric: str,
    n_buckets: int = 10,
) -> dict[str, Any]:
    usable = [
        row
        for row in rows
        if getattr(row, metric, None) is not None and row.forward_return_pct is not None
    ]
    usable.sort(key=lambda row: float(getattr(row, metric) or 0.0))
    n = len(usable)
    min_rows = n_buckets * 3
    if n < min_rows:
        return {
            "metric": metric,
            "n": n,
            "required_n": min_rows,
            "base_win_pct": None,
            "buckets": [],
            "lift_pct": None,
            "monotonicity": None,
            "verdict": "too_few_rows",
        }

    returns = [row.forward_return_pct for row in usable if row.forward_return_pct is not None]
    base_win = _win_rate(returns)
    size = n // n_buckets
    buckets = []
    wins_by_bucket = []
    for idx in range(n_buckets):
        lo = idx * size
        hi = n if idx == n_buckets - 1 else (idx + 1) * size
        bucket = usable[lo:hi]
        bucket_returns = [
            row.forward_return_pct for row in bucket if row.forward_return_pct is not None
        ]
        values = [float(getattr(row, metric)) for row in bucket if getattr(row, metric) is not None]
        win = _win_rate(bucket_returns)
        wins_by_bucket.append(win or 0.0)
        buckets.append(
            {
                "bucket": f"D{idx + 1}",
                "n": len(bucket),
                "value_min": min(values) if values else None,
                "value_max": max(values) if values else None,
                "win_pct": win,
                "mean_return_pct": _avg(bucket_returns),
            }
        )

    lift = round(wins_by_bucket[-1] - wins_by_bucket[0], 1)
    ups = sum(1 for idx in range(1, n_buckets) if wins_by_bucket[idx] >= wins_by_bucket[idx - 1])
    monotonicity = round(ups / (n_buckets - 1), 4)
    verdict = "rank_orders_outcomes" if lift >= 8.0 and monotonicity >= 0.6 else "weak_or_flat"
    return {
        "metric": metric,
        "n": n,
        "required_n": min_rows,
        "base_win_pct": base_win,
        "buckets": buckets,
        "lift_pct": lift,
        "monotonicity": monotonicity,
        "verdict": verdict,
    }


def feature_decile_lift(
    rows: list[EdgeRow],
    *,
    feature: str,
    n_buckets: int = 10,
    min_rows: int | None = None,
) -> dict[str, Any]:
    usable = [
        row
        for row in rows
        if feature in row.numeric_features and row.forward_return_pct is not None
    ]
    usable.sort(key=lambda row: row.numeric_features[feature])
    n = len(usable)
    required_n = min_rows or n_buckets * 3
    if n < required_n:
        return {
            "feature": feature,
            "n": n,
            "required_n": required_n,
            "base_win_pct": None,
            "buckets": [],
            "lift_pct": None,
            "monotonicity": None,
            "verdict": "too_few_rows",
        }

    returns = [row.forward_return_pct for row in usable if row.forward_return_pct is not None]
    base_win = _win_rate(returns)
    size = n // n_buckets
    buckets = []
    wins_by_bucket = []
    for idx in range(n_buckets):
        lo = idx * size
        hi = n if idx == n_buckets - 1 else (idx + 1) * size
        bucket = usable[lo:hi]
        bucket_returns = [
            row.forward_return_pct for row in bucket if row.forward_return_pct is not None
        ]
        values = [row.numeric_features[feature] for row in bucket]
        win = _win_rate(bucket_returns)
        wins_by_bucket.append(win or 0.0)
        buckets.append(
            {
                "bucket": f"D{idx + 1}",
                "n": len(bucket),
                "value_min": min(values) if values else None,
                "value_max": max(values) if values else None,
                "win_pct": win,
                "mean_return_pct": _avg(bucket_returns),
            }
        )

    lift = round(wins_by_bucket[-1] - wins_by_bucket[0], 1)
    if lift >= 0:
        aligned_steps = sum(
            1 for idx in range(1, n_buckets) if wins_by_bucket[idx] >= wins_by_bucket[idx - 1]
        )
        direction = "higher_is_better"
    else:
        aligned_steps = sum(
            1 for idx in range(1, n_buckets) if wins_by_bucket[idx] <= wins_by_bucket[idx - 1]
        )
        direction = "lower_is_better"
    monotonicity = round(aligned_steps / (n_buckets - 1), 4)
    verdict = "rank_orders_outcomes" if abs(lift) >= 8.0 and monotonicity >= 0.6 else "weak_or_flat"
    return {
        "feature": feature,
        "n": n,
        "required_n": required_n,
        "base_win_pct": base_win,
        "buckets": buckets,
        "lift_pct": lift,
        "monotonicity": monotonicity,
        "direction": direction,
        "verdict": verdict,
    }


def feature_lift_scan(
    rows: list[EdgeRow],
    *,
    n_buckets: int = 10,
    min_rows: int = 100,
) -> list[dict[str, Any]]:
    features = sorted(
        {
            feature
            for row in rows
            if row.forward_return_pct is not None
            for feature in row.numeric_features
        }
    )
    results = [
        feature_decile_lift(
            rows,
            feature=feature,
            n_buckets=n_buckets,
            min_rows=min_rows,
        )
        for feature in features
    ]
    usable = [result for result in results if result["verdict"] != "too_few_rows"]
    usable.sort(
        key=lambda item: (
            item["verdict"] != "rank_orders_outcomes",
            -abs(float(item["lift_pct"] or 0.0)),
            -float(item["monotonicity"] or 0.0),
            item["feature"],
        )
    )
    return usable


def _regime_value(row: EdgeRow, field: str) -> str | None:
    value = row.categorical_features.get(field)
    if value not in (None, ""):
        return value
    numeric = row.numeric_features.get(field)
    if numeric is not None:
        return str(numeric)
    return None


def feature_lift_scan_by_regime(
    rows: list[EdgeRow],
    *,
    regime_field: str,
    n_buckets: int = 10,
    min_rows: int = 100,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[EdgeRow]] = defaultdict(list)
    for row in rows:
        if row.forward_return_pct is None:
            continue
        regime = _regime_value(row, regime_field)
        if not regime:
            continue
        grouped[regime].append(row)

    result = []
    for regime, bucket in grouped.items():
        if len(bucket) < min_rows:
            continue
        returns = [row.forward_return_pct for row in bucket if row.forward_return_pct is not None]
        result.append(
            {
                "regime": regime,
                "n": len(bucket),
                "base_win_pct": _win_rate(returns),
                "mean_return_pct": _avg(returns),
                "features": feature_lift_scan(
                    bucket,
                    n_buckets=n_buckets,
                    min_rows=min_rows,
                ),
            }
        )
    result.sort(key=lambda item: (-int(item["n"]), str(item["regime"])))
    return result


def score_window(rows: list[EdgeRow], min_score: float) -> list[dict[str, Any]]:
    grouped = {
        "below_window": [],
        "near_window": [],
        "meets_score": [],
    }
    for row in rows:
        if row.forward_return_pct is None:
            continue
        score = row.conviction_score if row.conviction_score is not None else row.score
        if score is None:
            continue
        if score >= min_score:
            grouped["meets_score"].append(row)
        elif score >= min_score - 3.0:
            grouped["near_window"].append(row)
        else:
            grouped["below_window"].append(row)
    result = []
    for group, bucket in grouped.items():
        returns = [row.forward_return_pct for row in bucket if row.forward_return_pct is not None]
        result.append(
            {
                "group": group,
                "n": len(bucket),
                "win_pct": _win_rate(returns),
                "mean_return_pct": _avg(returns),
            }
        )
    return result


def _print_decile_lift(title: str, result: dict[str, Any]) -> None:
    print(f"\n  {title}")
    print(
        f"  source={result['source']} n={result['n']} "
        f"required_n={result['required_n']} base_win%={_fmt(result['base_win_pct'])}"
    )
    if result["verdict"] == "too_few_rows":
        print("  (too few probability/outcome rows for stable bucket lift)")
        return
    print(f"  {'bucket':<8}{'n':>8}{'prob_range%':>18}{'win%':>10}{'mean_ret%':>12}")
    for item in result["buckets"]:
        prob_range = (
            "-"
            if item["prob_min"] is None or item["prob_max"] is None
            else f"{item['prob_min']:.1f}-{item['prob_max']:.1f}"
        )
        print(
            f"  {item['bucket']:<8}{item['n']:>8}{prob_range:>18}"
            f"{_fmt(item['win_pct']):>10}{_fmt(item['mean_return_pct']):>12}"
        )
    print(
        f"  top-minus-bottom lift: {_fmt(result['lift_pct'])} pts"
        f"   |   monotonicity: {100.0 * float(result['monotonicity']):.0f}%"
        f"   |   verdict: {result['verdict']}"
    )


def _print_metric_lift(result: dict[str, Any]) -> None:
    print(f"\n  METRIC DECILE LIFT: {result['metric']}")
    print(
        f"  n={result['n']} required_n={result['required_n']} "
        f"base_win%={_fmt(result['base_win_pct'])}"
    )
    if result["verdict"] == "too_few_rows":
        print("  (too few metric/outcome rows for stable bucket lift)")
        return
    print(f"  {'bucket':<8}{'n':>8}{'value_range':>18}{'win%':>10}{'mean_ret%':>12}")
    for item in result["buckets"]:
        value_range = (
            "-"
            if item["value_min"] is None or item["value_max"] is None
            else f"{item['value_min']:.1f}-{item['value_max']:.1f}"
        )
        print(
            f"  {item['bucket']:<8}{item['n']:>8}{value_range:>18}"
            f"{_fmt(item['win_pct']):>10}{_fmt(item['mean_return_pct']):>12}"
        )
    print(
        f"  top-minus-bottom lift: {_fmt(result['lift_pct'])} pts"
        f"   |   monotonicity: {100.0 * float(result['monotonicity']):.0f}%"
        f"   |   verdict: {result['verdict']}"
    )


def _print_feature_scan(results: list[dict[str, Any]], *, limit: int) -> None:
    print("\n  NUMERIC FEATURE LIFT SCAN")
    if not results:
        print("  (no numeric features with enough forward-outcome coverage)")
        return
    print(
        f"  {'feature':<38}{'n':>8}{'lift':>10}{'mono%':>10}"
        f"{'direction':>18}{'base_win%':>12}{'d1_ret%':>12}{'d10_ret%':>12}"
    )
    for item in results[:limit]:
        buckets = item.get("buckets") or []
        d1_ret = buckets[0]["mean_return_pct"] if buckets else None
        d10_ret = buckets[-1]["mean_return_pct"] if buckets else None
        print(
            f"  {item['feature']:<38}{item['n']:>8}"
            f"{_fmt(item['lift_pct']):>10}"
            f"{100.0 * float(item['monotonicity']):>10.0f}"
            f"{str(item.get('direction', '-')):>18}"
            f"{_fmt(item['base_win_pct']):>12}"
            f"{_fmt(d1_ret):>12}"
            f"{_fmt(d10_ret):>12}"
        )


def _print_regime_feature_scan(
    results: list[dict[str, Any]],
    *,
    regime_field: str,
    limit: int,
) -> None:
    print(f"\n  NUMERIC FEATURE LIFT BY REGIME: {regime_field}")
    if not results:
        print("  (no regime buckets with enough forward-outcome coverage)")
        return
    for group in results:
        print(
            f"\n  regime={group['regime']} n={group['n']} "
            f"base_win%={_fmt(group['base_win_pct'])} "
            f"mean_ret%={_fmt(group['mean_return_pct'])}"
        )
        features = group["features"]
        if not features:
            print("  (no numeric features with enough coverage inside this regime)")
            continue
        print(
            f"  {'feature':<38}{'n':>8}{'lift':>10}{'mono%':>10}"
            f"{'direction':>18}{'d1_ret%':>12}{'d10_ret%':>12}"
        )
        for item in features[:limit]:
            buckets = item.get("buckets") or []
            d1_ret = buckets[0]["mean_return_pct"] if buckets else None
            d10_ret = buckets[-1]["mean_return_pct"] if buckets else None
            print(
                f"  {item['feature']:<38}{item['n']:>8}"
                f"{_fmt(item['lift_pct']):>10}"
                f"{100.0 * float(item['monotonicity']):>10.0f}"
                f"{str(item.get('direction', '-')):>18}"
                f"{_fmt(d1_ret):>12}"
                f"{_fmt(d10_ret):>12}"
            )


def print_report(
    source: str,
    rows: list[EdgeRow],
    bins: int,
    min_score: float,
    decile_buckets: int,
    feature_scan_limit: int,
    feature_scan_min_rows: int,
    regime_field: str,
    regime_scan_limit: int,
    regime_scan_min_rows: int,
) -> None:
    total = len(rows)
    outcome_rows = [row for row in rows if row.forward_return_pct is not None]
    probability_rows = [row for row in rows if row.probability_pct is not None]
    instruction_rows = [row for row in rows if row.instruction_class != "unknown"]
    print("\n" + "=" * 78)
    print(f"  {source}")
    print("=" * 78)
    print(f"  rows                              : {total}")
    print(
        f"  rows with forward outcome          : {len(outcome_rows)} ({_pct(len(outcome_rows), total)})"
    )
    print(
        f"  rows with probability              : {len(probability_rows)} ({_pct(len(probability_rows), total)})"
    )
    print(
        f"  rows with layered instruction       : {len(instruction_rows)} ({_pct(len(instruction_rows), total)})"
    )
    if not outcome_rows:
        print(
            "  analysis                           : no forward outcomes available for this source"
        )
        return

    print("\n  CALIBRATION")
    print(f"  {'bin':<10}{'n':>8}{'pred_win%':>12}{'real_win%':>12}{'gap':>10}{'mean_ret%':>12}")
    table = calibration(rows, bins)
    if not table:
        print("  (no probability/outcome overlap)")
    for item in table:
        print(
            f"  {item['bin']:<10}{item['n']:>8}{_fmt(item['predicted_win_pct']):>12}"
            f"{_fmt(item['realized_win_pct']):>12}{_fmt(item['gap']):>10}"
            f"{_fmt(item['mean_return_pct']):>12}"
        )

    print("\n  CALIBRATION BY PROBABILITY SOURCE")
    print(f"  {'source':<42}{'n':>8}{'pred_win%':>12}{'real_win%':>12}{'gap':>10}{'mean_ret%':>12}")
    source_table = probability_source_edge(rows)
    if not source_table:
        print("  (no probability/outcome overlap by source)")
    for item in source_table:
        print(
            f"  {item['source']:<42}{item['n']:>8}"
            f"{_fmt(item['predicted_win_pct']):>12}"
            f"{_fmt(item['realized_win_pct']):>12}"
            f"{_fmt(item['gap']):>10}"
            f"{_fmt(item['mean_return_pct']):>12}"
        )

    _print_decile_lift("DECILE LIFT", decile_lift(rows, n_buckets=decile_buckets))
    for item in source_table:
        _print_decile_lift(
            "DECILE LIFT BY PROBABILITY SOURCE",
            decile_lift(
                rows,
                n_buckets=decile_buckets,
                probability_source=str(item["source"]),
            ),
        )

    for metric in ("score", "confluence_score", "conviction_score", "setup_score"):
        _print_metric_lift(metric_decile_lift(rows, metric=metric, n_buckets=decile_buckets))

    _print_feature_scan(
        feature_lift_scan(
            rows,
            n_buckets=decile_buckets,
            min_rows=feature_scan_min_rows,
        ),
        limit=feature_scan_limit,
    )
    _print_regime_feature_scan(
        feature_lift_scan_by_regime(
            rows,
            regime_field=regime_field,
            n_buckets=decile_buckets,
            min_rows=regime_scan_min_rows,
        ),
        regime_field=regime_field,
        limit=regime_scan_limit,
    )

    print("\n  INSTRUCTION EDGE")
    print(f"  {'class':<14}{'n':>8}{'win%':>10}{'mean_ret%':>12}{'avg_mfe%':>12}")
    for item in edge_by_group(rows, "instruction_class"):
        print(
            f"  {item['group']:<14}{item['n']:>8}{_fmt(item['win_pct']):>10}"
            f"{_fmt(item['mean_return_pct']):>12}{_fmt(item['avg_mfe_pct']):>12}"
        )

    print("\n  SCORE WINDOW EDGE")
    print(f"  {'window':<14}{'n':>8}{'win%':>10}{'mean_ret%':>12}")
    for item in score_window(rows, min_score):
        print(
            f"  {item['group']:<14}{item['n']:>8}{_fmt(item['win_pct']):>10}"
            f"{_fmt(item['mean_return_pct']):>12}"
        )


def _pct(num: int, den: int) -> str:
    return f"{100.0 * num / den:.1f}%" if den else "0.0%"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.getenv("TRADES_DB_PATH", "trades.db"))
    parser.add_argument("--start", default=None, help="inclusive timestamp/date lower bound")
    parser.add_argument("--end", default=None, help="exclusive timestamp/date upper bound")
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--decile-buckets", type=int, default=10)
    parser.add_argument("--feature-scan-limit", type=int, default=20)
    parser.add_argument("--feature-scan-min-rows", type=int, default=100)
    parser.add_argument("--regime-field", default="session_trend_label")
    parser.add_argument("--regime-scan-limit", type=int, default=8)
    parser.add_argument("--regime-scan-min-rows", type=int, default=100)
    parser.add_argument(
        "--min-score", type=float, default=float(os.getenv("CONVICTION_MIN_SCORE", "23"))
    )
    parser.add_argument("--limit", type=int, default=None, help="debug limit per source")
    parser.add_argument(
        "--source",
        choices=("all", "candidate_universe", "rejected", "daily_join"),
        default="all",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        reports: list[tuple[str, list[EdgeRow]]] = []
        if args.source in {"all", "candidate_universe"}:
            reports.append(
                (
                    "CANDIDATE UNIVERSE FORWARD-LABEL EDGE",
                    load_candidate_universe(con, args.start, args.end, args.limit),
                )
            )
        if args.source in {"all", "rejected"}:
            reports.append(
                (
                    "REJECTED SIGNAL FORWARD-OUTCOME EDGE",
                    load_rejected_outcomes(con, args.start, args.end, args.limit),
                )
            )
        if args.source in {"all", "daily_join"}:
            reports.append(
                (
                    "AUTO-BUY SNAPSHOT DAILY REALIZED-OUTCOME EDGE",
                    load_daily_outcome_join(con, args.start, args.end, args.limit),
                )
            )
    finally:
        con.close()

    print("=" * 78)
    print("  ML AUTHORITY EDGE REPORT")
    print("=" * 78)
    print(f"  db                                : {db_path}")
    print(f"  start                             : {args.start or '-'}")
    print(f"  end                               : {args.end or '-'}")
    print(f"  conviction min score              : {args.min_score}")
    for title, rows in reports:
        print_report(
            title,
            rows,
            args.bins,
            args.min_score,
            args.decile_buckets,
            args.feature_scan_limit,
            args.feature_scan_min_rows,
            args.regime_field,
            args.regime_scan_limit,
            args.regime_scan_min_rows,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
