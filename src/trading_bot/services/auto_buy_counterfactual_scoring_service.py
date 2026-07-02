"""Observe-only counterfactual scoring for auto-buy candidate rows."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

REPORT_VERSION = "auto_buy_counterfactual_score_v1"
RUNTIME_EFFECT = "diagnostic_only_no_live_authority"

TAPE_REGIME_KEYS = frozenset(
    {
        "negative_session",
        "15m_falling",
        "30m_falling",
        "60m_falling",
        "120m_falling",
        "below_vwap",
        "structural_downtrend",
    }
)
CONTEXT_RISK_KEYS = frozenset({"bias_avoid", "risk_high"})
SETUP_MEMORY_KEYS = frozenset({"setup_avoid", "strategy_memory_caution"})
QUALITY_KEYS = frozenset(
    {
        "setup_favorable",
        "setup_score>=70",
        "early_constructive_build",
        "relative_strength",
        "feature_5m_15m_positive",
        "mom_accel",
        "mom_strong_accel",
        "layered_ml_pass",
        "layered_ml_approval",
    }
)


@dataclass(frozen=True)
class ReasonToken:
    raw: str
    key: str
    delta: float | None


@dataclass(frozen=True)
class ScoreReplayConfig:
    strong_threshold: float = 13.0
    watch_threshold: float = 7.0
    outcome_field: str = "return_60m"
    profitable_return_threshold_pct: float = 0.0


def _row_get(row: dict[str, Any], key: str, default: Any = None) -> Any:
    for candidate in (key, key.lower(), key.upper()):
        if candidate in row:
            return row[candidate]
    return default


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


def _token_key(raw: str) -> str:
    head = raw.strip().split(":", 1)[0].strip().lower()
    return re.sub(r"\([^)]*\)", "", head).strip()


def _token_delta(raw: str) -> float | None:
    matches = re.findall(r"(?:(?<=:)|^)([+-]\d+(?:\.\d+)?)(?=$|[:(])", raw.strip())
    if not matches:
        return None
    return _float(matches[-1])


def parse_reason_tokens(reason: Any) -> list[ReasonToken]:
    if reason is None:
        return []
    parts = [part.strip() for part in str(reason).replace("|", ";").split(";")]
    tokens = []
    for part in parts:
        if not part:
            continue
        tokens.append(ReasonToken(raw=part, key=_token_key(part), delta=_token_delta(part)))
    return tokens


def _key_matches(key: str, family_keys: frozenset[str]) -> bool:
    return any(key == family_key or key.startswith(f"{family_key}_") for family_key in family_keys)


def _negative_family_deltas(
    tokens: list[ReasonToken],
    family_keys: frozenset[str],
) -> list[float]:
    return [
        float(token.delta)
        for token in tokens
        if token.delta is not None and token.delta < 0 and _key_matches(token.key, family_keys)
    ]


def _family_cap_adjustment(
    tokens: list[ReasonToken],
    family_keys: frozenset[str],
    cap: float,
) -> float:
    current = sum(_negative_family_deltas(tokens, family_keys))
    if current >= cap:
        return 0.0
    return cap - current


def _diminishing_tape_adjustment(tokens: list[ReasonToken]) -> float:
    deltas = _negative_family_deltas(tokens, TAPE_REGIME_KEYS)
    if len(deltas) <= 1:
        return 0.0
    adjusted = 0.0
    for index, delta in enumerate(deltas):
        if index == 0:
            weight = 1.0
        elif index == 1:
            weight = 0.5
        else:
            weight = 0.25
        adjusted += delta * weight
    return adjusted - sum(deltas)


def _quality_boost(tokens: list[ReasonToken]) -> float:
    quality_hits = {token.key for token in tokens if _key_matches(token.key, QUALITY_KEYS)}
    if len(quality_hits) >= 3:
        return 3.0
    if len(quality_hits) >= 2:
        return 2.0
    return 0.0


def variant_score(current_score: float, tokens: list[ReasonToken], variant: str) -> float:
    score = current_score
    if variant == "current":
        return round(score, 4)
    if variant == "tape_cap_-8":
        score += _family_cap_adjustment(tokens, TAPE_REGIME_KEYS, -8.0)
    elif variant == "tape_cap_-10":
        score += _family_cap_adjustment(tokens, TAPE_REGIME_KEYS, -10.0)
    elif variant == "diminishing_tape":
        score += _diminishing_tape_adjustment(tokens)
    elif variant == "context_risk_collapsed":
        score += _family_cap_adjustment(tokens, CONTEXT_RISK_KEYS, -5.0)
    elif variant == "setup_memory_cap_-6":
        score += _family_cap_adjustment(tokens, SETUP_MEMORY_KEYS, -6.0)
    elif variant == "candidate_quality_boost":
        score += _quality_boost(tokens)
    elif variant == "tape_cap_-8_context_risk_collapsed":
        score += _family_cap_adjustment(tokens, TAPE_REGIME_KEYS, -8.0)
        score += _family_cap_adjustment(tokens, CONTEXT_RISK_KEYS, -5.0)
    else:
        raise ValueError(f"unknown scoring variant: {variant}")
    return round(score, 4)


def score_bucket(score: float, config: ScoreReplayConfig) -> str:
    if score >= config.strong_threshold:
        return "strong_buy_candidate"
    if score >= config.watch_threshold:
        return "watch"
    return "skip"


def _candidate_json(row: dict[str, Any]) -> dict[str, Any]:
    raw = _row_get(row, "candidate_json")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        payload = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_numeric(row: dict[str, Any], payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _float(_row_get(row, key))
        if value is not None:
            return value
        value = _float(payload.get(key))
        if value is not None:
            return value
    return None


def normalize_replay_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = _candidate_json(row)
    out = dict(row)
    out["score"] = _float(_row_get(row, "score"))
    out["reason"] = _row_get(row, "reason", "")
    out["hard_block_reason"] = _row_get(row, "hard_block_reason") or payload.get(
        "hard_block_reason"
    )
    out["return_5m"] = _first_numeric(row, payload, ("return_5m", "forward_return_5m_pct"))
    out["return_15m"] = _first_numeric(row, payload, ("return_15m", "forward_return_15m_pct"))
    out["return_30m"] = _first_numeric(row, payload, ("return_30m", "forward_return_30m_pct"))
    out["return_60m"] = _first_numeric(
        row,
        payload,
        ("return_60m", "forward_return_60m_pct", "forward_return_pct"),
    )
    out["forward_mfe_pct"] = _first_numeric(
        row,
        payload,
        ("forward_mfe_pct", "max_favorable_60m", "mfe_60m"),
    )
    out["forward_mae_pct"] = _first_numeric(
        row,
        payload,
        ("forward_mae_pct", "max_adverse_60m", "mae_60m"),
    )
    return out


def replay_counterfactual_scores(
    rows: list[dict[str, Any]],
    *,
    config: ScoreReplayConfig | None = None,
    variants: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    config = config or ScoreReplayConfig()
    variants = variants or (
        "current",
        "tape_cap_-8",
        "tape_cap_-10",
        "diminishing_tape",
        "context_risk_collapsed",
        "candidate_quality_boost",
        "tape_cap_-8_context_risk_collapsed",
    )
    normalized = [normalize_replay_row(row) for row in rows]
    scored = [row for row in normalized if row["score"] is not None]

    variant_rows: dict[str, list[dict[str, Any]]] = {variant: [] for variant in variants}
    for row in scored:
        tokens = parse_reason_tokens(row["reason"])
        current_score = float(row["score"])
        current_bucket = score_bucket(current_score, config)
        outcome = _float(row.get(config.outcome_field))
        for variant in variants:
            new_score = variant_score(current_score, tokens, variant)
            new_bucket = score_bucket(new_score, config)
            score_unlock = current_score < config.strong_threshold <= new_score
            result = {
                "timestamp": _row_get(row, "timestamp") or _row_get(row, "candidate_ts"),
                "symbol": _row_get(row, "symbol"),
                "current_decision": _row_get(row, "decision"),
                "current_score_bucket": current_bucket,
                "variant_score_bucket": new_bucket,
                "current_score": current_score,
                "variant_score": new_score,
                "score_delta": round(new_score - current_score, 4),
                "score_unlock": score_unlock,
                "hard_block_reason": row.get("hard_block_reason"),
                "outcome_pct": outcome,
                "forward_mfe_pct": row.get("forward_mfe_pct"),
                "forward_mae_pct": row.get("forward_mae_pct"),
                "reason": row["reason"],
            }
            variant_rows[variant].append(result)

    summaries = []
    for variant, items in variant_rows.items():
        changed = [row for row in items if abs(float(row["score_delta"])) > 0.0001]
        unlocks = [row for row in items if row["score_unlock"]]
        known_unlocks = [row for row in unlocks if row["outcome_pct"] is not None]
        profitable_unlocks = [
            row
            for row in known_unlocks
            if float(row["outcome_pct"]) > config.profitable_return_threshold_pct
        ]
        losing_unlocks = [
            row
            for row in known_unlocks
            if float(row["outcome_pct"]) <= config.profitable_return_threshold_pct
        ]
        summaries.append(
            {
                "variant": variant,
                "rows": len(items),
                "changed_rows": len(changed),
                "avg_score_delta": round(mean([row["score_delta"] for row in changed]), 4)
                if changed
                else 0.0,
                "max_score_delta": max([row["score_delta"] for row in changed], default=0.0),
                "score_unlocks": len(unlocks),
                "known_outcome_unlocks": len(known_unlocks),
                "profitable_unlocks": len(profitable_unlocks),
                "losing_unlocks": len(losing_unlocks),
                "unknown_outcome_unlocks": len(unlocks) - len(known_unlocks),
                "still_hard_blocked_unlocks": sum(1 for row in unlocks if row["hard_block_reason"]),
                "avg_unlock_return_pct": round(
                    mean([float(row["outcome_pct"]) for row in known_unlocks]), 4
                )
                if known_unlocks
                else None,
                "avg_unlock_mfe_pct": round(
                    mean(
                        [
                            float(row["forward_mfe_pct"])
                            for row in unlocks
                            if row["forward_mfe_pct"] is not None
                        ]
                    ),
                    4,
                )
                if any(row["forward_mfe_pct"] is not None for row in unlocks)
                else None,
                "top_unlocks": sorted(
                    unlocks,
                    key=lambda row: (
                        row["outcome_pct"] is not None,
                        float(row["outcome_pct"])
                        if row["outcome_pct"] is not None
                        else -999.0,
                        float(row["score_delta"]),
                    ),
                    reverse=True,
                )[:10],
            }
        )

    return {
        "report_version": REPORT_VERSION,
        "runtime_effect": RUNTIME_EFFECT,
        "row_count": len(normalized),
        "scored_rows": len(scored),
        "strong_threshold": config.strong_threshold,
        "watch_threshold": config.watch_threshold,
        "outcome_field": config.outcome_field,
        "variants": summaries,
    }


def load_rows_from_csv(path: Path | str) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]
