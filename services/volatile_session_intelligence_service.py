"""Volatile-session intelligence diagnostics.

This service verifies that the research/intelligence layers can be evaluated
under stressed session conditions without granting any new execution authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository
from services.supervised_prediction_training_service import (
    ASYMMETRIC_XGBOOST_FALSE_POSITIVE_PENALTY,
    asymmetric_false_positive_logistic_objective,
)
from services.transformer_authority_model_service import evaluate_transformer_authority
from services.volume_clock_vpin_service import build_volume_clock_vpin_payload


VOLATILE_SESSION_INTELLIGENCE_VERSION = "volatile_session_intelligence_v1"
VOLATILE_SESSION_INTELLIGENCE_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"
MARKET_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class VolatileSymbolAssessment:
    symbol: str
    source_rows: int
    window_rows: int
    vpin_bucket_count: int
    latest_vpin: float | None
    max_vpin: float | None
    toxicity_bucket: str
    transformer_decision: str
    transformer_size_multiplier: float | None
    transformer_probability: float | None
    transformer_reason: str
    latest_feature_timestamp: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _ProbeDTrain:
    def __init__(self, labels: list[float]):
        self._labels = labels

    def get_label(self) -> list[float]:
        return self._labels


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _parse_market_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        hour, minute, *_ = str(value).split(":")
        return time(int(hour), int(minute))
    except Exception:
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MARKET_TZ)
    return parsed.astimezone(MARKET_TZ)


def filter_rows_by_market_time(
    rows: list[dict[str, Any]],
    *,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[dict[str, Any]]:
    start = _parse_market_time(start_time)
    end = _parse_market_time(end_time)
    if start is None and end is None:
        return list(rows)

    filtered: list[dict[str, Any]] = []
    for row in rows:
        parsed = _parse_timestamp(row.get("bar_timestamp"))
        if parsed is None:
            continue
        market_clock = parsed.time()
        if start is not None and market_clock < start:
            continue
        if end is not None and market_clock > end:
            continue
        filtered.append(row)
    return filtered


def asymmetric_penalty_probe(
    *,
    false_positive_penalty: float = ASYMMETRIC_XGBOOST_FALSE_POSITIVE_PENALTY,
) -> dict[str, Any]:
    """Return a direct objective-function probe for false-positive pressure."""
    raw_preds = [2.0, -2.0]
    labels = [0.0, 1.0]
    grad, hess = asymmetric_false_positive_logistic_objective(
        raw_preds,
        _ProbeDTrain(labels),
        false_positive_penalty=false_positive_penalty,
    )
    false_positive_grad = abs(float(grad[0]))
    false_negative_grad = abs(float(grad[1]))
    grad_ratio = false_positive_grad / max(false_negative_grad, 1e-9)
    return {
        "provider": "xgboost_custom_objective",
        "objective": "asymmetric_false_positive_logistic",
        "configured_penalty": float(false_positive_penalty),
        "false_positive_grad": round(false_positive_grad, 6),
        "false_negative_grad": round(false_negative_grad, 6),
        "gradient_penalty_ratio": round(grad_ratio, 6),
        "false_positive_hessian": round(float(hess[0]), 6),
        "false_negative_hessian": round(float(hess[1]), 6),
        "status": "active" if grad_ratio >= float(false_positive_penalty) * 0.95 else "weak",
    }


def build_volatile_session_intelligence_payload(
    *,
    target_date: str,
    symbols: list[str],
    base_dir: Path,
    bucket_volume: float = 500_000.0,
    window_buckets: int = 20,
    start_time: str | None = "09:30",
    end_time: str | None = "10:00",
    timeframe: str = "1m",
    row_limit: int = 20000,
    repo: BarPatternFeatureRepository | None = None,
    transformer_evaluator: Callable[..., dict[str, Any]] = evaluate_transformer_authority,
) -> dict[str, Any]:
    repo = repo or BarPatternFeatureRepository(base_dir / "trades.db")
    assessments: list[VolatileSymbolAssessment] = []
    for raw_symbol in symbols:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        rows = repo.volume_clock_source_rows(
            target_date=target_date,
            symbol=symbol,
            timeframe=timeframe,
            limit=row_limit,
        )
        window_rows = filter_rows_by_market_time(
            rows,
            start_time=start_time,
            end_time=end_time,
        )
        vpin = build_volume_clock_vpin_payload(
            rows=window_rows,
            symbol=symbol,
            target_date=target_date,
            bucket_volume=bucket_volume,
            window_buckets=window_buckets,
        ).to_dict()
        latest_features = dict((window_rows or rows)[-1]) if (window_rows or rows) else {}
        transformer = transformer_evaluator(
            symbol=symbol,
            action="buy",
            account_state={"bar_pattern_features": latest_features},
            registry_path=base_dir / "ml" / "models" / "registry.json",
        )
        assessments.append(
            VolatileSymbolAssessment(
                symbol=symbol,
                source_rows=len(rows),
                window_rows=len(window_rows),
                vpin_bucket_count=int(vpin["summary"]["bucket_count"] or 0),
                latest_vpin=_float(vpin["summary"].get("latest_vpin")),
                max_vpin=_float(vpin["summary"].get("max_vpin")),
                toxicity_bucket=str(vpin["summary"].get("toxicity_bucket") or "unknown"),
                transformer_decision=str(transformer.get("decision") or "unknown"),
                transformer_size_multiplier=_float(transformer.get("size_multiplier")),
                transformer_probability=_float(transformer.get("probability")),
                transformer_reason=str(transformer.get("reason") or ""),
                latest_feature_timestamp=latest_features.get("bar_timestamp"),
            )
        )

    penalty = asymmetric_penalty_probe()
    severe = sum(1 for item in assessments if item.toxicity_bucket == "severe")
    elevated = sum(1 for item in assessments if item.toxicity_bucket == "elevated")
    insufficient = sum(1 for item in assessments if item.toxicity_bucket == "insufficient_buckets")
    transformer_size_down = sum(1 for item in assessments if item.transformer_decision == "size_down")
    transformer_blocks = sum(1 for item in assessments if item.transformer_decision == "block")
    symbols_with_window_rows = sum(1 for item in assessments if item.window_rows > 0)
    return {
        "report_version": VOLATILE_SESSION_INTELLIGENCE_VERSION,
        "runtime_effect": VOLATILE_SESSION_INTELLIGENCE_RUNTIME_EFFECT,
        "target_date": target_date,
        "timeframe": timeframe,
        "market_time_window": {
            "start_time": start_time,
            "end_time": end_time,
            "timezone": "America/New_York",
        },
        "symbol_count": len(assessments),
        "asymmetric_penalty": penalty,
        "summary": {
            "vpin_elevated_or_severe_symbols": elevated + severe,
            "vpin_severe_symbols": severe,
            "vpin_insufficient_symbols": insufficient,
            "transformer_size_down_symbols": transformer_size_down,
            "transformer_block_symbols": transformer_blocks,
            "symbols_with_window_rows": symbols_with_window_rows,
            "diagnostic_ready": (
                bool(assessments)
                and symbols_with_window_rows > 0
                and insufficient < len(assessments)
                and penalty["status"] == "active"
            ),
        },
        "symbols": [item.to_dict() for item in assessments],
    }
