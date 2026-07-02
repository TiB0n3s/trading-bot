"""Read-only row loading for auto-buy scoring counterfactual reports."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path
from typing import Any

from db import get_read_connection

HORIZONS = (5, 15, 30, 60)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return (end - start) / start * 100.0


def _table_exists(con: Any, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _candidate_json_sql(has_snapshots: bool) -> str:
    return (
        """
        (
            SELECT s.candidate_json
            FROM auto_buy_decision_snapshots s
            WHERE s.symbol = c.symbol
              AND s.candidate_timestamp = c.timestamp
            ORDER BY s.id DESC
            LIMIT 1
        ) AS candidate_json
        """
        if has_snapshots
        else "NULL AS candidate_json"
    )


def _feature_price_at_or_before(
    con: Any,
    symbol: str,
    timestamp: str,
) -> tuple[float | None, str | None]:
    row = con.execute(
        """
        SELECT last_price, timestamp
        FROM feature_snapshots
        WHERE symbol = ?
          AND julianday(timestamp) <= julianday(?)
          AND last_price IS NOT NULL
        ORDER BY julianday(timestamp) DESC, id DESC
        LIMIT 1
        """,
        (symbol, timestamp),
    ).fetchone()
    if not row:
        return None, None
    return _float(row["last_price"]), row["timestamp"]


def _feature_price_at_or_after(
    con: Any,
    symbol: str,
    timestamp: str,
    minutes: int,
) -> tuple[float | None, str | None]:
    row = con.execute(
        """
        SELECT last_price, timestamp
        FROM feature_snapshots
        WHERE symbol = ?
          AND julianday(timestamp) >= julianday(?, ?)
          AND last_price IS NOT NULL
        ORDER BY julianday(timestamp) ASC, id ASC
        LIMIT 1
        """,
        (symbol, timestamp, f"+{minutes} minutes"),
    ).fetchone()
    if not row:
        return None, None
    return _float(row["last_price"]), row["timestamp"]


def load_auto_buy_rows_for_counterfactual_score(
    target_date: str,
    *,
    db_path: Path | str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with get_read_connection(db_path) as con:
        if not _table_exists(con, "auto_buy_candidates"):
            return []
        has_snapshots = _table_exists(con, "auto_buy_decision_snapshots")
        has_features = _table_exists(con, "feature_snapshots")
        candidate_json_sql = _candidate_json_sql(has_snapshots)
        sql = f"""
            SELECT c.*, {candidate_json_sql}
            FROM auto_buy_candidates c
            WHERE substr(c.timestamp, 1, 10) = ?
            ORDER BY c.timestamp, c.id
        """
        params: list[Any] = [target_date]
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = [dict(row) for row in con.execute(sql, params).fetchall()]
        if not has_features:
            return rows
        for row in rows:
            base_price, base_ts = _feature_price_at_or_before(con, row["symbol"], row["timestamp"])
            row["base_price"] = base_price
            row["base_timestamp"] = base_ts
            for minutes in HORIZONS:
                future_price, future_ts = _feature_price_at_or_after(
                    con,
                    row["symbol"],
                    row["timestamp"],
                    minutes,
                )
                row[f"price_{minutes}m"] = future_price
                row[f"timestamp_{minutes}m"] = future_ts
                row[f"return_{minutes}m"] = _pct(base_price, future_price)
        return rows


def load_auto_buy_rows_for_counterfactual_score_range(
    start_date: str,
    end_date: str,
    *,
    db_path: Path | str,
) -> list[dict[str, Any]]:
    """Load a date window with forward returns using one feature-snapshot pass."""

    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with get_read_connection(db_path) as con:
        if not _table_exists(con, "auto_buy_candidates"):
            return []
        has_snapshots = _table_exists(con, "auto_buy_decision_snapshots")
        has_features = _table_exists(con, "feature_snapshots")
        candidate_json_sql = _candidate_json_sql(has_snapshots)
        rows = [
            dict(row)
            for row in con.execute(
                f"""
                SELECT c.*, julianday(c.timestamp) AS candidate_jd, {candidate_json_sql}
                FROM auto_buy_candidates c
                WHERE substr(c.timestamp, 1, 10) BETWEEN ? AND ?
                ORDER BY c.timestamp, c.id
                """,
                (start_date, end_date),
            ).fetchall()
        ]
        if not rows or not has_features:
            return rows

        symbols = sorted({str(row["symbol"]) for row in rows if row.get("symbol")})
        candidate_jds = [_float(row.get("candidate_jd")) for row in rows]
        known_jds = [value for value in candidate_jds if value is not None]
        if not symbols or not known_jds:
            return rows

        placeholders = ",".join("?" for _ in symbols)
        min_jd = min(known_jds) - 1.0
        max_jd = max(known_jds) + (max(HORIZONS) / 1440.0) + 0.05
        feature_rows = con.execute(
            f"""
            SELECT symbol, timestamp, last_price, julianday(timestamp) AS snapshot_jd
            FROM feature_snapshots
            WHERE symbol IN ({placeholders})
              AND julianday(timestamp) BETWEEN ? AND ?
              AND last_price IS NOT NULL
            ORDER BY symbol, snapshot_jd, id
            """,
            [*symbols, min_jd, max_jd],
        ).fetchall()

    by_symbol: dict[str, dict[str, list[Any]]] = defaultdict(
        lambda: {"jds": [], "prices": [], "timestamps": []}
    )
    for feature in feature_rows:
        snapshot_jd = _float(feature["snapshot_jd"])
        price = _float(feature["last_price"])
        if snapshot_jd is None or price is None:
            continue
        series = by_symbol[str(feature["symbol"])]
        series["jds"].append(snapshot_jd)
        series["prices"].append(price)
        series["timestamps"].append(feature["timestamp"])

    for row in rows:
        symbol = str(row.get("symbol") or "")
        series = by_symbol.get(symbol)
        candidate_jd = _float(row.get("candidate_jd"))
        if not series or candidate_jd is None:
            continue
        jds = series["jds"]
        base_index = bisect_right(jds, candidate_jd) - 1
        base_price = series["prices"][base_index] if base_index >= 0 else None
        base_ts = series["timestamps"][base_index] if base_index >= 0 else None
        row["base_price"] = base_price
        row["base_timestamp"] = base_ts
        for minutes in HORIZONS:
            future_jd = candidate_jd + minutes / 1440.0
            future_index = bisect_left(jds, future_jd)
            future_price = (
                series["prices"][future_index] if future_index < len(series["prices"]) else None
            )
            future_ts = (
                series["timestamps"][future_index]
                if future_index < len(series["timestamps"])
                else None
            )
            row[f"price_{minutes}m"] = future_price
            row[f"timestamp_{minutes}m"] = future_ts
            row[f"return_{minutes}m"] = _pct(base_price, future_price)
    return rows
