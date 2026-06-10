"""Paper-only learned tie-breaker for auto-buy watch candidates.

The service uses prior candidate-universe forward outcomes to decide whether a
watch candidate has enough historical evidence to become a paper buy. It is
designed as the first narrow authority step after observe-only diagnostics:
it cannot bypass broker/capacity/risk checks, and by default it excludes the
current market date to avoid forward-outcome leakage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from repositories.candidate_universe_repo import CandidateUniverseRepository

LEARNED_AUTO_BUY_TIEBREAKER_VERSION = "learned_auto_buy_tiebreaker_v1"
LEARNED_AUTO_BUY_TIEBREAKER_RUNTIME_EFFECT = "paper_only_tiebreaker_authority"


@dataclass(frozen=True)
class LearnedAutoBuyThresholds:
    min_sample_size: int = 25
    min_win_rate: float = 0.55
    min_avg_return_pct: float = 0.20
    min_avg_mfe_pct: float = 1.00
    max_avg_mae_pct: float = -1.50
    lookback_days: int = 10


@dataclass(frozen=True)
class LearnedAutoBuyDecision:
    qualified: bool
    reason: str
    evidence: dict[str, Any]


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _load_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate")
    return candidate if isinstance(candidate, dict) else payload


def _first_float(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _float(payload.get(key))
        if value is not None:
            return value
    return None


def _forward_return(payload: dict[str, Any]) -> float | None:
    return _first_float(
        payload,
        ("forward_return_pct", "return_60m", "return_30m", "return_eod"),
    )


def _forward_mfe(payload: dict[str, Any]) -> float | None:
    return _first_float(
        payload,
        ("forward_mfe_pct", "max_favorable_60m", "max_favorable_30m", "max_favorable_eod"),
    )


def _forward_mae(payload: dict[str, Any]) -> float | None:
    return _first_float(
        payload,
        ("forward_mae_pct", "max_adverse_60m", "max_adverse_30m", "max_adverse_eod"),
    )


def _pattern_from(row: dict[str, Any], payload: dict[str, Any]) -> str:
    candidate = _candidate_payload(payload)
    return str(
        candidate.get("symbol_pattern")
        or payload.get("symbol_pattern")
        or candidate.get("pattern_label")
        or row.get("setup_label")
        or "unknown"
    )


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _stats(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    returns: list[float] = []
    mfes: list[float] = []
    maes: list[float] = []
    for row in rows:
        payload = _load_json(row.get("candidate_json"))
        ret = _forward_return(payload)
        mfe = _forward_mfe(payload)
        mae = _forward_mae(payload)
        if ret is not None:
            returns.append(ret)
        if mfe is not None:
            mfes.append(mfe)
        if mae is not None:
            maes.append(mae)
    return {
        "sample_size": len(returns),
        "win_rate": round(sum(1 for value in returns if value > 0) / len(returns), 4)
        if returns
        else None,
        "avg_return_pct": _mean(returns),
        "avg_mfe_pct": _mean(mfes),
        "avg_mae_pct": _mean(maes),
    }


def _passes(stats: dict[str, Any], thresholds: LearnedAutoBuyThresholds) -> bool:
    sample = int(stats.get("sample_size") or 0)
    win_rate = _float(stats.get("win_rate"))
    avg_return = _float(stats.get("avg_return_pct"))
    avg_mfe = _float(stats.get("avg_mfe_pct"))
    avg_mae = _float(stats.get("avg_mae_pct"))
    if sample < thresholds.min_sample_size:
        return False
    if win_rate is None or win_rate < thresholds.min_win_rate:
        return False
    if avg_return is None or avg_return < thresholds.min_avg_return_pct:
        return False
    if avg_mfe is None or avg_mfe < thresholds.min_avg_mfe_pct:
        return False
    if avg_mae is not None and avg_mae < thresholds.max_avg_mae_pct:
        return False
    return True


class LearnedAutoBuyTiebreakerService:
    def __init__(
        self,
        repository: CandidateUniverseRepository | None = None,
        thresholds: LearnedAutoBuyThresholds | None = None,
    ):
        self.repository = repository or CandidateUniverseRepository()
        self.thresholds = thresholds or LearnedAutoBuyThresholds()

    def _historical_rows(self, target_date: str) -> list[dict[str, Any]]:
        try:
            end = date.fromisoformat(target_date) - timedelta(days=1)
            start = end - timedelta(days=max(1, self.thresholds.lookback_days - 1))
        except Exception:
            return []
        if start > end:
            return []
        return [
            dict(row)
            for row in self.repository.rows_between(
                start.isoformat(),
                end.isoformat(),
                candidate_kind="entry",
            )
        ]

    def decide(self, candidate: dict[str, Any], *, target_date: str) -> LearnedAutoBuyDecision:
        symbol = str(candidate.get("symbol") or "").upper()
        pattern = str(candidate.get("symbol_pattern") or candidate.get("setup_label") or "unknown")
        if not symbol:
            return LearnedAutoBuyDecision(False, "missing_symbol", {})
        if pattern in {"", "unknown", "held_symbol_not_evaluated"}:
            return LearnedAutoBuyDecision(
                False, "missing_pattern", {"symbol": symbol, "pattern": pattern}
            )

        historical_rows = self._historical_rows(target_date)
        if not historical_rows:
            return LearnedAutoBuyDecision(
                False,
                "no_prior_candidate_outcomes",
                {
                    "version": LEARNED_AUTO_BUY_TIEBREAKER_VERSION,
                    "runtime_effect": LEARNED_AUTO_BUY_TIEBREAKER_RUNTIME_EFFECT,
                    "symbol": symbol,
                    "pattern": pattern,
                },
            )

        symbol_pattern_rows: list[dict[str, Any]] = []
        pattern_rows: list[dict[str, Any]] = []
        for row in historical_rows:
            payload = _load_json(row.get("candidate_json"))
            row_pattern = _pattern_from(row, payload)
            if row_pattern == pattern:
                pattern_rows.append(row)
                if str(row.get("symbol") or "").upper() == symbol:
                    symbol_pattern_rows.append(row)

        symbol_pattern_stats = _stats(symbol_pattern_rows)
        pattern_stats = _stats(pattern_rows)
        evidence = {
            "version": LEARNED_AUTO_BUY_TIEBREAKER_VERSION,
            "runtime_effect": LEARNED_AUTO_BUY_TIEBREAKER_RUNTIME_EFFECT,
            "symbol": symbol,
            "pattern": pattern,
            "thresholds": {
                "min_sample_size": self.thresholds.min_sample_size,
                "min_win_rate": self.thresholds.min_win_rate,
                "min_avg_return_pct": self.thresholds.min_avg_return_pct,
                "min_avg_mfe_pct": self.thresholds.min_avg_mfe_pct,
                "max_avg_mae_pct": self.thresholds.max_avg_mae_pct,
                "lookback_days": self.thresholds.lookback_days,
            },
            "symbol_pattern_stats": symbol_pattern_stats,
            "pattern_stats": pattern_stats,
        }
        if _passes(symbol_pattern_stats, self.thresholds):
            evidence["qualified_bucket"] = "symbol_pattern"
            return LearnedAutoBuyDecision(True, "symbol_pattern_bucket_passed", evidence)
        if _passes(pattern_stats, self.thresholds):
            evidence["qualified_bucket"] = "pattern"
            return LearnedAutoBuyDecision(True, "pattern_bucket_passed", evidence)
        return LearnedAutoBuyDecision(False, "historical_bucket_below_thresholds", evidence)
