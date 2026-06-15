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
from dataclasses import dataclass
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
    probability_pct: float | None
    probability_source: str | None
    instruction: str
    instruction_class: str
    forward_return_pct: float | None
    forward_mfe_pct: float | None


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


def _first_value(*sources: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        for source in sources:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


def _probability(payload: dict[str, Any], candidate: dict[str, Any]) -> tuple[float | None, str | None]:
    for key in PROBABILITY_KEYS:
        value = candidate.get(key)
        if value in (None, ""):
            value = payload.get(key)
        probability = _float(value)
        if probability is not None:
            source = str(candidate.get("probability_source") or payload.get("probability_source") or key)
            return probability, source
    return None, None


def _instruction(payload: dict[str, Any], candidate: dict[str, Any], reason: str | None) -> tuple[str, str]:
    instruction = str(
        candidate.get("layered_ml_final_instruction")
        or payload.get("layered_ml_final_instruction")
        or "none"
    ).strip().lower()
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
        confluence_score=_raw_float(
            _first_value(candidate, payload, keys=("confluence_score",))
        ),
        conviction_score=_raw_float(
            _first_value(candidate, payload, keys=("conviction_score",))
        ),
        probability_pct=probability_pct,
        probability_source=probability_source,
        instruction=instruction,
        instruction_class=instruction_class,
        forward_return_pct=forward_return,
        forward_mfe_pct=forward_mfe,
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
            probability_source = str(
                _raw_json_value(raw_payload, ("probability_source",)) or key
            )
            break

    instruction = str(
        _raw_json_value(raw_payload, ("layered_ml_final_instruction",)) or "none"
    ).strip().lower()
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

    return EdgeRow(
        source=source,
        symbol=str(symbol or "").upper() or None,
        market_date=str(market_date or "")[:10] or None,
        decision=str(decision or "") or None,
        score=_raw_float(score),
        confluence_score=_raw_float(_raw_json_value(raw_payload, ("confluence_score",))),
        conviction_score=_raw_float(_raw_json_value(raw_payload, ("conviction_score",))),
        probability_pct=probability_pct,
        probability_source=probability_source,
        instruction=instruction,
        instruction_class=instruction_class,
        forward_return_pct=forward_return,
        forward_mfe_pct=forward_mfe,
    )


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
        rows.append(
            _edge_row_from_raw_payload(
                source="candidate_universe",
                symbol=row["symbol"],
                market_date=row["candidate_ts"],
                decision=row["candidate_status"],
                score=row["score"],
                reason=row["reason"],
                raw_payload=row["candidate_json"],
            )
        )
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


def print_report(source: str, rows: list[EdgeRow], bins: int, min_score: float) -> None:
    total = len(rows)
    outcome_rows = [row for row in rows if row.forward_return_pct is not None]
    probability_rows = [row for row in rows if row.probability_pct is not None]
    instruction_rows = [row for row in rows if row.instruction_class != "unknown"]
    print("\n" + "=" * 78)
    print(f"  {source}")
    print("=" * 78)
    print(f"  rows                              : {total}")
    print(f"  rows with forward outcome          : {len(outcome_rows)} ({_pct(len(outcome_rows), total)})")
    print(f"  rows with probability              : {len(probability_rows)} ({_pct(len(probability_rows), total)})")
    print(f"  rows with layered instruction       : {len(instruction_rows)} ({_pct(len(instruction_rows), total)})")
    if not outcome_rows:
        print("  analysis                           : no forward outcomes available for this source")
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
    parser.add_argument("--min-score", type=float, default=float(os.getenv("CONVICTION_MIN_SCORE", "23")))
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
        print_report(title, rows, args.bins, args.min_score)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
