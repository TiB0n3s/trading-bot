"""Backfill forward outcomes for captured candidate-universe rows.

The service is analysis-only.  It labels skipped/near-threshold candidates so
offline learning can compare taken trades with missed opportunities.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

import pytz
from repositories.candidate_universe_repo import CandidateUniverseRepository
from services.intelligence.candidates.outcome_coverage import (
    candidate_has_forward_outcome,
    load_candidate_json,
    summarize_candidate_outcome_coverage,
)
from services.rejected_signal_outcome_market_data_service import (
    rejected_signal_outcome_market_data_service,
)

CANDIDATE_OUTCOME_BACKFILL_VERSION = "candidate_outcome_backfill_v1"
CANDIDATE_OUTCOME_RUNTIME_EFFECT = "analysis_backfill_only_no_live_authority"

LOCAL_TZ = pytz.timezone(os.getenv("TRADING_BOT_LOCAL_TZ", "America/Chicago"))
ET = pytz.timezone("America/New_York")
MARKET_OPEN_ET = time(9, 30)
MARKET_CLOSE_ET = time(16, 0)


@dataclass(frozen=True)
class CandidateOutcomeBackfillResult:
    report_version: str
    runtime_effect: str
    date: str
    rows: int
    eligible: int
    updated: int
    skipped_existing: int
    partial: int
    no_bars: int
    error: int
    dry_run: bool
    coverage_before: dict[str, Any]
    projected_coverage_after: dict[str, Any]


def _load_json(raw: Any) -> dict[str, Any]:
    return load_candidate_json(raw)


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = LOCAL_TZ.localize(dt)
    return dt.astimezone(ET)


def _market_open_for_date(target_date: str) -> datetime:
    day = datetime.fromisoformat(target_date).date()
    return ET.localize(datetime.combine(day, MARKET_OPEN_ET))


def _market_close_for_date(target_date: str) -> datetime:
    day = datetime.fromisoformat(target_date).date()
    return ET.localize(datetime.combine(day, MARKET_CLOSE_ET))


def _pct_change(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return round((float(current) - float(base)) / float(base) * 100.0, 6)


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _candidate_reference_price(
    payload: dict[str, Any],
    candidate_payload: dict[str, Any],
) -> float | None:
    for source in (payload, candidate_payload):
        for key in ("reference_price", "mid", "signal_price", "current_price", "price"):
            value = _float(source.get(key))
            if value is not None and value > 0:
                return value
    return None


def _action_adjusted(value: float | None, action: str) -> float | None:
    if value is None:
        return None
    if str(action or "").lower() == "sell":
        return round(-float(value), 6)
    return round(float(value), 6)


def _bar_dt(row: dict[str, Any]) -> datetime:
    return _parse_ts(str(row["timestamp"]))


def _first_bar_at_or_after(
    rows: list[dict[str, Any]], target_dt: datetime
) -> dict[str, Any] | None:
    for row in rows:
        if _bar_dt(row) >= target_dt:
            return row
    return None


def _first_close_at_or_after(rows: list[dict[str, Any]], target_dt: datetime) -> float | None:
    row = _first_bar_at_or_after(rows, target_dt)
    return float(row["close"]) if row else None


def _last_close_at_or_before(rows: list[dict[str, Any]], target_dt: datetime) -> float | None:
    latest = None
    for row in rows:
        if _bar_dt(row) <= target_dt:
            latest = float(row["close"])
    return latest


def _excursion_60m(
    rows: list[dict[str, Any]],
    *,
    reference_price: float,
    start_dt: datetime,
    action: str,
) -> tuple[float | None, float | None]:
    cutoff = start_dt + timedelta(minutes=60)
    highs = []
    lows = []
    for row in rows:
        row_dt = _bar_dt(row)
        if start_dt <= row_dt <= cutoff:
            highs.append(float(row["high"]))
            lows.append(float(row["low"]))
    if not highs or not lows or reference_price <= 0:
        return None, None

    max_up = _pct_change(max(highs), reference_price)
    max_down = _pct_change(min(lows), reference_price)
    if str(action or "").lower() == "sell":
        favorable = _action_adjusted(max_down, "sell")
        adverse = _action_adjusted(max_up, "sell")
    else:
        favorable = max_up
        adverse = max_down

    if favorable is not None:
        favorable = max(0.0, float(favorable))
    if adverse is not None:
        adverse = min(0.0, float(adverse))
    return favorable, adverse


def compute_candidate_outcome(row: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_dt = _parse_ts(str(row["candidate_ts"]))
    action = str(row.get("action") or "buy").lower()
    payload = _load_json(row.get("candidate_json"))
    candidate_payload = (
        payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    )
    captured_reference = _candidate_reference_price(payload, candidate_payload)
    reference_bar = _first_bar_at_or_after(bars, candidate_dt)
    reference_price = captured_reference
    reference_ts = payload.get("quote_ts") or candidate_payload.get("quote_ts")
    reference_source = payload.get("reference_price_source") or candidate_payload.get(
        "reference_price_source"
    )
    if reference_price is None:
        reference_price = float(reference_bar["close"]) if reference_bar else None
        reference_ts = reference_bar.get("timestamp") if reference_bar else None
        reference_source = "first_bar_close_at_or_after_candidate_ts"

    def return_at(minutes: int) -> float | None:
        if reference_price is None:
            return None
        close = _first_close_at_or_after(bars, candidate_dt + timedelta(minutes=minutes))
        return _action_adjusted(_pct_change(close, reference_price), action)

    close_eod = _last_close_at_or_before(
        bars, _market_close_for_date(candidate_dt.date().isoformat())
    )
    mfe_60m, mae_60m = (
        _excursion_60m(
            bars,
            reference_price=reference_price,
            start_dt=candidate_dt,
            action=action,
        )
        if reference_price is not None
        else (None, None)
    )
    values = {
        "candidate_outcome_version": CANDIDATE_OUTCOME_BACKFILL_VERSION,
        "candidate_outcome_source": "candidate_outcome_backfill",
        "forward_reference_price": reference_price,
        "forward_reference_ts": reference_ts,
        "forward_reference_price_source": reference_source,
        "return_5m": return_at(5),
        "return_15m": return_at(15),
        "return_30m": return_at(30),
        "return_60m": return_at(60),
        "return_eod": _action_adjusted(_pct_change(close_eod, reference_price), action),
        "max_favorable_60m": mfe_60m,
        "max_adverse_60m": mae_60m,
        "forward_return_pct": None,
        "forward_mfe_pct": mfe_60m,
        "forward_mae_pct": mae_60m,
    }
    values["forward_return_pct"] = (
        values["return_60m"] or values["return_30m"] or values["return_eod"]
    )

    if not bars or reference_price is None:
        values["label_status"] = "no_bars"
        values["partial_reason"] = "no_bars"
    elif all(
        values[key] is not None for key in ("return_5m", "return_15m", "return_30m", "return_60m")
    ):
        values["label_status"] = "labeled"
        values["partial_reason"] = None
    elif any(
        values[key] is not None
        for key in ("return_5m", "return_15m", "return_30m", "return_60m", "return_eod")
    ):
        values["label_status"] = "partial"
        if candidate_dt + timedelta(minutes=60) > _market_close_for_date(
            candidate_dt.date().isoformat()
        ):
            values["partial_reason"] = "near_close_no_60m_window"
        else:
            values["partial_reason"] = "missing_forward_bars"
    else:
        values["label_status"] = "pending"
        values["partial_reason"] = "pending_forward_bars"

    return values


class CandidateOutcomeBackfillService:
    def __init__(
        self,
        repository: CandidateUniverseRepository | None = None,
        market_data: Any = rejected_signal_outcome_market_data_service,
    ):
        self.repository = repository or CandidateUniverseRepository()
        self.market_data = market_data

    def _fetch_local_feature_snapshot_bars(
        self,
        symbol: str,
        target_date: str,
    ) -> list[dict[str, Any]]:
        db_path = getattr(self.repository, "db_path", None)
        if not db_path:
            return []
        try:
            fetch_local = getattr(self.repository, "feature_snapshot_price_bars", None)
            if not callable(fetch_local):
                return []
            rows = fetch_local(symbol=symbol, target_date=target_date)
        except Exception:
            return []

        bars: list[dict[str, Any]] = []
        for row in rows:
            price = _float(row["last_price"])
            if price is None or price <= 0:
                continue
            bars.append(
                {
                    "timestamp": row["timestamp"],
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "source": "feature_snapshots_last_price",
                }
            )
        return bars

    def _fetch_day_bars(self, symbol: str, target_date: str) -> list[dict[str, Any]]:
        local_bars = self._fetch_local_feature_snapshot_bars(symbol, target_date)
        if local_bars:
            return local_bars
        return self.market_data.fetch_day_bars(
            symbol=symbol,
            start_dt=_market_open_for_date(target_date),
            end_dt=_market_close_for_date(target_date) + timedelta(minutes=1),
        )

    def backfill(
        self,
        target_date: str,
        *,
        symbol: str | None = None,
        limit: int | None = None,
        dry_run: bool = False,
        overwrite: bool = False,
    ) -> CandidateOutcomeBackfillResult:
        all_rows = [dict(row) for row in self.repository.rows_for_date(target_date, symbol=symbol)]
        selected_rows: list[dict[str, Any]] = []
        skipped_existing_total = 0
        for row in all_rows:
            payload = _load_json(row.get("candidate_json"))
            if candidate_has_forward_outcome(payload) and not overwrite:
                skipped_existing_total += 1
                continue
            selected_rows.append(row)

        if limit is not None:
            selected_rows = selected_rows[: max(0, int(limit))]

        bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
        coverage_before = summarize_candidate_outcome_coverage(all_rows)
        projected_rows = [dict(row) for row in all_rows]
        projected_by_id = {
            int(row["id"]): row for row in projected_rows if row.get("id") is not None
        }
        counts = {
            "eligible": 0,
            "updated": 0,
            "skipped_existing": skipped_existing_total,
            "partial": 0,
            "no_bars": 0,
            "error": 0,
        }
        updates: list[tuple[int, dict[str, Any]]] = []

        for row in selected_rows:
            payload = _load_json(row.get("candidate_json"))
            counts["eligible"] += 1
            try:
                row_symbol = str(row["symbol"]).upper()
                if row_symbol not in bars_by_symbol:
                    bars_by_symbol[row_symbol] = self._fetch_day_bars(row_symbol, target_date)
                outcome = compute_candidate_outcome(row, bars_by_symbol[row_symbol])
                if bars_by_symbol[row_symbol] and bars_by_symbol[row_symbol][0].get("source"):
                    outcome["candidate_outcome_price_path_source"] = bars_by_symbol[row_symbol][
                        0
                    ].get("source")
                merged = dict(payload)
                merged.update(outcome)
                if not dry_run:
                    updates.append((int(row["id"]), merged))
                projected_row = projected_by_id.get(int(row["id"]))
                if projected_row is not None:
                    projected_row["candidate_json"] = json.dumps(
                        merged,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                status = outcome.get("label_status")
                if status == "partial":
                    counts["partial"] += 1
                elif status == "no_bars":
                    counts["no_bars"] += 1
                counts["updated"] += 1
            except Exception as exc:
                if not dry_run:
                    merged = dict(payload)
                    merged.update(
                        {
                            "candidate_outcome_version": CANDIDATE_OUTCOME_BACKFILL_VERSION,
                            "candidate_outcome_source": "candidate_outcome_backfill",
                            "label_status": "error",
                            "partial_reason": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    updates.append((int(row["id"]), merged))
                counts["error"] += 1

        if updates:
            update_many = getattr(self.repository, "update_candidate_json_many", None)
            if callable(update_many):
                update_many(updates)
            else:
                for candidate_id, payload in updates:
                    self.repository.update_candidate_json(candidate_id, payload)
        projected_coverage_after = summarize_candidate_outcome_coverage(projected_rows)

        return CandidateOutcomeBackfillResult(
            report_version=CANDIDATE_OUTCOME_BACKFILL_VERSION,
            runtime_effect=CANDIDATE_OUTCOME_RUNTIME_EFFECT,
            date=target_date,
            rows=len(all_rows),
            eligible=counts["eligible"],
            updated=counts["updated"],
            skipped_existing=counts["skipped_existing"],
            partial=counts["partial"],
            no_bars=counts["no_bars"],
            error=counts["error"],
            dry_run=dry_run,
            coverage_before=coverage_before,
            projected_coverage_after=projected_coverage_after,
        )
