"""Detect approved-symbol universe changes and trigger ML retraining.

This service is intentionally stateful and conservative:
- first run records the current universe as the baseline;
- later approved-symbol additions/removals create a retraining trigger;
- newly added symbols must have enough bar-pattern coverage before training;
- triggering retraining never changes live trading authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from db import DB_PATH
from symbols_config import APPROVED_SYMBOLS_LIST, SYMBOL_UNIVERSE_VERSION


DEFAULT_STATE_PATH = Path("runtime_state/symbol_universe_training_state.json")
DEFAULT_MIN_BAR_ROWS = 1000
DEFAULT_MIN_BAR_DAYS = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        return {}
    return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def approved_universe_snapshot() -> dict[str, Any]:
    symbols = sorted({str(symbol).upper().strip() for symbol in APPROVED_SYMBOLS_LIST if str(symbol).strip()})
    payload = {
        "symbol_universe_version": SYMBOL_UNIVERSE_VERSION,
        "approved_symbols": symbols,
        "symbol_count": len(symbols),
    }
    fingerprint_source = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["universe_hash"] = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    return payload


def _symbol_coverage(
    *,
    db_path: Path | str,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    path = Path(db_path)
    if not path.exists():
        return {
            symbol: {
                "rows": 0,
                "trading_days": 0,
                "coverage_status": "missing_db",
            }
            for symbol in symbols
        }
    placeholders = ",".join("?" for _ in symbols)
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bar_pattern_features'"
            ).fetchone()
            if not exists:
                return {
                    symbol: {
                        "rows": 0,
                        "trading_days": 0,
                        "coverage_status": "missing_bar_pattern_features",
                    }
                    for symbol in symbols
                }
            rows = con.execute(
                f"""
                SELECT
                    symbol,
                    COUNT(*) AS rows,
                    COUNT(DISTINCT substr(bar_timestamp, 1, 10)) AS trading_days,
                    MIN(substr(bar_timestamp, 1, 10)) AS first_date,
                    MAX(substr(bar_timestamp, 1, 10)) AS last_date
                FROM bar_pattern_features
                WHERE symbol IN ({placeholders})
                GROUP BY symbol
                """,
                symbols,
            ).fetchall()
    except Exception as exc:
        return {
            symbol: {
                "rows": 0,
                "trading_days": 0,
                "coverage_status": f"coverage_query_failed:{type(exc).__name__}",
            }
            for symbol in symbols
        }

    by_symbol = {
        str(row["symbol"]).upper(): {
            "rows": int(row["rows"] or 0),
            "trading_days": int(row["trading_days"] or 0),
            "first_date": row["first_date"],
            "last_date": row["last_date"],
            "coverage_status": "observed",
        }
        for row in rows
    }
    return {
        symbol: by_symbol.get(
            symbol,
            {
                "rows": 0,
                "trading_days": 0,
                "coverage_status": "no_rows",
            },
        )
        for symbol in symbols
    }


@dataclass(frozen=True)
class UniverseRetrainingAssessment:
    report_version: str
    runtime_effect: str
    status: str
    retraining_required: bool
    retraining_allowed: bool
    reason: str
    current_snapshot: dict[str, Any]
    previous_snapshot: dict[str, Any] | None
    added_symbols: list[str]
    removed_symbols: list[str]
    coverage: dict[str, dict[str, Any]]
    blockers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SymbolUniverseRetrainingService:
    def __init__(
        self,
        *,
        state_path: Path | str = DEFAULT_STATE_PATH,
        db_path: Path | str = DB_PATH,
    ):
        self.state_path = Path(state_path)
        self.db_path = Path(db_path)

    def assess(
        self,
        *,
        min_bar_rows: int = DEFAULT_MIN_BAR_ROWS,
        min_bar_days: int = DEFAULT_MIN_BAR_DAYS,
    ) -> UniverseRetrainingAssessment:
        state = _read_json(self.state_path)
        current = approved_universe_snapshot()
        previous = state.get("last_trained_snapshot") or state.get("last_seen_snapshot")
        if not previous:
            return UniverseRetrainingAssessment(
                report_version="symbol_universe_retraining_v1",
                runtime_effect="state_initialization_only_no_training",
                status="needs_baseline",
                retraining_required=False,
                retraining_allowed=False,
                reason="no previous universe state; initialize baseline before triggering retraining",
                current_snapshot=current,
                previous_snapshot=None,
                added_symbols=[],
                removed_symbols=[],
                coverage={},
                blockers=["missing_previous_universe_state"],
            )

        previous_symbols = {
            str(symbol).upper()
            for symbol in previous.get("approved_symbols", [])
            if str(symbol).strip()
        }
        current_symbols = set(current["approved_symbols"])
        added = sorted(current_symbols - previous_symbols)
        removed = sorted(previous_symbols - current_symbols)
        hash_changed = current.get("universe_hash") != previous.get("universe_hash")
        if not hash_changed:
            return UniverseRetrainingAssessment(
                report_version="symbol_universe_retraining_v1",
                runtime_effect="none",
                status="no_change",
                retraining_required=False,
                retraining_allowed=False,
                reason="approved symbol universe hash unchanged",
                current_snapshot=current,
                previous_snapshot=previous,
                added_symbols=[],
                removed_symbols=[],
                coverage={},
                blockers=[],
            )

        coverage = _symbol_coverage(db_path=self.db_path, symbols=added)
        blockers = []
        for symbol in added:
            item = coverage.get(symbol) or {}
            if int(item.get("rows") or 0) < int(min_bar_rows):
                blockers.append(f"{symbol}:fewer_than_{min_bar_rows}_bar_pattern_rows")
            if int(item.get("trading_days") or 0) < int(min_bar_days):
                blockers.append(f"{symbol}:fewer_than_{min_bar_days}_bar_pattern_days")

        allowed = not blockers
        return UniverseRetrainingAssessment(
            report_version="symbol_universe_retraining_v1",
            runtime_effect="candidate_training_trigger_only_no_live_authority",
            status="ready_for_retraining" if allowed else "pending_bar_coverage",
            retraining_required=True,
            retraining_allowed=allowed,
            reason=(
                "approved symbol universe changed and coverage gates passed"
                if allowed
                else "approved symbol universe changed but added-symbol bar coverage is not ready"
            ),
            current_snapshot=current,
            previous_snapshot=previous,
            added_symbols=added,
            removed_symbols=removed,
            coverage=coverage,
            blockers=blockers,
        )

    def initialize_baseline(self) -> dict[str, Any]:
        current = approved_universe_snapshot()
        state = {
            "report_version": "symbol_universe_retraining_state_v1",
            "last_seen_snapshot": current,
            "last_trained_snapshot": current,
            "last_status": "baseline_initialized",
            "updated_at": _now(),
        }
        _write_json(self.state_path, state)
        return state

    def record_pending(self, assessment: UniverseRetrainingAssessment) -> dict[str, Any]:
        state = _read_json(self.state_path)
        state.update(
            {
                "report_version": "symbol_universe_retraining_state_v1",
                "last_seen_snapshot": assessment.current_snapshot,
                "pending_snapshot": assessment.current_snapshot,
                "pending_added_symbols": assessment.added_symbols,
                "pending_removed_symbols": assessment.removed_symbols,
                "pending_coverage": assessment.coverage,
                "pending_blockers": assessment.blockers,
                "last_status": assessment.status,
                "updated_at": _now(),
            }
        )
        _write_json(self.state_path, state)
        return state

    def record_trained(
        self,
        assessment: UniverseRetrainingAssessment,
        *,
        retrain_exit_code: int,
    ) -> dict[str, Any]:
        state = _read_json(self.state_path)
        state.update(
            {
                "report_version": "symbol_universe_retraining_state_v1",
                "last_seen_snapshot": assessment.current_snapshot,
                "last_trained_snapshot": assessment.current_snapshot,
                "last_trained_added_symbols": assessment.added_symbols,
                "last_trained_removed_symbols": assessment.removed_symbols,
                "last_retrain_exit_code": retrain_exit_code,
                "last_status": "trained_for_universe_change",
                "last_trained_at": _now(),
                "updated_at": _now(),
            }
        )
        for key in (
            "pending_snapshot",
            "pending_added_symbols",
            "pending_removed_symbols",
            "pending_coverage",
            "pending_blockers",
        ):
            state.pop(key, None)
        _write_json(self.state_path, state)
        return state
