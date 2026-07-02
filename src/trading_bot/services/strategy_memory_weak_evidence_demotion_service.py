"""Observe-only demotion replay for weak strategy-memory blockers."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Any

from trading_bot.services.auto_buy_counterfactual_scoring_service import (
    normalize_replay_row,
    parse_reason_tokens,
)

REPORT_VERSION = "strategy_memory_weak_evidence_demotion_v1"
RUNTIME_EFFECT = "diagnostic_only_no_live_authority"

WEAK_MEMORY_KEY = "strategy_memory_avoid_weak_evidence"
WEAK_REASON_PATTERNS = {
    "no_symbol_memory": ("no symbol memory",),
    "sample_too_small": ("sample too small", "sample size too small"),
}

SETUP_BLOCKER_KEYS = frozenset(
    {
        "setup_avoid",
        "setup_block",
        "setup_missing",
        "setup_not_favorable",
        "unclassified_extended_vwap",
        "weak_setup",
    }
)
TAPE_BLOCKER_KEYS = frozenset(
    {
        "negative_session",
        "negative_session_downtrend",
        "negative_session_fading",
        "15m_falling",
        "30m_falling",
        "60m_falling",
        "120m_falling",
        "below_vwap",
        "structural_downtrend",
        "market_regime",
        "regime_block",
    }
)
ML_BLOCKER_KEYS = frozenset(
    {
        "ml_prediction",
        "ml_prediction_weak",
        "prediction_gate",
        "layered_ml",
        "layered_ml_weak",
        "weak_ml",
    }
)
CHASE_BLOCKER_KEYS = frozenset(
    {
        "chase",
        "mature_chase",
        "extreme_chase",
        "extreme_mature_chase",
    }
)
CONTEXT_BLOCKER_KEYS = frozenset({"bias_avoid", "risk_high"})


@dataclass(frozen=True)
class StrategyMemoryDemotionConfig:
    strong_threshold: float = 13.0
    watch_threshold: float = 7.0
    near_threshold_min: float = 10.0
    score_cap_epsilon: float = 0.01
    outcome_field: str = "return_60m"
    profitable_return_threshold_pct: float = 0.25


def _float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value or value == "-":
            return None
        if value.endswith("%"):
            value = value[:-1]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _token_matches(key: str, patterns: frozenset[str]) -> bool:
    return any(key == pattern or key.startswith(f"{pattern}_") for pattern in patterns)


def _hard_block_text(row: dict[str, Any]) -> str:
    return str(row.get("hard_block_reason") or "")


def _weak_reason(text: str) -> str | None:
    lowered = text.lower()
    if WEAK_MEMORY_KEY not in lowered:
        return None
    for label, patterns in WEAK_REASON_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            return label
    return None


def _blocker_families(text: str) -> dict[str, list[str]]:
    tokens = parse_reason_tokens(text)
    families: dict[str, list[str]] = {
        "setup": [],
        "tape": [],
        "ml": [],
        "chase": [],
        "context": [],
    }
    for token in tokens:
        if token.key == WEAK_MEMORY_KEY or token.key.startswith(f"{WEAK_MEMORY_KEY}_"):
            continue
        if _token_matches(token.key, SETUP_BLOCKER_KEYS):
            families["setup"].append(token.raw)
        if _token_matches(token.key, TAPE_BLOCKER_KEYS):
            families["tape"].append(token.raw)
        if _token_matches(token.key, ML_BLOCKER_KEYS):
            families["ml"].append(token.raw)
        if _token_matches(token.key, CHASE_BLOCKER_KEYS):
            families["chase"].append(token.raw)
        if _token_matches(token.key, CONTEXT_BLOCKER_KEYS):
            families["context"].append(token.raw)
    return families


def _score_band(score: float, config: StrategyMemoryDemotionConfig) -> str:
    if score >= config.strong_threshold:
        return "strong_score_ge_13"
    if score >= 12.0:
        return "near_12_to_12_99"
    if score >= 11.0:
        return "near_11_to_11_99"
    if score >= config.near_threshold_min:
        return "near_10_to_10_99"
    return "below_near_threshold"


def _counterfactual_score(score: float, config: StrategyMemoryDemotionConfig) -> float:
    watch_cap = config.strong_threshold - config.score_cap_epsilon
    return round(min(score, watch_cap), 4)


def _summarize(rows: list[dict[str, Any]], config: StrategyMemoryDemotionConfig) -> dict[str, Any]:
    known = [row for row in rows if row["outcome_pct"] is not None]
    returns = [float(row["outcome_pct"]) for row in known]
    return {
        "rows": len(rows),
        "known_outcome_rows": len(known),
        "avg_return_pct": round(mean(returns), 4) if returns else None,
        "median_return_pct": round(median(returns), 4) if returns else None,
        "profitable_rows": sum(
            1 for value in returns if value >= config.profitable_return_threshold_pct
        ),
        "positive_rows": sum(1 for value in returns if value > 0.0),
        "negative_rows": sum(1 for value in returns if value < 0.0),
        "below_ev_bar_rows": sum(
            1 for value in returns if value < config.profitable_return_threshold_pct
        ),
    }


def _group_summaries(
    rows: list[dict[str, Any]],
    key: str,
    config: StrategyMemoryDemotionConfig,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[key]), []).append(row)
    return [
        {"group": group, **_summarize(items, config)}
        for group, items in sorted(groups.items(), key=lambda item: item[0])
    ]


def _row_result(
    row: dict[str, Any],
    config: StrategyMemoryDemotionConfig,
) -> dict[str, Any] | None:
    normalized = normalize_replay_row(row)
    score = _float(normalized.get("score"))
    if score is None:
        return None

    hard_text = _hard_block_text(normalized)
    weak_reason = _weak_reason(hard_text)
    families = _blocker_families(hard_text)
    other_setup_tape_ml_chase = [
        family for family in ("setup", "tape", "ml", "chase") if families[family]
    ]
    score_band = _score_band(score, config)
    meets_score_floor = score >= config.near_threshold_min
    eligible = (
        weak_reason is not None
        and meets_score_floor
        and not other_setup_tape_ml_chase
    )
    remaining_context_blocks = families["context"]
    counterfactual_score = _counterfactual_score(score, config)
    would_watch = (
        eligible
        and not remaining_context_blocks
        and counterfactual_score >= config.watch_threshold
    )

    return {
        "timestamp": normalized.get("timestamp") or normalized.get("candidate_ts"),
        "symbol": normalized.get("symbol"),
        "score": score,
        "score_band": score_band,
        "counterfactual_score": counterfactual_score if eligible else score,
        "counterfactual_bucket": "watch_only" if would_watch else "blocked_or_ineligible",
        "weak_reason": weak_reason,
        "eligible": eligible,
        "would_watch": would_watch,
        "remaining_context_blocks": remaining_context_blocks,
        "other_setup_tape_ml_chase_blocks": other_setup_tape_ml_chase,
        "hard_block_reason": hard_text,
        "outcome_pct": _float(normalized.get(config.outcome_field)),
        "forward_mfe_pct": normalized.get("forward_mfe_pct"),
        "forward_mae_pct": normalized.get("forward_mae_pct"),
        "decision": normalized.get("decision"),
    }


def replay_strategy_memory_weak_evidence_demotion(
    rows: list[dict[str, Any]],
    *,
    config: StrategyMemoryDemotionConfig | None = None,
) -> dict[str, Any]:
    """Replay weak-evidence strategy-memory as watch-only instead of hard block."""

    config = config or StrategyMemoryDemotionConfig()
    normalized = [normalize_replay_row(row) for row in rows]
    row_results = [
        result for row in normalized if (result := _row_result(row, config)) is not None
    ]

    eligible = [row for row in row_results if row["eligible"]]
    would_watch = [row for row in eligible if row["would_watch"]]
    remaining_context = [
        row for row in eligible if row["remaining_context_blocks"] and not row["would_watch"]
    ]
    ineligible_other_blocker = [
        row for row in row_results if row["weak_reason"] and row["other_setup_tape_ml_chase_blocks"]
    ]
    baseline = [
        row
        for row in normalized
        if _float(row.get("score")) is not None
        and float(row["score"]) >= config.near_threshold_min
        and not row.get("hard_block_reason")
    ]
    baseline_rows = [
        {
            "outcome_pct": _float(row.get(config.outcome_field)),
            "score_band": _score_band(float(row["score"]), config),
        }
        for row in baseline
    ]

    watch_summary = _summarize(would_watch, config)
    baseline_summary = _summarize(baseline_rows, config)
    watch_avg = watch_summary["avg_return_pct"]
    baseline_avg = baseline_summary["avg_return_pct"]
    ev_delta = (
        round(float(watch_avg) - float(baseline_avg), 4)
        if watch_avg is not None and baseline_avg is not None
        else None
    )
    passes_net_ev_guard = (
        watch_summary["known_outcome_rows"] > 0
        and watch_avg is not None
        and float(watch_avg) >= 0.0
        and (ev_delta is None or ev_delta >= 0.0)
    )

    return {
        "report_version": REPORT_VERSION,
        "runtime_effect": RUNTIME_EFFECT,
        "row_count": len(normalized),
        "scored_rows": len(row_results),
        "strong_threshold": config.strong_threshold,
        "watch_threshold": config.watch_threshold,
        "near_threshold_min": config.near_threshold_min,
        "score_cap": round(config.strong_threshold - config.score_cap_epsilon, 4),
        "outcome_field": config.outcome_field,
        "profitable_return_threshold_pct": config.profitable_return_threshold_pct,
        "eligible_rows": len(eligible),
        "would_watch_rows": len(would_watch),
        "remaining_context_block_rows": len(remaining_context),
        "ineligible_other_setup_tape_ml_chase_rows": len(ineligible_other_blocker),
        "would_watch_summary": watch_summary,
        "baseline_no_hard_block_summary": baseline_summary,
        "ev_delta_vs_no_hard_block_pct": ev_delta,
        "passes_net_ev_guard": passes_net_ev_guard,
        "would_watch_by_reason": _group_summaries(would_watch, "weak_reason", config),
        "would_watch_by_score_band": _group_summaries(would_watch, "score_band", config),
        "eligible_by_reason": _group_summaries(eligible, "weak_reason", config),
        "eligible_by_score_band": _group_summaries(eligible, "score_band", config),
        "remaining_context_examples": remaining_context[:10],
        "top_profitable_would_watch": sorted(
            [row for row in would_watch if row["outcome_pct"] is not None],
            key=lambda row: float(row["outcome_pct"]),
            reverse=True,
        )[:10],
        "top_losing_would_watch": sorted(
            [row for row in would_watch if row["outcome_pct"] is not None],
            key=lambda row: float(row["outcome_pct"]),
        )[:10],
    }
