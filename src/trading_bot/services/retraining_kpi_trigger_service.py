"""KPI-based retraining trigger for guarded ML retrain runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RETRAINING_KPI_TRIGGER_VERSION = "retraining_kpi_trigger_v1"


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
    except Exception:
        return None
    return result if result == result else None


def _load_payload(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def evaluate_retraining_kpi_trigger(
    *,
    metrics_path: str | Path | None = None,
    metrics: dict[str, Any] | None = None,
    min_win_rate: float = 0.48,
    min_sharpe_proxy: float = 0.0,
    max_drawdown_pct: float = -2.0,
) -> dict[str, Any]:
    payload = metrics if isinstance(metrics, dict) else _load_payload(metrics_path)
    base = {
        "version": RETRAINING_KPI_TRIGGER_VERSION,
        "runtime_effect": "retraining_trigger_only_no_live_authority",
        "metrics_path": str(metrics_path) if metrics_path else None,
        "retraining_recommended": False,
        "blockers": [],
        "thresholds": {
            "min_win_rate": min_win_rate,
            "min_sharpe_proxy": min_sharpe_proxy,
            "max_drawdown_pct": max_drawdown_pct,
        },
    }
    if not payload:
        return {**base, "status": "missing_metrics", "reason": "KPI metrics unavailable"}

    win_rate = _float(
        payload.get("win_rate")
        or payload.get("same_day_win_rate")
        or payload.get("rolling_win_rate")
    )
    sharpe = _float(payload.get("sharpe_proxy") or payload.get("rolling_sharpe_proxy"))
    drawdown = _float(
        payload.get("max_drawdown_pct")
        or payload.get("rolling_max_drawdown_pct")
        or payload.get("same_day_max_drawdown_pct")
    )
    blockers: list[str] = []
    if win_rate is not None and win_rate < min_win_rate:
        blockers.append(f"win_rate_below_threshold:{win_rate:.4f}<{min_win_rate:.4f}")
    if sharpe is not None and sharpe < min_sharpe_proxy:
        blockers.append(f"sharpe_proxy_below_threshold:{sharpe:.4f}<{min_sharpe_proxy:.4f}")
    if drawdown is not None and drawdown < max_drawdown_pct:
        blockers.append(f"drawdown_below_threshold:{drawdown:.4f}<{max_drawdown_pct:.4f}")
    return {
        **base,
        "status": "retraining_recommended" if blockers else "within_thresholds",
        "retraining_recommended": bool(blockers),
        "blockers": blockers,
        "metrics": {
            "win_rate": win_rate,
            "sharpe_proxy": sharpe,
            "max_drawdown_pct": drawdown,
        },
        "reason": (
            "KPI degradation recommends retraining"
            if blockers
            else "KPI metrics remain within retraining thresholds"
        ),
    }
